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
