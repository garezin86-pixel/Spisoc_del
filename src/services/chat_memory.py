"""
src/services/chat_memory.py

Хранит историю диалога пользователя в Redis.
Используется для передачи контекста в Groq LLM.

Ключ: chat_memory:{user_id}
Значение: JSON-список последних MAX_MESSAGES сообщений
TTL: 24 часа (сбрасывается при каждом обновлении)
"""

import json
import logging
from datetime import timedelta

from src.core.redis import redis

logger = logging.getLogger(__name__)

MAX_MESSAGES = 10
TTL = int(timedelta(hours=24).total_seconds())


def _key(user_id: int) -> str:
    return f"chat_memory:{user_id}"


async def get_history(user_id: int) -> list[dict]:
    """Возвращает историю диалога (список {role, content})."""
    try:
        raw = await redis.get(_key(user_id))
        if not raw:
            return []
        return json.loads(raw)
    except Exception as e:
        logger.warning("chat_memory get error: %s", e)
        return []


async def add_message(user_id: int, role: str, content: str) -> None:
    """Добавляет сообщение в историю, обрезает до MAX_MESSAGES."""
    try:
        history = await get_history(user_id)
        history.append({"role": role, "content": content})
        # Оставляем только последние MAX_MESSAGES
        if len(history) > MAX_MESSAGES:
            history = history[-MAX_MESSAGES:]
        await redis.setex(_key(user_id), TTL, json.dumps(history, ensure_ascii=False))
    except Exception as e:
        logger.warning("chat_memory add error: %s", e)


async def clear_history(user_id: int) -> None:
    """Очищает историю диалога."""
    try:
        await redis.delete(_key(user_id))
    except Exception as e:
        logger.warning("chat_memory clear error: %s", e)
