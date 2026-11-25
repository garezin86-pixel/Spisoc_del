# src/services/table_query_service.py
"""Запросы Smart Tables (Этап 1, только чтение).

Сервис превращает описание таблицы (источник, колонки, фильтры, сортировка, страница) в SQL-запрос,
сверяясь с реестром. Всё, чего в реестре нет, — 422: произвольный SQL, чужие поля, недопустимая операция
или значение не того типа не доходят до базы.

Читать таблицы клиентов и сделок могут все пользователи компании — как и обычные списки CRM.
Самостоятельные таблицы пользователей (`uct_<id>`, этап 4.3) читает тот, кто их видит: общие — вся компания,
личные — владелец, admin и manager, с ограниченным доступом — они и участники (недоступная таблица — 404).
"""

import math
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Select, func, select

from src.models.user import UserModel
from src.repositories.table_repository import TableRepository
from src.schemas.tables import (
    ColumnSchema,
    SourceSchema,
    TableFilter,
    TableMetaSchema,
    TableRowsSchema,
    TableSort,
)
from src.services.table_registry import (
    OPS_BY_TYPE,
    SOURCES,
    ColumnDef,
    SourceDef,
    custom_columns,
    parse_user_table_source_key,
    user_table_source,
)
from src.services.user_custom_table_service import can_view_table

MAX_FILTERS = 20
MAX_SORTS = 3
MAX_IN_VALUES = 100
MAX_TEXT_VALUE = 200


def _like_pattern(text: str) -> str:
    """Экранирует % и _, чтобы они искались буквально."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _bad(detail: str) -> HTTPException:
    return HTTPException(422, detail)


def _json_value(value: Any) -> Any:
    """Значение ячейки в JSON: деньги числом (как во всём API, см. Money в schemas/deal.py), даты в ISO."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


