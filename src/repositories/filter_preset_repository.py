# src/repositories/filter_preset_repository.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.filter_preset import FilterPresetModel


class FilterPresetRepository:
    """Без Abstract-обёртки — по аналогии с TagRepository: сущность простая,
    полноценный DI через ABC для неё избыточен."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all_for_user(self, user_id: int) -> list[FilterPresetModel]:
        result = await self.session.execute(
            select(FilterPresetModel).where(FilterPresetModel.user_id == user_id).order_by(FilterPresetModel.created_at)
        )
        return list(result.scalars().all())

    async def get_by_id(self, preset_id: int) -> FilterPresetModel | None:
        result = await self.session.execute(select(FilterPresetModel).where(FilterPresetModel.id == preset_id))
        return result.scalar_one_or_none()

    async def create(self, preset: FilterPresetModel) -> FilterPresetModel:
        self.session.add(preset)
        await self.session.commit()
        await self.session.refresh(preset)
        return preset

    async def delete(self, preset: FilterPresetModel) -> None:
        await self.session.delete(preset)
        await self.session.commit()
