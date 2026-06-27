from datetime import datetime, timedelta
from typing import Dict, List, Optional

import sqlalchemy as sa
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import GroupModel, UserModel
from src.models.comment import CommentModel
from src.models.notification_log import NotificationLogModel
from src.models.notification_settings import NotificationSettingsModel
from src.models.task import SpisokModel, TaskStatus
from src.repositories.abstract.base_other_repositories import (
    AbstractCommentRepository,
    AbstractNotificationRepository,
    AbstractStatsRepository,
)
from src.schemas.stats import UsersStats


class CommentRepository(AbstractCommentRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, comment: CommentModel) -> CommentModel:
        self.session.add(comment)
        await self.session.commit()
        await self.session.refresh(comment, ["created_at", "user"])
        return comment

    async def get_by_task(self, task_id: int) -> list[CommentModel]:
        result = await self.session.execute(
            select(CommentModel)
            .options(
                selectinload(CommentModel.user),
                selectinload(CommentModel.task),
            )
            .where(CommentModel.task_id == task_id)
        )
        return list(result.scalars().all())

    async def select_query(self, task_id: int):
        query = select(CommentModel).where(CommentModel.task_id == task_id).options(selectinload(CommentModel.user))
        return query

    async def get_total_tasks(self, query):
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        return total

    async def get_by_task_offset_limit(self, query, offset, limit):
        query = query.offset(offset).limit(limit).order_by(CommentModel.created_at.desc())
        result = await self.session.execute(query)
        comments = result.scalars().all()
        return comments


