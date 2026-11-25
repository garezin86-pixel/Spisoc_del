# src/repositories/table_repository.py
from collections.abc import Sequence

from sqlalchemy import RowMapping, Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.custom_field import CustomFieldModel
from src.models.user_custom_table import (
    UserCustomTableColumnModel,
    UserCustomTableMemberModel,
    UserCustomTableModel,
)


class TableRepository:
    """Выполняет подготовленные запросы Smart Tables.

    Сами запросы строит TableQueryService по реестру колонок (src/services/table_registry.py).
    Изоляция по компании: запросы идут через ORM-атрибуты моделей, поэтому слушатель tenant_scope
    добавляет workspace_id сам; сервис дополнительно ставит его явно (двойная защита).
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def count(self, stmt: Select) -> int:
        return int((await self.session.scalar(stmt)) or 0)

    async def rows(self, stmt: Select) -> Sequence[RowMapping]:
        result = await self.session.execute(stmt)
        return result.mappings().all()

    async def list_custom_fields(self, entity_types: Sequence[str]) -> list[CustomFieldModel]:
        """Живые свои поля компании указанных сущностей (изоляция — tenant_scope)."""
        result = await self.session.execute(
            select(CustomFieldModel)
            .where(CustomFieldModel.entity_type.in_(list(entity_types)), CustomFieldModel.not_deleted_filter())
            .order_by(CustomFieldModel.entity_type, CustomFieldModel.position, CustomFieldModel.id)
        )
        return list(result.scalars().all())

    async def list_user_tables(self) -> list[UserCustomTableModel]:
        """Живые самостоятельные таблицы компании (видимость проверяет сервис)."""
        result = await self.session.execute(
            select(UserCustomTableModel)
            .where(UserCustomTableModel.not_deleted_filter())
            .order_by(UserCustomTableModel.name, UserCustomTableModel.id)
        )
        return list(result.scalars().all())

    async def get_user_table(self, table_id: int) -> UserCustomTableModel | None:
        result = await self.session.execute(
            select(UserCustomTableModel).where(
                UserCustomTableModel.id == table_id, UserCustomTableModel.not_deleted_filter()
            )
        )
        return result.scalar_one_or_none()

    async def list_user_columns(self, table_id: int) -> list[UserCustomTableColumnModel]:
        result = await self.session.execute(
            select(UserCustomTableColumnModel)
            .where(UserCustomTableColumnModel.table_id == table_id, UserCustomTableColumnModel.not_deleted_filter())
            .order_by(UserCustomTableColumnModel.position, UserCustomTableColumnModel.id)
        )
        return list(result.scalars().all())

    async def user_table_member_access(self, user_id: int) -> dict[int, bool]:
        """Таблицы, где пользователь участник (видимость restricted): id таблицы → может ли менять строки."""
        result = await self.session.execute(
            select(UserCustomTableMemberModel.table_id, UserCustomTableMemberModel.can_edit).where(
                UserCustomTableMemberModel.user_id == user_id, UserCustomTableMemberModel.not_deleted_filter()
            )
        )
        return {row[0]: bool(row[1]) for row in result.all()}
