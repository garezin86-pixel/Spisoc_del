# src/ai/context.py
"""Контекст выполнения инструмента: кто спрашивает, сессия БД и сервисы CRM поверх неё.

Контекст создаёт транспорт (бот, API) внутри уже привязанной к компании сессии (workspace_context) — инструменты
видят только данные компании пользователя, как и обычные эндпоинты.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.focus_store import focus_store
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
    # Контекст экрана (веб): открытая карточка клиента — «этот клиент», «у него» относятся к нему
    focus_client_id: int | None = None
    focus_client_name: str | None = None
    focus_source: str = "screen"  # "screen" — открытая карточка, "recent" — о ком недавно шла речь
    _now: datetime | None = field(default=None, repr=False)  # фиксированное «сейчас» для тестов

    def __post_init__(self) -> None:
        # Кто делает записи: попадает в audit-лог (как в обычных эндпоинтах и прежнем голосовом обработчике)
        self.session.info["audit_user_id"] = self.user.id

    async def load_recent_focus(self) -> None:
        """Если клиент не задан экраном, берём того, о ком недавно шла речь (find_client, open_client, …)."""
        if self.focus_client_id is not None:
            return
        client_id = await focus_store.recall(self.user.workspace_id, self.user.id)
        if client_id is None:
            return
        try:
            client = await self.clients.get_client(client_id)
        except HTTPException:  # клиента удалили или он из другой компании — забываем
            await focus_store.forget(self.user.workspace_id, self.user.id)
            return
        self.focus_client_id, self.focus_client_name, self.focus_source = client.id, client.name, "recent"

    async def remember_client(self, client) -> None:
        """Запомнить клиента как рабочего: следующие команды без названия относятся к нему."""
        await focus_store.remember(self.user.workspace_id, self.user.id, client.id)

    def focus_hint(self) -> str:
        """Подсказка модели про клиента из контекста; пусто, если такого нет."""
        if self.focus_client_id is None or not self.focus_client_name:
            return ""
        name = self.focus_client_name
        if self.focus_source == "recent":
            return (
                f"\nНедавно в разговоре шла речь о клиенте «{name}». Слова «этот клиент», «у него», «ему» и команды по "
                f"клиенту без названия относятся к нему, если пользователь не назвал другого: "
                f"передавай client=«{name}»."
            )
        return (
            f"\nКонтекст экрана: пользователь сейчас смотрит карточку клиента «{name}». "
            f"Слова «этот клиент», «у него», «ему» и команды по клиенту без названия относятся к нему: "
            f"передавай client=«{name}»."
        )

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
