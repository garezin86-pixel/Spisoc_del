from typing import Any

import structlog
from aiogram.types import BufferedInputFile

from src.bot.keyboards.notification_keyboard import task_action_keyboard
from src.core.metrics import notifications_failed, notifications_sent

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

    async def send_voice(self, user, text: str, notification_type: str = "voice_reminder"):
        """
        Синтезирует текст в речь (Groq PlayAI TTS) и отправляет как голосовое
        сообщение в Telegram. Ошибка TTS/отправки НЕ пробрасывается наружу —
        голосовое уведомление всегда идёт "бонусом" поверх уже отправленного
        текстового, а не вместо него; если TTS недоступен (сбой Groq API,
        превышена квота и т.п.), пользователь всё равно получил текст.
        """
        try:
            from src.services.voice_ai import synthesize_speech

            audio_bytes = await synthesize_speech(text)
            voice_file = BufferedInputFile(audio_bytes, filename="reminder.ogg")
            await self.bot.send_voice(chat_id=user.telegram_id, voice=voice_file)
            notifications_sent.labels(type=notification_type).inc()
            return True, None
        except Exception as exc:
            # str(exc) может быть пустым (напр. голый asyncio.TimeoutError()
            # или обрыв сокета без сообщения) — тогда без типа исключения и
            # traceback непонятно, что вообще упало. logger.exception сама
            # подхватывает sys.exc_info() и допишет traceback в лог.
            error_detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            logger.exception(
                "Ошибка синтеза/отправки голосового уведомления",
                user_id=user.id,
                error_type=type(exc).__name__,
            )
            notifications_failed.labels(type=notification_type).inc()
            return False, error_detail[:500]
