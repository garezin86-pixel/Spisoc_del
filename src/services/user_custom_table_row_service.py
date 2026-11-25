# src/services/user_custom_table_row_service.py
"""Строки самостоятельных таблиц (Smart Tables, этап 4.2).

Права: читать строки может каждый, кто видит таблицу; добавлять, править и удалять — каждый, кто видит таблицу,
кроме участников только для чтения (таблица с ограниченным доступом, can_edit=false — 403). В общей таблице это
вся компания (совместная работа), в личной — владелец, admin и manager (чужую личную таблицу не видно вовсе: 404).
Структуру таблицы и участников меняют только владелец, admin и manager (UserCustomTableService).

Значения проверяются по типам колонок (value_coercion — те же правила, что у своих полей). Строка хранит версию
(`updated_at`), которая меняется при записи любой её ячейки; правка с устаревшей версией — 409.
"""

import math
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import HTTPException

from src.models.user import UserModel
from src.models.user_custom_table import (
    CELL_VALUE_COLUMN_BY_TYPE,
    LINK_COLUMN_TYPES,
    UserCustomTableCellModel,
    UserCustomTableColumnModel,
    UserCustomTableRowModel,
)
from src.repositories.client_repository import ClientRepository
from src.repositories.deal_repository import DealRepository
from src.repositories.user_custom_table_row_repository import UserCustomTableRowRepository
from src.repositories.users_repository import UserRepository
from src.schemas.user_custom_table import (
    UserTableRowCreate,
    UserTableRowSchema,
    UserTableRowsPage,
    UserTableRowUpdate,
)
from src.services.row_version import require_current_version
from src.services.user_custom_table_service import UserCustomTableService
from src.services.value_coercion import coerce_value

logger = structlog.get_logger()

