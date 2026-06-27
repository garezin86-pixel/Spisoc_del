import structlog
from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork

logger = structlog.get_logger()


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, Message):
            return await handler(event, data)

        # Пропускаем /start и заявку
        if event.text and (event.text.startswith("/start") or event.text == "📝 Подать заявку"):
            return await handler(event, data)

        # Пропускаем состояния регистрации
        fsm_context = data.get("state")
        if not isinstance(fsm_context, FSMContext):
            return await handler(event, data)
        current_state = await fsm_context.get_state()
        if current_state and "Registration" in current_state:
            return await handler(event, data)

        async with UnitOfWork(get_session_maker()) as uow:
            if not event.from_user:
                return
            user = await uow.users.get_by_telegram_id(event.from_user.id)

        if not user:
            await logger.awarning(
                "access_denied",
                telegram_id=event.from_user.id if event.from_user else None,
                reason="not_registered",
            )
            await event.answer("❌ У вас нет доступа. Обратитесь к администратору.")
            return

        if not user.is_active:
            await logger.awarning(
                "access_denied",
                telegram_id=event.from_user.id if event.from_user else None,
                reason="inactive",
            )
            await event.answer("⛔ Ваш аккаунт заблокирован. Обратитесь к администратору.")
            return

        return await handler(event, data)
