# src/repositories/user_custom_table_repository.py
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user_custom_table import (
    UserCustomTableColumnModel,
    UserCustomTableMemberModel,
    UserCustomTableModel,
    UserTableVisibility,
)


class UserCustomTableRepository:
    """Репозиторий самостоятельных таблиц и их колонок. Изоляция по компании — слушатель tenant_scope;
    здесь — мягкое удаление и видимость таблиц."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def set_audit_user(self, user_id: int | None) -> None:
        self.session.info["audit_user_id"] = user_id

    # ── таблицы ──────────────────────────────────────────────────────────────
    async def list_tables(self, visible_to_user_id: int | None) -> list[UserCustomTableModel]:
        """Живые таблицы компании. visible_to_user_id=None — все (admin, manager); иначе общие, свои и те,
        где пользователь участник (при видимости restricted)."""
        query = select(UserCustomTableModel).where(UserCustomTableModel.not_deleted_filter())
        if visible_to_user_id is not None:
            member_of = select(UserCustomTableMemberModel.table_id).where(
                UserCustomTableMemberModel.user_id == visible_to_user_id,
                UserCustomTableMemberModel.not_deleted_filter(),
            )
            query = query.where(
                or_(
                    UserCustomTableModel.visibility == UserTableVisibility.shared.value,
                    UserCustomTableModel.owner_id == visible_to_user_id,
                    and_(
                        UserCustomTableModel.visibility == UserTableVisibility.restricted.value,
                        UserCustomTableModel.id.in_(member_of),
                    ),
                )
            )
        result = await self.session.execute(query.order_by(UserCustomTableModel.name, UserCustomTableModel.id))
        return list(result.scalars().all())

    async def count_tables(self) -> int:
        return int(
            (
                await self.session.scalar(
                    select(func.count())
                    .select_from(UserCustomTableModel)
                    .where(UserCustomTableModel.not_deleted_filter())
                )
            )
            or 0
        )

    async def get_table(self, table_id: int) -> UserCustomTableModel | None:
        result = await self.session.execute(
            select(UserCustomTableModel).where(
                UserCustomTableModel.id == table_id, UserCustomTableModel.not_deleted_filter()
            )
        )
        return result.scalar_one_or_none()

    async def create_table(self, table: UserCustomTableModel, columns: list[UserCustomTableColumnModel]):
        """Таблица вместе с начальными колонками одной транзакцией."""
        self.session.add(table)
        await self.session.flush()
        for column in columns:
            column.table_id = table.id
            self.session.add(column)
        await self.session.commit()
        await self.session.refresh(table)
        return table

    async def update_table(self, table: UserCustomTableModel) -> UserCustomTableModel:
        await self.session.commit()
        await self.session.refresh(table)
        return table

    async def soft_delete_table(self, table: UserCustomTableModel) -> None:
        table.soft_delete(self.session)
        await self.session.commit()

    # ── колонки ──────────────────────────────────────────────────────────────
    async def list_columns(self, table_id: int) -> list[UserCustomTableColumnModel]:
        result = await self.session.execute(
            select(UserCustomTableColumnModel)
            .where(UserCustomTableColumnModel.table_id == table_id, UserCustomTableColumnModel.not_deleted_filter())
            .order_by(UserCustomTableColumnModel.position, UserCustomTableColumnModel.id)
        )
        return list(result.scalars().all())

    async def columns_count_by_table(self, table_ids: list[int]) -> dict[int, int]:
        if not table_ids:
            return {}
        result = await self.session.execute(
            select(UserCustomTableColumnModel.table_id, func.count())
            .where(UserCustomTableColumnModel.table_id.in_(table_ids), UserCustomTableColumnModel.not_deleted_filter())
            .group_by(UserCustomTableColumnModel.table_id)
        )
        return {row[0]: int(row[1]) for row in result.all()}

    async def get_column(self, table_id: int, column_id: int) -> UserCustomTableColumnModel | None:
        result = await self.session.execute(
            select(UserCustomTableColumnModel).where(
                UserCustomTableColumnModel.id == column_id,
                UserCustomTableColumnModel.table_id == table_id,
                UserCustomTableColumnModel.not_deleted_filter(),
            )
        )
        return result.scalar_one_or_none()

    async def max_column_position(self, table_id: int) -> int:
        value = await self.session.scalar(
            select(func.max(UserCustomTableColumnModel.position)).where(
                UserCustomTableColumnModel.table_id == table_id, UserCustomTableColumnModel.not_deleted_filter()
            )
        )
        return -1 if value is None else int(value)

    async def create_column(self, column: UserCustomTableColumnModel) -> UserCustomTableColumnModel:
        self.session.add(column)
        await self.session.commit()
        await self.session.refresh(column)
        return column

    async def update_column(self, column: UserCustomTableColumnModel) -> UserCustomTableColumnModel:
        await self.session.commit()
        await self.session.refresh(column)
        return column

    async def soft_delete_column(self, column: UserCustomTableColumnModel) -> None:
        column.soft_delete(self.session)
        await self.session.commit()

    # ── участники (ограниченный доступ) ──────────────────────────────────────
    async def get_member(self, table_id: int, user_id: int) -> UserCustomTableMemberModel | None:
        """Живой участник таблицы."""
        result = await self.session.execute(
            select(UserCustomTableMemberModel).where(
                UserCustomTableMemberModel.table_id == table_id,
                UserCustomTableMemberModel.user_id == user_id,
                UserCustomTableMemberModel.not_deleted_filter(),
            )
        )
        return result.scalar_one_or_none()

    async def member_access(self, user_id: int) -> dict[int, bool]:
        """Таблицы, где пользователь участник: id таблицы → может ли менять строки."""
        result = await self.session.execute(
            select(UserCustomTableMemberModel.table_id, UserCustomTableMemberModel.can_edit).where(
                UserCustomTableMemberModel.user_id == user_id, UserCustomTableMemberModel.not_deleted_filter()
            )
        )
        return {row[0]: bool(row[1]) for row in result.all()}

    async def list_members(self, table_id: int, include_deleted: bool = False) -> list[UserCustomTableMemberModel]:
        query = select(UserCustomTableMemberModel).where(UserCustomTableMemberModel.table_id == table_id)
        if not include_deleted:
            query = query.where(UserCustomTableMemberModel.not_deleted_filter())
        result = await self.session.execute(query.order_by(UserCustomTableMemberModel.id))
        return list(result.scalars().all())

    def add_member(self, member: UserCustomTableMemberModel) -> None:
        self.session.add(member)

    async def commit(self) -> None:
        await self.session.commit()
