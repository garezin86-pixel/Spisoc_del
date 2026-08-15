import structlog
from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.core.config import CHAT_BRIDGE_GROUP_ID
from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork

logger = structlog.get_logger()


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, Message):
            return await handler(event, data)

        # Сообщения из привязанной Telegram-группы (мост с общим чатом Spisoc,
        # см. src/bot/handlers/chat_bridge.py) обрабатываются отдельным
        # роутером с собственной, более мягкой логикой: незарегистрированных
        # участников группы молча игнорируем, а не отвечаем "нет доступа"
        # на каждое сообщение — иначе бот будет спамить всю группу.
        if CHAT_BRIDGE_GROUP_ID and event.chat.id == CHAT_BRIDGE_GROUP_ID:
            return await handler(event, data)

        # Пропускаем /start, заявку и /chatid (нужен ДО того, как группа
        # привязана и её участники зарегистрированы — иначе узнать chat_id
        # новой группы для настройки моста будет нечем)
        if event.text and (
            event.text.startswith("/start") or event.text == "📝 Подать заявку" or event.text.startswith("/chatid")
        ):
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
