# src/services/dm_bridge_memory.py
"""Хранит связку "это сообщение бота в Telegram — зеркало ЛС от такого-то
пользователя Spisoc", чтобы ответ (reply) в Telegram можно было направить
обратно нужному человеку в приложении.

Ключ: dm_bridge:{telegram_chat_id}:{telegram_message_id}
Значение: id пользователя Spisoc, которому нужно доставить ответ
TTL: 7 дней — дольше реальная переписка вряд ли продолжится через reply
"""

from datetime import timedelta

import structlog

from src.core.redis import redis

logger = structlog.get_logger()

TTL = int(timedelta(days=7).total_seconds())


def _key(chat_id: int, message_id: int) -> str:
    return f"dm_bridge:{chat_id}:{message_id}"


async def remember_reply_target(chat_id: int, message_id: int, reply_to_user_id: int) -> None:
    try:
        await redis.setex(_key(chat_id, message_id), TTL, str(reply_to_user_id))
    except Exception as e:  # noqa: BLE001 — сбой Redis не должен ронять отправку сообщения
        await logger.awarning("dm_bridge_memory_write_failed", error=str(e))


async def get_reply_target(chat_id: int, message_id: int) -> int | None:
    try:
        raw = await redis.get(_key(chat_id, message_id))
        return int(raw) if raw else None
    except Exception as e:  # noqa: BLE001
        await logger.awarning("dm_bridge_memory_read_failed", error=str(e))
        return None
