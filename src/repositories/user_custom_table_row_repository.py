# src/repositories/user_custom_table_row_repository.py
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user_custom_table import UserCustomTableCellModel, UserCustomTableRowModel


class UserCustomTableRowRepository:
    """Репозиторий строк и ячеек самостоятельных таблиц. Изоляция по компании — слушатель tenant_scope;
    здесь — мягкое удаление строк."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def set_audit_user(self, user_id: int | None) -> None:
        self.session.info["audit_user_id"] = user_id

    async def count_rows(self, table_id: int) -> int:
        return int(
            (
                await self.session.scalar(
                    select(func.count())
                    .select_from(UserCustomTableRowModel)
                    .where(UserCustomTableRowModel.table_id == table_id, UserCustomTableRowModel.not_deleted_filter())
                )
            )
            or 0
        )

    async def list_rows(self, table_id: int, offset: int, limit: int) -> list[UserCustomTableRowModel]:
        result = await self.session.execute(
            select(UserCustomTableRowModel)
            .where(UserCustomTableRowModel.table_id == table_id, UserCustomTableRowModel.not_deleted_filter())
            .order_by(UserCustomTableRowModel.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_row(self, table_id: int, row_id: int) -> UserCustomTableRowModel | None:
        result = await self.session.execute(
            select(UserCustomTableRowModel).where(
                UserCustomTableRowModel.id == row_id,
                UserCustomTableRowModel.table_id == table_id,
                UserCustomTableRowModel.not_deleted_filter(),
            )
        )
        return result.scalar_one_or_none()

    async def list_cells(self, row_ids: Sequence[int]) -> list[UserCustomTableCellModel]:
        if not row_ids:
            return []
        result = await self.session.execute(
            select(UserCustomTableCellModel).where(UserCustomTableCellModel.row_id.in_(list(row_ids)))
        )
        return list(result.scalars().all())

    async def create_row(
        self, row: UserCustomTableRowModel, cells: list[UserCustomTableCellModel]
    ) -> UserCustomTableRowModel:
        """Строка вместе с заполненными ячейками одной транзакцией."""
        self.session.add(row)
        await self.session.flush()
        for cell in cells:
            cell.row_id = row.id
            self.session.add(cell)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def save_row(self, row: UserCustomTableRowModel) -> UserCustomTableRowModel:
        """Фиксирует изменения строки и её ячеек (ячейки уже изменены в сессии)."""
        await self.session.commit()
        await self.session.refresh(row)
        return row

    def add_cell(self, cell: UserCustomTableCellModel) -> None:
        self.session.add(cell)

    async def soft_delete_row(self, row: UserCustomTableRowModel) -> None:
        row.soft_delete(self.session)
        await self.session.commit()
