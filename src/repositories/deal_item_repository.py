# src/repositories/deal_item_repository.py
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.deal_item import DealItemModel


class DealItemRepository:
    """Репозиторий оборудования сделки. Изоляция по компании — слушатель tenant_scope; здесь — мягкое удаление."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def set_audit_user(self, user_id: int | None) -> None:
        self.session.info["audit_user_id"] = user_id

    async def list_for_deal(self, deal_id: int) -> list[DealItemModel]:
        result = await self.session.execute(
            select(DealItemModel)
            .where(DealItemModel.deal_id == deal_id, DealItemModel.not_deleted_filter())
            .order_by(DealItemModel.position, DealItemModel.id)
        )
        return list(result.scalars().all())

    async def get(self, deal_id: int, item_id: int) -> DealItemModel | None:
        result = await self.session.execute(
            select(DealItemModel).where(
                DealItemModel.id == item_id,
                DealItemModel.deal_id == deal_id,
                DealItemModel.not_deleted_filter(),
            )
        )
        return result.scalar_one_or_none()

    async def count_for_deal(self, deal_id: int) -> int:
        return int(
            (
                await self.session.scalar(
                    select(func.count())
                    .select_from(DealItemModel)
                    .where(DealItemModel.deal_id == deal_id, DealItemModel.not_deleted_filter())
                )
            )
            or 0
        )

    async def max_position(self, deal_id: int) -> int:
        value = await self.session.scalar(
            select(func.max(DealItemModel.position)).where(
                DealItemModel.deal_id == deal_id, DealItemModel.not_deleted_filter()
            )
        )
        return -1 if value is None else int(value)

    async def create(self, item: DealItemModel) -> DealItemModel:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def update(self, item: DealItemModel) -> DealItemModel:
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def soft_delete(self, item: DealItemModel) -> None:
        item.soft_delete(self.session)
        await self.session.commit()

    async def name_usage(self, limit: int) -> list[tuple[str, int]]:
        """Названия оборудования компании и сколько раз каждое встречается (точное совпадение), частые сверху.
        Склейка по регистру и поиск делаются в сервисе: lower()/ILIKE в SQLite не понимают кириллицу,
        а подсказка должна вести себя одинаково на любой базе."""
        result = await self.session.execute(
            select(DealItemModel.name, func.count().label("uses"))
            .where(DealItemModel.not_deleted_filter())
            .group_by(DealItemModel.name)
            .order_by(func.count().desc(), DealItemModel.name)
            .limit(limit)
        )
        return [(row[0], int(row[1])) for row in result.all()]
