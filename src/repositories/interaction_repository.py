# src/repositories/interaction_repository.py
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.interaction import InteractionModel


class InteractionRepository:
    """Репозиторий взаимодействий. Изоляция по компании — слушатель tenant_scope; здесь — мягкое удаление."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def set_audit_user(self, user_id: int | None) -> None:
        self.session.info["audit_user_id"] = user_id

    async def list_for_client(self, client_id: int, offset: int, limit: int) -> tuple[list[InteractionModel], int]:
        query = select(InteractionModel).where(
            InteractionModel.client_id == client_id, InteractionModel.not_deleted_filter()
        )
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.execute(
            query.order_by(InteractionModel.occurred_at.desc(), InteractionModel.id.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def get(self, client_id: int, interaction_id: int) -> InteractionModel | None:
        result = await self.session.execute(
            select(InteractionModel).where(
                InteractionModel.id == interaction_id,
                InteractionModel.client_id == client_id,
                InteractionModel.not_deleted_filter(),
            )
        )
        return result.scalar_one_or_none()

    async def last_occurred_at(self, client_id: int) -> datetime | None:
        return await self.session.scalar(
            select(func.max(InteractionModel.occurred_at)).where(
                InteractionModel.client_id == client_id, InteractionModel.not_deleted_filter()
            )
        )

    async def last_activity_many(self, client_ids: list[int]) -> dict[int, tuple[datetime, str]]:
        """Последнее взаимодействие каждого клиента из списка: {client_id: (occurred_at, type)}.
        Один запрос на всю страницу списка (оконная функция), клиенты без взаимодействий в результат не попадают."""
        if not client_ids:
            return {}
        ranked = (
            select(
                InteractionModel.client_id.label("client_id"),
                InteractionModel.occurred_at.label("occurred_at"),
                InteractionModel.type.label("type"),
                func.row_number()
                .over(
                    partition_by=InteractionModel.client_id,
                    order_by=(InteractionModel.occurred_at.desc(), InteractionModel.id.desc()),
                )
                .label("rn"),
            )
            .where(InteractionModel.client_id.in_(client_ids), InteractionModel.not_deleted_filter())
            .subquery()
        )
        result = await self.session.execute(
            select(ranked.c.client_id, ranked.c.occurred_at, ranked.c.type).where(ranked.c.rn == 1)
        )
        return {row[0]: (row[1], row[2]) for row in result.all()}

    async def create(self, interaction: InteractionModel) -> InteractionModel:
        self.session.add(interaction)
        await self.session.commit()
        await self.session.refresh(interaction)
        return interaction

    async def update(self, interaction: InteractionModel) -> InteractionModel:
        await self.session.commit()
        await self.session.refresh(interaction)
        return interaction

    async def soft_delete(self, interaction: InteractionModel) -> None:
        interaction.soft_delete(self.session)
        await self.session.commit()
