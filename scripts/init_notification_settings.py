# scripts/init_notification_settings.py
import asyncio
from sqlalchemy import select
from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.models.user import UserModel as User
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init_notification_settings():
    """Создаёт настройки уведомлений для всех существующих пользователей"""
    session_maker = get_session_maker()

    async with UnitOfWork(session_maker) as uow:
        # Получаем всех пользователей
        result = await uow.session.execute(select(User))
        users = result.scalars().all()

        created_count = 0
        for user in users:
            # Проверяем, есть ли уже настройки
            settings = await uow.notification_settings.get_by_user(user.id)
            if not settings:
                # Создаём настройки по умолчанию
                await uow.notification_settings.create_or_update(
                    user_id=user.id,
                    notify_deadline_24h=True,
                    notify_deadline_1h=True,
                    notify_overdue=True,
                    weekly_report_enabled=True,
                    notify_task_assigned=True,
                    notify_task_updated=True,
                    notify_comment=True,
                )
                created_count += 1
                logger.info(f"Created settings for user {user.id} ({user.telegram_id})")

        await uow.commit()
        logger.info(
            f"Done! Created settings for {created_count} out of {len(users)} users"
        )


if __name__ == "__main__":
    asyncio.run(init_notification_settings())
