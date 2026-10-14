# src/services/dashboard_service.py
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from src.models.user import UserModel, UserRole
from src.repositories.dashboard_repository import DashboardRepository
from src.repositories.users_repository import UserRepository
from src.schemas.dashboard import (
    DashboardClient,
    DashboardEvent,
    DashboardList,
    DashboardSchema,
    DashboardTask,
)
from src.services.deal_service import DealService

_LIST_LIMIT = 20  # задачи
_CLIENT_LIMIT = 10
_EVENT_LIMIT = 10


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class DashboardService:
    """Рабочий стол: задачи на сегодня и просроченные, клиенты без контакта, ближайшие события, воронка.

    Правила доступа: свой дашборд видит любой пользователь; чужой (`user_id`) — только admin и manager.
    «Сегодня» — календарные сутки в часовом поясе `tz`; просроченные — дедлайн раньше начала сегодняшнего дня
    (задача на сегодня с прошедшим временем остаётся в «сегодня»).
    """

    def __init__(self, repo: DashboardRepository, deal_service: DealService, user_repo: UserRepository):
        self.repo = repo
        self.deal_service = deal_service
        self.user_repo = user_repo

    async def _target_user_id(self, user_id: int | None, current_user: UserModel) -> int:
        if user_id is None or user_id == current_user.id:
            return current_user.id
        if current_user.role not in (UserRole.admin, UserRole.manager):
            raise HTTPException(403, "Чужой дашборд могут смотреть только admin и manager")
        if await self.user_repo.get_by_id(user_id) is None:
            raise HTTPException(404, "Пользователь не найден")
        return user_id

    @staticmethod
    def _zone(tz: str) -> ZoneInfo:
        try:
            return ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise HTTPException(422, f"Неизвестный часовой пояс: {tz}")

    async def get_dashboard(
        self,
        current_user: UserModel,
        user_id: int | None = None,
        tz: str = "UTC",
        stale_days: int = 14,
        events_days: int = 7,
    ) -> DashboardSchema:
        target_id = await self._target_user_id(user_id, current_user)
        zone = self._zone(tz)

        now = datetime.now(timezone.utc)
        today = now.astimezone(zone).date()
        day_start = _as_utc(datetime.combine(today, time.min, tzinfo=zone))
        day_end = _as_utc(datetime.combine(today + timedelta(days=1), time.min, tzinfo=zone))

        today_rows, today_total = await self.repo.tasks_due(target_id, day_start, day_end, _LIST_LIMIT)
        overdue_rows, overdue_total = await self.repo.tasks_due(target_id, None, day_start, _LIST_LIMIT)
        stale_rows, stale_total = await self.repo.stale_clients(
            target_id, now - timedelta(days=stale_days), _CLIENT_LIMIT
        )
        event_rows, event_total = await self.repo.upcoming_events(
            target_id, now, now + timedelta(days=events_days), _EVENT_LIMIT
        )
        pipeline = await self.deal_service.get_summary(current_user, owner_id=target_id)

        stale_clients = []
        for client, last_at in stale_rows:
            baseline = _as_utc(last_at if last_at is not None else client.created_at)
            stale_clients.append(
                DashboardClient(
                    id=client.id,
                    name=client.name,
                    client_type=client.client_type,
                    last_contact_at=last_at,
                    days_since_contact=(now - baseline).days,
                    next_contact_at=client.next_contact_at,
                )
            )

        return DashboardSchema(
            user_id=target_id,
            generated_at=now,
            tz=tz,
            today=today,
            stale_days=stale_days,
            tasks_today=DashboardList(total=today_total, items=[DashboardTask.model_validate(t) for t in today_rows]),
            overdue_tasks=DashboardList(
                total=overdue_total, items=[DashboardTask.model_validate(t) for t in overdue_rows]
            ),
            stale_clients=DashboardList(total=stale_total, items=stale_clients),
            upcoming_events=DashboardList(
                total=event_total,
                items=[
                    DashboardEvent(
                        id=e.id,
                        client_id=e.client_id,
                        client_name=name,
                        type=e.type,
                        title=e.title,
                        starts_at=e.starts_at,
                        duration_minutes=e.duration_minutes,
                        status=e.status,
                    )
                    for e, name in event_rows
                ],
            ),
            pipeline=pipeline,
        )
