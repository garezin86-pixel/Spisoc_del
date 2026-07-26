# src/repositories/calendar_repository.py
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.task import SpisokModel
from src.models.user import UserModel


class CalendarRepository:
    """
    Отдельный маленький репозиторий, а не расширение UserRepository/
    TaskRepository — намеренно: логика завязана на нестандартную для
    остального приложения аутентификацию (токен в query-параметре, без
    get_current_user), и не хочется тянуть эту специфику через абстрактные
    интерфейсы репозиториев, которыми пользуется вся остальная кодовая база
    (пришлось бы реализовывать заглушки в mock_repositories.py ради двух
    запросов, нужных только здесь).
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_by_calendar_token(self, token: str) -> UserModel | None:
        return await self.session.scalar(select(UserModel).where(UserModel.calendar_feed_token == token))

    async def get_tasks_with_deadline_for_user(self, user_id: int) -> list[SpisokModel]:
        """
        Задачи с дедлайном, где пользователь автор ИЛИ исполнитель — тот же
        круг, что получает уведомления о задаче (см. notify_task_assigned).
        """
        result = await self.session.execute(
            select(SpisokModel)
            .where(
                SpisokModel.deadline.is_not(None),
                SpisokModel.deleted_at.is_(None),
                or_(SpisokModel.user_id == user_id, SpisokModel.author_id == user_id),
            )
            .order_by(SpisokModel.deadline)
        )
        return list(result.scalars().all())

    async def set_calendar_token(self, user: UserModel, token: str) -> UserModel:
        user.calendar_feed_token = token
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user