class TableQueryService:
    def __init__(self, repo: TableRepository):
        self.repo = repo

    # ── описание ─────────────────────────────────────────────────────────────
    async def list_sources(self, current_user: UserModel) -> list[SourceSchema]:
        """Источники: клиенты, сделки, оборудование и самостоятельные таблицы, которые видит пользователь."""
        sources = [SourceSchema(key=s.key, label=s.label) for s in SOURCES.values()]
        member_access = await self.repo.user_table_member_access(current_user.id)
        for table in await self.repo.list_user_tables():
            if can_view_table(table, current_user, member_access.get(table.id)):
                sources.append(SourceSchema(key=f"uct_{table.id}", label=table.name))
        return sources

    async def _resolve(self, source_key: str, current_user: UserModel) -> tuple[SourceDef, dict[str, ColumnDef]]:
        """Источник и его колонки. Самостоятельная таблица строится из её колонок; скрытая — 404."""
        table_id = parse_user_table_source_key(source_key)
        if table_id is not None:
            table = await self.repo.get_user_table(table_id)
            member_can_edit = (await self.repo.user_table_member_access(current_user.id)).get(table_id)
            if table is None or not can_view_table(table, current_user, member_can_edit):
                raise HTTPException(404, "Источник таблицы не найден")
            columns = await self.repo.list_user_columns(table_id)
            source = user_table_source(table, columns, current_user.workspace_id)
            return source, {c.key: c for c in source.columns}
        static = SOURCES.get(source_key)
        if static is None:
            raise HTTPException(404, "Источник таблицы не найден")
        return static, await self._columns(static, current_user.workspace_id)

    async def _columns(self, source: SourceDef, workspace_id: int) -> dict[str, ColumnDef]:
        """Все колонки источника: из реестра плюс свои поля компании (cf_<id>)."""
        columns = {c.key: c for c in source.columns}
        if source.custom_entities:
            fields = await self.repo.list_custom_fields([ce.entity_type for ce in source.custom_entities])
            for col in custom_columns(source, fields, workspace_id):
                columns[col.key] = col
        return columns

    async def meta(self, source_key: str, current_user: UserModel) -> TableMetaSchema:
        source, columns = await self._resolve(source_key, current_user)
        return TableMetaSchema(
            source=source.key,
            label=source.label,
            columns=[
                ColumnSchema(
                    key=c.key,
                    label=c.label,
                    type=c.type,  # type: ignore[arg-type]
                    editable=c.editable,
                    manager_only=c.manager_only,
                    linked=c.linked,
                    filterable=c.filterable,
                    sortable=c.sortable,
                    ops=list(OPS_BY_TYPE[c.type]) if c.filterable else [],  # type: ignore[arg-type]
                    options=list(c.options) if c.options else None,
                )
                for c in columns.values()
            ],
            default_columns=list(source.default_columns),
        )

    # ── проверка пользовательского ввода ─────────────────────────────────────
    @staticmethod
    def _coerce_scalar(col: ColumnDef, value: Any) -> Any:
        """Приводит значение фильтра к типу колонки или говорит 422."""
        if value is None:
            raise _bad(f"Для колонки «{col.key}» нужно значение")
        kind = col.type
        try:
            if kind == "boolean":
                if not isinstance(value, bool):
                    raise ValueError
                return value
            if isinstance(value, bool):  # True/False не годятся ни для чего, кроме boolean
                raise ValueError
            if kind in ("number", "user", "client", "deal"):
                if kind != "number" or col.integer:
                    if isinstance(value, float) and not value.is_integer():
                        raise ValueError
                    return int(value)
                number = Decimal(str(value))
                if not number.is_finite():
                    raise ValueError
                return number
            if kind == "date":
                text = str(value)
                if len(text) < 10:
                    raise ValueError
                return date.fromisoformat(text[:10])
            if kind == "datetime":
                parsed = datetime.fromisoformat(str(value))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            if kind == "select":
                text = str(value)
                if col.options is not None and text not in col.options:
                    raise _bad(f"Недопустимое значение «{text}» для колонки «{col.key}»")
                return text
            text = str(value)  # text
            if len(text) > MAX_TEXT_VALUE:
                raise ValueError
            return text
        except HTTPException:
            raise
        except (ValueError, TypeError, InvalidOperation):
            raise _bad(f"Некорректное значение для колонки «{col.key}»") from None

    def _condition(self, columns: dict[str, ColumnDef], flt: TableFilter) -> Any:
        col = columns.get(flt.field)
        if col is None:
            raise _bad(f"Неизвестная колонка «{flt.field}»")
        if not col.filterable:
            raise _bad(f"По колонке «{col.key}» нельзя фильтровать")
        if flt.op not in OPS_BY_TYPE[col.type]:
            raise _bad(f"Операция «{flt.op}» недопустима для колонки «{col.key}»")

        expr = col.expr
        if flt.op == "is_null":
            return expr.is_(None)
        if flt.op == "not_null":
            return expr.is_not(None)
        if flt.op == "in":
            if not isinstance(flt.value, list) or not flt.value:
                raise _bad(f"Для «in» по колонке «{col.key}» нужен непустой список")
            if len(flt.value) > MAX_IN_VALUES:
                raise _bad(f"В списке «in» не больше {MAX_IN_VALUES} значений")
            return expr.in_([self._coerce_scalar(col, v) for v in flt.value])

        value = self._coerce_scalar(col, flt.value)
        if flt.op == "eq":
            return expr == value
        if flt.op == "ne":
            return (expr != value) | expr.is_(None)  # «не равно» не должно терять пустые значения
        if flt.op == "contains":
            return expr.ilike(_like_pattern(str(value)), escape="\\")
        if flt.op == "gt":
            return expr > value
        if flt.op == "gte":
            return expr >= value
        if flt.op == "lt":
            return expr < value
        return expr <= value  # lte

    def _order(self, source: SourceDef, columns: dict[str, ColumnDef], sorts: list[TableSort]) -> list[Any]:
        order: list[Any] = []
        effective = sorts or [TableSort(field=key, direction=direction) for key, direction in source.default_sort]  # type: ignore[arg-type]
        for item in effective:
            col = columns.get(item.field)
            if col is None:
                raise _bad(f"Неизвестная колонка «{item.field}»")
            if not col.sortable:
                raise _bad(f"По колонке «{col.key}» нельзя сортировать")
            expr = func.lower(col.expr) if col.type == "text" else col.expr
            clause = expr.desc() if item.direction == "desc" else expr.asc()
            order.append(clause.nulls_last())
        # Стабильный порядок для постраничной выдачи
        if not any(item.field == "id" for item in effective):
            order.append(source.model.id.asc())
        return order

    @staticmethod
    def _select_columns(
        source: SourceDef, columns_by_key: dict[str, ColumnDef], requested: list[str] | None
    ) -> list[ColumnDef]:
        keys = list(dict.fromkeys(requested)) if requested else list(source.default_columns)
        columns: list[ColumnDef] = []
        for key in keys:
            col = columns_by_key.get(key)
            if col is None:
                raise _bad(f"Неизвестная колонка «{key}»")
            columns.append(col)
        return columns

    # ── запрос ───────────────────────────────────────────────────────────────
    async def query(
        self,
        source_key: str,
        current_user: UserModel,
        columns: list[str] | None,
        filters: list[TableFilter],
        sorts: list[TableSort],
        page: int,
        size: int,
    ) -> TableRowsSchema:
        if len(filters) > MAX_FILTERS:
            raise _bad(f"Не больше {MAX_FILTERS} условий фильтра")
        if len(sorts) > MAX_SORTS:
            raise _bad(f"Не больше {MAX_SORTS} ключей сортировки")

        source, available = await self._resolve(source_key, current_user)
        selected = self._select_columns(source, available, columns)
        model = source.model
        conditions = [
            model.workspace_id == current_user.workspace_id,
            model.not_deleted_filter(),
            *source.extra_conditions(),
            *[self._condition(available, f) for f in filters],
        ]

        count_stmt: Select = source.joins(select(func.count())).where(*conditions)
        total = await self.repo.count(count_stmt)

        stmt: Select = source.joins(
            select(
                model.id.label("_id"),
                model.updated_at.label("_version"),
                *[c.expr.label(c.key) for c in selected],
            )
        ).where(*conditions)
        stmt = stmt.order_by(*self._order(source, available, sorts)).offset((page - 1) * size).limit(size)

        rows = await self.repo.rows(stmt)
        items = [
            {
                "_id": row["_id"],
                "_version": _json_value(row["_version"]),
                **{c.key: _json_value(row[c.key]) for c in selected},
            }
            for row in rows
        ]
        return TableRowsSchema(
            source=source.key,
            columns=[c.key for c in selected],
            items=items,
            total=total,
            page=page,
            size=size,
            pages=math.ceil(total / size) if size else 0,
        )
