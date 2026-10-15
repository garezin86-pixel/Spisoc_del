# src/repositories/scheduled_event_repository.py
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.client import ClientModel
from src.models.interaction import InteractionModel
from src.models.scheduled_event import EventStatus, ScheduledEventModel
from src.models.user import UserModel


class ScheduledEventRepository:
    """Репозиторий запланированных событий. Изоляция по компании — слушатель tenant_scope; здесь — мягкое удаление."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def set_audit_user(self, user_id: int | None) -> None:
        self.session.info["audit_user_id"] = user_id

    async def get(self, event_id: int) -> ScheduledEventModel | None:
        result = await self.session.execute(
            select(ScheduledEventModel).where(
                ScheduledEventModel.id == event_id, ScheduledEventModel.not_deleted_filter()
            )
        )
        return result.scalar_one_or_none()

    async def list_events(
        self,
        offset: int,
        limit: int,
        client_id: int | None = None,
        assignee_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        status: EventStatus | None = None,
    ) -> tuple[list[ScheduledEventModel], int]:
        """Без явного status отменённые не возвращаются."""
        query = select(ScheduledEventModel).where(ScheduledEventModel.not_deleted_filter())
        if status is None:
            query = query.where(ScheduledEventModel.status != EventStatus.cancelled.value)
        else:
            query = query.where(ScheduledEventModel.status == status.value)
        if client_id is not None:
            query = query.where(ScheduledEventModel.client_id == client_id)
        if assignee_id is not None:
            query = query.where(ScheduledEventModel.assignee_id == assignee_id)
        if date_from is not None:
            query = query.where(ScheduledEventModel.starts_at >= date_from)
        if date_to is not None:
            query = query.where(ScheduledEventModel.starts_at < date_to)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.execute(
            query.order_by(ScheduledEventModel.starts_at, ScheduledEventModel.id).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def get_due_for_reminder(
        self, now: datetime, lead: timedelta
    ) -> list[tuple[ScheduledEventModel, str, UserModel]]:
        """События, о которых пора напомнить: запланированы, начнутся в ближайшие `lead`, ещё не напоминали, есть
        ответственный. Уже начавшиеся не берём. Вызывается из планировщика без привязки к компании — видит все."""
        result = await self.session.execute(
            select(ScheduledEventModel, ClientModel.name, UserModel)
            .join(ClientModel, ClientModel.id == ScheduledEventModel.client_id)
            .join(UserModel, UserModel.id == ScheduledEventModel.assignee_id)
            .where(
                ScheduledEventModel.not_deleted_filter(),
                ClientModel.not_deleted_filter(),
                ScheduledEventModel.status == EventStatus.planned.value,
                ScheduledEventModel.reminded_at.is_(None),
                ScheduledEventModel.starts_at > now,
                ScheduledEventModel.starts_at <= now + lead,
            )
            .order_by(ScheduledEventModel.starts_at, ScheduledEventModel.id)
        )
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def client_names(self, client_ids: set[int]) -> dict[int, str]:
        """Названия клиентов по id (для подписи событий в календаре)."""
        if not client_ids:
            return {}
        result = await self.session.execute(
            select(ClientModel.id, ClientModel.name).where(ClientModel.id.in_(client_ids))
        )
        return {row[0]: row[1] for row in result.all()}

    async def create(self, event: ScheduledEventModel) -> ScheduledEventModel:
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def update(self, event: ScheduledEventModel) -> ScheduledEventModel:
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def complete(self, event: ScheduledEventModel, interaction: InteractionModel) -> ScheduledEventModel:
        """Атомарно: создать взаимодействие и пометить событие состоявшимся."""
        self.session.add(interaction)
        await self.session.flush()
        event.status = EventStatus.done.value
        event.completed_interaction_id = interaction.id
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def soft_delete(self, event: ScheduledEventModel) -> None:
        event.soft_delete(self.session)
        await self.session.commit()