MAX_ROWS_PER_TABLE = 50_000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserCustomTableRowService:
    def __init__(
        self,
        row_repo: UserCustomTableRowRepository,
        table_service: UserCustomTableService,
        client_repo: ClientRepository,
        deal_repo: DealRepository,
        user_repo: UserRepository,
    ):
        self.row_repo = row_repo
        self.table_service = table_service
        self.client_repo = client_repo
        self.deal_repo = deal_repo
        self.user_repo = user_repo

    async def _verify_link(self, column: UserCustomTableColumnModel, ref_id: int) -> None:
        """Связь должна вести на существующую запись своей компании (клиент и сделка — не удалённую).
        Читать клиентов и сделки могут все пользователи компании, поэтому отдельной проверки доступа не требуется."""
        if column.data_type == "client":
            found, what = await self.client_repo.get_by_id(ref_id), "Клиент"
        elif column.data_type == "deal":
            found, what = await self.deal_repo.get_deal(ref_id), "Сделка"
        else:
            found, what = await self.user_repo.get_by_id(ref_id), "Пользователь"
        if found is None:
            raise HTTPException(422, f"Колонка «{column.name}»: {what} с id {ref_id} не найден")

    async def _columns_by_key(
        self, table_id: int, user: UserModel, edit: bool = False
    ) -> dict[str, UserCustomTableColumnModel]:
        """Таблица должна быть видна пользователю (иначе 404), а для записи ещё и доступна на правку строк
        (участник только для чтения — 403). Возвращает живые колонки таблицы по ключам c<id>."""
        if edit:
            table = await self.table_service.get_table_for_row_edit(table_id, user)
        else:
            table = await self.table_service.get_visible_table(table_id, user)
        return {c.key: c for c in await self.table_service.list_columns(table.id)}

    @staticmethod
    def _coerce_values(columns: dict[str, UserCustomTableColumnModel], values: dict[str, Any]) -> dict[str, Any]:
        coerced: dict[str, Any] = {}
        for key, raw in values.items():
            column = columns.get(key)
            if column is None:
                raise HTTPException(422, f"Неизвестная колонка «{key}»")
            coerced[key] = coerce_value(column.name, column.data_type, column.options, raw, noun="Колонка")
        return coerced

    @staticmethod
    def _schema(
        row: UserCustomTableRowModel,
        columns: dict[str, UserCustomTableColumnModel],
        cells_by_column: dict[int, UserCustomTableCellModel],
    ) -> UserTableRowSchema:
        values: dict[str, Any] = {}
        for key, column in columns.items():
            cell = cells_by_column.get(column.id)
            values[key] = cell.value_for(column.data_type) if cell is not None else None
        return UserTableRowSchema(
            id=row.id,
            values=values,
            created_by_id=row.created_by_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _row_or_404(self, table_id: int, row_id: int) -> UserCustomTableRowModel:
        row = await self.row_repo.get_row(table_id, row_id)
        if row is None:
            raise HTTPException(404, "Строка не найдена")
        return row

    async def list_rows(self, table_id: int, page: int, size: int, user: UserModel) -> UserTableRowsPage:
        columns = await self._columns_by_key(table_id, user)
        total = await self.row_repo.count_rows(table_id)
        rows = await self.row_repo.list_rows(table_id, (page - 1) * size, size)
        cells: dict[int, dict[int, UserCustomTableCellModel]] = {}
        for cell in await self.row_repo.list_cells([r.id for r in rows]):
            cells.setdefault(cell.row_id, {})[cell.column_id] = cell
        return UserTableRowsPage(
            items=[self._schema(r, columns, cells.get(r.id, {})) for r in rows],
            total=total,
            page=page,
            size=size,
            pages=math.ceil(total / size) if size else 0,
        )

    async def create_row(self, table_id: int, data: UserTableRowCreate, user: UserModel) -> UserTableRowSchema:
        columns = await self._columns_by_key(table_id, user, edit=True)
        coerced = self._coerce_values(columns, data.values)
        for key, value in coerced.items():
            if value is not None and columns[key].data_type in LINK_COLUMN_TYPES:
                await self._verify_link(columns[key], value)
        if await self.row_repo.count_rows(table_id) >= MAX_ROWS_PER_TABLE:
            raise HTTPException(409, f"В таблице не больше {MAX_ROWS_PER_TABLE} строк")
        self.row_repo.set_audit_user(user.id)
        cells = []
        for key, value in coerced.items():
            if value is None:
                continue  # пустое значение ячейкой не хранится
            column = columns[key]
            cell = UserCustomTableCellModel(column_id=column.id)
            setattr(cell, CELL_VALUE_COLUMN_BY_TYPE[column.data_type], value)
            cells.append(cell)
        row = await self.row_repo.create_row(UserCustomTableRowModel(table_id=table_id, created_by_id=user.id), cells)
        await logger.ainfo("user_table_row_created", table_id=table_id, row_id=row.id)
        by_column = {cell.column_id: cell for cell in cells}
        return self._schema(row, columns, by_column)

    async def update_row(
        self, table_id: int, row_id: int, data: UserTableRowUpdate, user: UserModel
    ) -> UserTableRowSchema:
        columns = await self._columns_by_key(table_id, user, edit=True)
        row = await self._row_or_404(table_id, row_id)
        require_current_version(row.updated_at, data.version)
        coerced = self._coerce_values(columns, data.values)

        self.row_repo.set_audit_user(user.id)
        cells = {c.column_id: c for c in await self.row_repo.list_cells([row.id])}
        changed = False
        for key, value in coerced.items():
            column = columns[key]
            attr = CELL_VALUE_COLUMN_BY_TYPE[column.data_type]
            cell = cells.get(column.id)
            current = getattr(cell, attr) if cell is not None else None
            if current == value:
                continue  # значение не изменилось — ничего не пишем (и связь не перепроверяем)
            if value is not None and column.data_type in LINK_COLUMN_TYPES:
                await self._verify_link(column, value)
            if cell is None:
                cell = UserCustomTableCellModel(row_id=row.id, column_id=column.id)
                cells[column.id] = cell
                self.row_repo.add_cell(cell)
            setattr(cell, attr, value)
            changed = True
        if changed:
            row.updated_at = _utcnow()  # новая версия строки
        saved = await self.row_repo.save_row(row)
        if changed:
            await logger.ainfo("user_table_row_updated", table_id=table_id, row_id=row_id)
        return self._schema(saved, columns, cells)

    async def delete_row(self, table_id: int, row_id: int, user: UserModel) -> dict:
        await self._columns_by_key(table_id, user, edit=True)
        row = await self._row_or_404(table_id, row_id)
        self.row_repo.set_audit_user(user.id)
        await self.row_repo.soft_delete_row(row)
        await logger.ainfo("user_table_row_deleted", table_id=table_id, row_id=row_id)
        return {"message": f"Row {row_id} deleted"}
