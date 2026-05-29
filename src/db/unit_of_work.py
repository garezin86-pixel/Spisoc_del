from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.repositories.users_repository import UserRepository
from src.repositories.task_repository import TaskRepository
from src.repositories.groups_repository import GroupRepository
from src.repositories.other_repositories import (
    CommentRepository,
    NotificationRepository,
)
from src.repositories.other_repositories import NotificationSettingsRepository  # НОВЫЙ
from src.repositories.audit_repository import AuditRepository


class UnitOfWork:
    def __init__(self, session_maker: async_sessionmaker):
        self._session_maker = session_maker

    async def __aenter__(self):
        self._session: AsyncSession = self._session_maker()
        self.users = UserRepository(self._session)
        self.tasks = TaskRepository(self._session)
        self.groups = GroupRepository(self._session)
        self.comments = CommentRepository(self._session)
        self.notifications = NotificationRepository(self._session)
        self.notification_settings = NotificationSettingsRepository(self._session)
        self.audit = AuditRepository(self._session)
        return self

    def set_audit_user(self, user_id: int | None) -> None:
        """Устанавливает пользователя для audit_log на время этой сессии."""
        self.session.info["audit_user_id"] = user_id

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await self.rollback()
        await self._session.close()

    async def commit(self):
        await self._session.commit()

    async def rollback(self):
        await self._session.rollback()

    @property
    def session(self):
        return self._session