class NotificationRepository(AbstractNotificationRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_comment_with_relations(self, comment_id: int) -> CommentModel | None:
        result = await self.session.execute(
            select(CommentModel)
            .options(
                selectinload(CommentModel.user),
                selectinload(CommentModel.task).selectinload(SpisokModel.author),
                selectinload(CommentModel.task).selectinload(SpisokModel.user),
            )
            .where(CommentModel.id == comment_id)
        )
        return result.scalar_one_or_none()

    async def get_task_with_relations(self, task_id: int) -> SpisokModel | None:
        stmt = (
            select(SpisokModel)
            .where(SpisokModel.id == task_id)
            .options(
                selectinload(SpisokModel.user),
                selectinload(SpisokModel.group).selectinload(GroupModel.users),
                selectinload(SpisokModel.author),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    ################### добавил в репозиторий
    async def create_log(
        self,
        user_id: int,
        notification_type: str,
        content: str,
        task_id: Optional[int] = None,
        success: bool = True,
        error: Optional[str] = None,
    ) -> NotificationLogModel:
        """Создание записи в логе уведомлений"""
        log = NotificationLogModel(
            user_id=user_id,
            notification_type=notification_type,
            task_id=task_id,
            content=content,
            success=success,
            error=error,
            sent_at=datetime.utcnow(),
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def check_already_sent(
        self,
        user_id: int,
        task_id: Optional[int],
        notification_type: str,
        hours_back: Optional[int] = None,
    ) -> bool:
        """Проверка, было ли уже отправлено уведомление"""
        query = select(NotificationLogModel.id).where(
            NotificationLogModel.user_id == user_id,
            NotificationLogModel.notification_type == notification_type,
            NotificationLogModel.success.is_(True),
        )

        if task_id is not None:
            query = query.where(NotificationLogModel.task_id == task_id)

        if hours_back is not None:
            since = datetime.utcnow() - timedelta(hours=hours_back)
            query = query.where(NotificationLogModel.sent_at >= since)

        result = await self.session.execute(query.limit(1))
        return result.scalar() is not None

    async def get_admin_statistics(
        self,
        days: int = 7,
        top_users_limit: int = 10,
    ) -> dict:
        """Returns aggregated notification statistics for the admin dashboard."""
        since = datetime.utcnow() - timedelta(days=days)

        total = await self.session.scalar(select(func.count()).select_from(NotificationLogModel))
        total_success = await self.session.scalar(
            select(func.count()).select_from(NotificationLogModel).where(NotificationLogModel.success.is_(True))
        )

        type_stats = await self.session.execute(
            select(
                NotificationLogModel.notification_type,
                func.count().label("count"),
                func.sum(func.cast(NotificationLogModel.success, sa.Integer)).label("success_count"),
            ).group_by(NotificationLogModel.notification_type)
        )

        daily_stats = await self.session.execute(
            select(
                func.date(NotificationLogModel.sent_at).label("date"),
                func.count().label("count"),
                func.sum(func.cast(NotificationLogModel.success, sa.Integer)).label("success_count"),
            )
            .where(NotificationLogModel.sent_at >= since)
            .group_by(func.date(NotificationLogModel.sent_at))
            .order_by(func.date(NotificationLogModel.sent_at).desc())
        )

        top_users = await self.session.execute(
            select(
                UserModel.username,
                UserModel.telegram_id,
                func.count(NotificationLogModel.id).label("total"),
                func.sum(func.cast(NotificationLogModel.success, sa.Integer)).label("success"),
            )
            .join(NotificationLogModel.user)
            .group_by(UserModel.id, UserModel.username, UserModel.telegram_id)
            .order_by(func.count(NotificationLogModel.id).desc())
            .limit(top_users_limit)
        )

        return {
            "total": total or 0,
            "total_success": total_success or 0,
            "type_stats": type_stats.all(),
            "daily_stats": daily_stats.all(),
            "top_users": top_users.all(),
        }

    async def get_tasks_by_deadline_window(self, start: datetime, end: datetime, user_id: Optional[int] = None):
        """Поиск задач по окну дедлайна"""
        query = select(SpisokModel).where(SpisokModel.deadline.between(start, end))

        if user_id:
            query = query.where(SpisokModel.user_id == user_id)

        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_overdue_tasks(self, now: datetime, user_id: Optional[int] = None):
        """Поиск просроченных задач"""
        query = select(SpisokModel).where(SpisokModel.deadline < now, SpisokModel.status != TaskStatus.done)

        if user_id:
            query = query.where(SpisokModel.user_id == user_id)

        result = await self.session.execute(query)
        return result.scalars().all()


class NotificationSettingsRepository:
    """Репозиторий для работы с настройками уведомлений"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user(self, user_id: int) -> Optional[NotificationSettingsModel]:
        """
        Получить настройки уведомлений для конкретного пользователя.

        Args:
            user_id: ID пользователя

        Returns:
            Настройки уведомлений или None, если не найдены
        """
        query = select(NotificationSettingsModel).where(NotificationSettingsModel.user_id == user_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_users_with_weekly_report(self):
        """
        Получить всех пользователей с включённой еженедельной сводкой.
        Выполняет JOIN с таблицей users.

        Returns:
            Список пользователей, у которых weekly_report_enabled = True
        """
        query = (
            select(UserModel)
            .join(
                NotificationSettingsModel,
                UserModel.id == NotificationSettingsModel.user_id,
            )
            .where(
                NotificationSettingsModel.weekly_report_enabled.is_(True),
                UserModel.telegram_id.is_not(None),  # Только с Telegram ID
                UserModel.is_active.is_(True),  # Только активные
            )
        )

        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_users_with_group_notifications(self):
        """
        Получить пользователей с включёнными уведомлениями о назначении на группу.
        Выполняет JOIN с таблицей users.

        Returns:
            Список пользователей, у которых notify_group_assigned = True
        """
        query = (
            select(UserModel)
            .join(
                NotificationSettingsModel,
                UserModel.id == NotificationSettingsModel.user_id,
            )
            .where(
                NotificationSettingsModel.notify_group_assigned.is_(True),
                UserModel.telegram_id.is_not(None),  # Только с Telegram ID
                UserModel.is_active.is_(True),  # Только активные
            )
        )

        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_users_with_all_notifications(self):
        """
        Получить пользователей у которых включены любые уведомления.
        Используется для массовой рассылки.

        Returns:
            Список пользователей с хотя бы одним включённым типом уведомлений
        """
        query = (
            select(UserModel)
            .join(
                NotificationSettingsModel,
                UserModel.id == NotificationSettingsModel.user_id,
            )
            .where(
                (
                    (NotificationSettingsModel.notify_deadline_24h.is_(True))
                    | (NotificationSettingsModel.notify_deadline_1h.is_(True))
                    | (NotificationSettingsModel.notify_overdue.is_(True))
                    | (NotificationSettingsModel.weekly_report_enabled.is_(True))
                    | (NotificationSettingsModel.notify_group_assigned.is_(True))
                    | (NotificationSettingsModel.notify_task_assigned.is_(True))
                    | (NotificationSettingsModel.notify_task_updated.is_(True))
                    | (NotificationSettingsModel.notify_comment.is_(True))
                ),
                UserModel.telegram_id.is_not(None),
                UserModel.is_active.is_(
                    True,
                ),
            )
        )

        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_by_user_ids(self, user_ids: List[int]) -> Dict[int, NotificationSettingsModel]:
        """
        Получить настройки для нескольких пользователей одним запросом.
        Используется для оптимизации (решение проблемы N+1).

        Args:
            user_ids: Список ID пользователей

        Returns:
            Словарь {user_id: NotificationSettingsModel}
        """
        if not user_ids:
            return {}

        query = select(NotificationSettingsModel).where(NotificationSettingsModel.user_id.in_(user_ids))
        result = await self.session.execute(query)
        settings_list = result.scalars().all()

        return {settings.user_id: settings for settings in settings_list}

    async def create_or_update(self, user_id: int, **kwargs) -> NotificationSettingsModel:
        """
        Создать или обновить настройки уведомлений для пользователя.

        Args:
            user_id: ID пользователя
            **kwargs: Поля для обновления (notify_deadline_24h, notify_overdue, etc.)

        Returns:
            Обновлённые настройки
        """
        settings = await self.get_by_user(user_id)

        if settings is None:
            settings = NotificationSettingsModel(user_id=user_id, **kwargs)
            self.session.add(settings)
        else:
            for key, value in kwargs.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)

        await self.session.flush()
        return settings

    async def enable_weekly_report(self, user_id: int) -> NotificationSettingsModel:
        """Включить еженедельную сводку для пользователя"""
        return await self.create_or_update(user_id, weekly_report_enabled=True)

    async def disable_weekly_report(self, user_id: int) -> NotificationSettingsModel:
        """Выключить еженедельную сводку для пользователя"""
        return await self.create_or_update(user_id, weekly_report_enabled=False)

    async def enable_group_notifications(self, user_id: int) -> NotificationSettingsModel:
        """Включить уведомления о назначении на группу для пользователя"""
        return await self.create_or_update(user_id, notify_group_assigned=True)

    async def disable_group_notifications(self, user_id: int) -> NotificationSettingsModel:
        """Выключить уведомления о назначении на группу для пользователя"""
        return await self.create_or_update(user_id, notify_group_assigned=False)

    async def enable_all_notifications(self, user_id: int) -> NotificationSettingsModel:
        """Включить все типы уведомлений для пользователя"""
        return await self.create_or_update(
            user_id,
            notify_deadline_24h=True,
            notify_deadline_1h=True,
            notify_overdue=True,
            weekly_report_enabled=True,
            notify_group_assigned=True,
            notify_task_assigned=True,
            notify_task_updated=True,
            notify_comment=True,
        )

    async def disable_all_notifications(self, user_id: int) -> NotificationSettingsModel:
        """Выключить все типы уведомлений для пользователя"""
        return await self.create_or_update(
            user_id,
            notify_deadline_24h=False,
            notify_deadline_1h=False,
            notify_overdue=False,
            weekly_report_enabled=False,
            notify_group_assigned=False,
            notify_task_assigned=False,
            notify_task_updated=False,
            notify_comment=False,
        )

    async def get_users_with_enabled_notification(self, notification_type: str):
        """
        Получить пользователей с включённым конкретным типом уведомлений.

        Args:
            notification_type: Тип уведомления ('deadline_24h', 'deadline_1h',
                            'overdue', 'weekly_report', 'group_assigned')

        Returns:
            Список пользователей с включённым уведомлением
        """
        # Маппинг типов уведомлений на поля в БД
        field_mapping = {
            "deadline_24h": NotificationSettingsModel.notify_deadline_24h,
            "deadline_1h": NotificationSettingsModel.notify_deadline_1h,
            "overdue": NotificationSettingsModel.notify_overdue,
            "weekly_report": NotificationSettingsModel.weekly_report_enabled,
            "group_assigned": NotificationSettingsModel.notify_group_assigned,
            "task_assigned": NotificationSettingsModel.notify_task_assigned,
            "task_updated": NotificationSettingsModel.notify_task_updated,
            "comment": NotificationSettingsModel.notify_comment,
        }

        field = field_mapping.get(notification_type)
        if not field:
            raise ValueError(f"Unknown notification type: {notification_type}")

        query = (
            select(UserModel)
            .join(
                NotificationSettingsModel,
                UserModel.id == NotificationSettingsModel.user_id,
            )
            .where(
                field.is_(True),
                UserModel.telegram_id.is_not(None),
                UserModel.is_active.is_(True),
            )
        )

        result = await self.session.execute(query)
        return result.scalars().all()


class StatsRepository(AbstractStatsRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_users_stats(self):
        result = await self.session.execute(
            select(
                func.count(UserModel.id).label("total_users"),
                func.sum(case((UserModel.is_active.is_(True), 1), else_=0)).label("active_users"),
                func.sum(case((UserModel.role == "admin", 1), else_=0)).label("admin_users"),
            )
        )
        row = result.one()
        return UsersStats(
            total_users=row.total_users,
            active_users=row.active_users or 0,
            admin_users=row.admin_users or 0,
        )

    async def get_tasks_stats(self):
        result = await self.session.execute(
            select(
                func.count(SpisokModel.id).label("total_tasks"),
                func.sum(case((SpisokModel.status == TaskStatus.done, 1), else_=0)).label("done_tasks"),
                func.sum(case((SpisokModel.status != TaskStatus.done, 1), else_=0)).label("pending_tasks"),
            )
        )
        return result.one()

    async def get_groups_count(self) -> int:
        result = await self.session.execute(select(func.count(GroupModel.id)))
        return result.scalar() or 0

    async def get_comments_count(self) -> int:
        result = await self.session.execute(select(func.count(CommentModel.id)))
        return result.scalar() or 0

    async def check_connection(self) -> None:
        await self.session.execute(select(1))
