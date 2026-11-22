# src/repositories/table_repository.py
from collections.abc import Sequence

from sqlalchemy import RowMapping, Select
from sqlalchemy.ext.asyncio import AsyncSession


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
