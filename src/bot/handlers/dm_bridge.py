# src/bot/handlers/dm_bridge.py
"""Личные сообщения: Telegram → веб.

Веб → Telegram уже покрыт в src/services/chat_service.py (_mirror_dm_to_telegram) —
получателю ЛС с привязанным Telegram отправляется зеркало, и ID этого
Telegram-сообщения запоминается в Redis (см. dm_bridge_memory.py).

Этот файл ловит REPLY на такое зеркало в приватном чате с ботом: если
человек отвечает на сообщение "Личное сообщение от X", ответ находит
исходного отправителя X через Redis-память и публикуется как ЛС от текущего
пользователя обратно к X — с тем же зеркалированием в Telegram, так что
переписка полностью работает в обе стороны прямо из Telegram, без открытия
веб-приложения.

Специально фильтруем ТОЛЬКО по наличию reply_to_message — обычные (не reply)
сообщения в приватном чате продолжают обрабатываться voice_router (голосовой
ассистент/создание задач), это не трогаем.
"""

import structlog
from aiogram import F, Router
from aiogram.types import Message

from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.repositories.chat_repository import ChatRepository
from src.services.chat_service import ChatService
from src.services.dm_bridge_memory import get_reply_target

logger = structlog.get_logger()
router = Router()


@router.message(F.chat.type == "private", F.reply_to_message, F.text)
async def handle_dm_reply(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return

    reply = message.reply_to_message
    if reply is None:
        return

    target_user_id = await get_reply_target(
        message.chat.id,
        reply.message_id,
    )

    if target_user_id is None:
        return

    async with UnitOfWork(get_session_maker()) as uow:
        sender = await uow.users.get_by_telegram_id(message.from_user.id)
        if not sender or not sender.is_active:
            return

        recipient = await uow.users.get_user_id(target_user_id)
        if not recipient or not recipient.is_active:
            return

        service = ChatService(ChatRepository(uow.session))
        content = message.text
        if content is None:
            return
        try:
            await service.send_dm(sender, recipient, content)
        except Exception as e:  # noqa: BLE001
            await logger.aerror(
                "dm_bridge_reply_failed",
                error=str(e)[:500],
            )
