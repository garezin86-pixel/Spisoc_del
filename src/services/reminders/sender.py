from typing import Any
import structlog

from src.bot.keyboards.notification_keyboard import task_action_keyboard
from src.core.metrics import notifications_sent, notifications_failed

logger = structlog.get_logger()


class NotificationSender:
    def __init__(self, bot: Any):
        self.bot = bot

    async def send_task(
        self,
        user,
        task,
        text: str,
        with_keyboard: bool = True,
        notification_type: str = "reminder",
    ):
        reply_markup = task_action_keyboard(task.id) if with_keyboard else None
        success, error = await self.send(user, text, reply_markup=reply_markup)
        if success:
            await logger.ainfo(
                "reminder_sent",
                task_id=task.id,
                type=notification_type,
            )
            notifications_sent.labels(type=notification_type).inc()  # 👈
        else:
            await logger.aerror(
                "reminder_failed",
                task_id=task.id,
                error=error,
            )
            notifications_failed.labels(type=notification_type).inc()  # 👈
        return success, error

    async def send(self, user, text: str, reply_markup=None):
        try:
            await self.bot.send_message(
                chat_id=user.telegram_id,
                text=text,
                reply_markup=reply_markup,
            )
            return True, None
        except Exception as exc:
            logger.error("Ошибка отправки уведомления", user_id=user.id, error=str(exc))
            return False, str(exc)[:500]
