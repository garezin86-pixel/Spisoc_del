# src/bot/handlers/chat_bridge.py
"""Мост между общей Telegram-группой и общим каналом чата Spisoc.

Веб → Telegram: см. src/services/chat_service.py (_mirror_to_telegram).
Telegram → Веб: этот файл — ловим сообщения из привязанной группы
(CHAT_BRIDGE_GROUP_ID), находим отправителя по telegram_id и публикуем от
его имени в общий канал (ChatService.send_message с origin="telegram",
чтобы не зациклить пересылку обратно в Telegram).

Незарегистрированных участников группы молча игнорируем — не отвечаем в
группу, чтобы не спамить всех её участников (AuthMiddleware тоже сделан
мягким для этой группы, см. src/bot/middlewares/auth.py).
"""

import structlog
from aiogram import F, Router
from aiogram.types import Message

from src.core.config import CHAT_BRIDGE_GROUP_ID
from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.repositories.chat_repository import ChatRepository
from src.services.chat_service import ChatService

logger = structlog.get_logger()
router = Router()


@router.message(F.chat.id == CHAT_BRIDGE_GROUP_ID, F.text)
async def handle_bridge_group_message(message: Message):
    if not CHAT_BRIDGE_GROUP_ID:
        return

    if not message.from_user or message.from_user.is_bot:
        return

    content = message.text
    if content is None:
        return

    if content.startswith("/"):
        return

    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)

        if not user:
            await logger.ainfo(
                "chat_bridge_unregistered_sender",
                telegram_id=message.from_user.id,
            )
            return

        if not user.is_active:
            return

        service = ChatService(ChatRepository(uow.session))

        await service.send_message(
            user,
            content,
            group_id=None,
            origin="telegram",
        )
