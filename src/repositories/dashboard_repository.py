# src/repositories/dashboard_repository.py
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.client import ClientModel
from src.models.enums import TaskStatus
from src.models.interaction import InteractionModel
from src.models.scheduled_event import EventStatus, ScheduledEventModel
from src.models.task import SpisokModel


class DashboardRepository:
    """Выборки для дашборда. Изоляция по компании — слушатель tenant_scope; здесь — мягкое удаление.

    Все методы возвращают (строки, общее количество): строк не больше `limit`, количество — без учёта лимита.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _page(self, query, order_by, limit: int) -> tuple[list, int]:
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.execute(query.order_by(*order_by).limit(limit))
        return list(result.all()), total or 0

    async def tasks_due(
        self, user_id: int, date_from: datetime | None, date_to: datetime, limit: int
    ) -> tuple[list[SpisokModel], int]:
        """Незавершённые задачи пользователя с дедлайном в [date_from, date_to); без date_from — всё раньше date_to."""
        query = select(SpisokModel).where(
            SpisokModel.not_deleted_filter(),
            SpisokModel.user_id == user_id,
            SpisokModel.status != TaskStatus.done,
            SpisokModel.deadline.is_not(None),
            SpisokModel.deadline < date_to,
        )
        if date_from is not None:
            query = query.where(SpisokModel.deadline >= date_from)
        rows, total = await self._page(query, (SpisokModel.deadline, SpisokModel.id), limit)
        return [row[0] for row in rows], total

    async def stale_clients(
        self, owner_id: int, cutoff: datetime, limit: int
    ) -> tuple[list[tuple[ClientModel, datetime | None]], int]:
        """Клиенты ответственного, с которыми не было контакта с `cutoff`: последнее взаимодействие раньше cutoff,
        а если их нет — клиент создан раньше cutoff. Самые давние сверху."""
        last = (
            select(InteractionModel.client_id, func.max(InteractionModel.occurred_at).label("last_at"))
            .where(InteractionModel.not_deleted_filter())
            .group_by(InteractionModel.client_id)
            .subquery()
        )
        baseline = func.coalesce(last.c.last_at, ClientModel.created_at)
        query = (
            select(ClientModel, last.c.last_at)
            .outerjoin(last, last.c.client_id == ClientModel.id)
            .where(ClientModel.not_deleted_filter(), ClientModel.owner_id == owner_id, baseline < cutoff)
        )
        rows, total = await self._page(query, (baseline, ClientModel.id), limit)
        return [(row[0], row[1]) for row in rows], total

    async def upcoming_events(
        self, assignee_id: int, date_from: datetime, date_to: datetime, limit: int
    ) -> tuple[list[tuple[ScheduledEventModel, str]], int]:
        """Запланированные события ответственного в [date_from, date_to) вместе с названием клиента."""
        query = (
            select(ScheduledEventModel, ClientModel.name)
            .join(ClientModel, ClientModel.id == ScheduledEventModel.client_id)
            .where(
                ScheduledEventModel.not_deleted_filter(),
                ClientModel.not_deleted_filter(),
                ScheduledEventModel.assignee_id == assignee_id,
                ScheduledEventModel.status == EventStatus.planned.value,
                ScheduledEventModel.starts_at >= date_from,
                ScheduledEventModel.starts_at < date_to,
            )
        )
        rows, total = await self._page(query, (ScheduledEventModel.starts_at, ScheduledEventModel.id), limit)
        return [(row[0], row[1]) for row in rows], total
