# src/ai/context.py
"""Контекст выполнения инструмента: кто спрашивает, сессия БД и сервисы CRM поверх неё.

Контекст создаёт транспорт (бот, API) внутри уже привязанной к компании сессии (workspace_context) — инструменты
видят только данные компании пользователя, как и обычные эндпоинты.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import UserModel
from src.repositories.client_repository import ClientRepository
from src.repositories.dashboard_repository import DashboardRepository
from src.repositories.deal_repository import DealRepository
from src.repositories.groups_repository import GroupRepository
from src.repositories.interaction_repository import InteractionRepository
from src.repositories.tag_repository import TagRepository
from src.repositories.task_repository import TaskRepository
from src.repositories.users_repository import UserRepository
from src.services.client_service import ClientService
from src.services.deal_service import DealService
from src.services.interaction_service import InteractionService
from src.services.task_service import TaskService

LOCAL_TZ = ZoneInfo("Europe/Kyiv")  # как в боте и напоминаниях: «завтра в 10» — по Киеву


@dataclass
class AIContext:
    user: UserModel
    session: AsyncSession
    tz: ZoneInfo = LOCAL_TZ
    _now: datetime | None = field(default=None, repr=False)  # фиксированное «сейчас» для тестов

    def __post_init__(self) -> None:
        # Кто делает записи: попадает в audit-лог (как в обычных эндпоинтах и прежнем голосовом обработчике)
        self.session.info["audit_user_id"] = self.user.id

    def now(self) -> datetime:
        return self._now or datetime.now(timezone.utc)

    @cached_property
    def users(self) -> UserRepository:
        return UserRepository(self.session)

    @cached_property
    def client_repo(self) -> ClientRepository:
        return ClientRepository(self.session)

    @cached_property
    def dashboard_repo(self) -> DashboardRepository:
        return DashboardRepository(self.session)

    @cached_property
    def clients(self) -> ClientService:
        return ClientService(self.client_repo, self.users)

    @cached_property
    def deals(self) -> DealService:
        return DealService(DealRepository(self.session), self.client_repo, self.users)

    @cached_property
    def interactions(self) -> InteractionService:
        return InteractionService(self.client_repo, InteractionRepository(self.session))

    @cached_property
    def tasks(self) -> TaskService:
        return TaskService(
            task_repo=TaskRepository(self.session),
            user_repo=self.users,
            group_repo=self.groups,
            tag_repo=TagRepository(self.session),
            session=self.session,
        )

    @cached_property
    def task_repo(self) -> TaskRepository:
        return TaskRepository(self.session)

    @cached_property
    def groups(self) -> GroupRepository:
        return GroupRepository(self.session)
