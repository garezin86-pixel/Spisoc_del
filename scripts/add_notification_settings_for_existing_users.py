# scripts/add_notification_settings_for_existing_users.py
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging

from sqlalchemy import select

from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.models.notification_settings import (
    NotificationSettingsModel as NotificationSettings,
)
from src.models.user import UserModel as User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def add_settings_for_existing_users():
    """Добавляет настройки уведомлений для всех пользователей, у которых их нет"""
    session_maker = get_session_maker()

    async with UnitOfWork(session_maker) as uow:
        # Получаем всех пользователей
        result = await uow.session.execute(select(User))
        users = result.scalars().all()

        added = 0
        for user in users:
            # Проверяем, есть ли настройки
            result = await uow.session.execute(
                select(NotificationSettings).where(NotificationSettings.user_id == user.id)
            )
            settings = result.scalar_one_or_none()

            if not settings:
                # Создаём настройки по умолчанию
                new_settings = NotificationSettings(
                    user_id=user.id,
                    notify_deadline_24h=True,
                    notify_deadline_1h=True,
                    notify_overdue=True,
                    weekly_report_enabled=True,
                    notify_task_assigned=True,
                    notify_task_updated=True,
                    notify_comment=True,
                )
                uow.session.add(new_settings)
                added += 1
                logger.info(f"Added settings for user {user.id} ({user.telegram_id})")

        await uow.commit()
        logger.info(f"Done! Added settings for {added} out of {len(users)} users")


if __name__ == "__main__":
    asyncio.run(add_settings_for_existing_users())
