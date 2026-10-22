# src/ai/focus_store.py
"""«Рабочий клиент» диалога: о ком последний раз шла речь (30 минут, по одному на пользователя).

Нужен, чтобы «найди клиента Алекс Алексеев» → «создай задачу позвонить завтра в 10» относилось к нему и в Telegram,
и в вебе (в вебе есть ещё и открытая карточка — она важнее). Это только подсказка: перед записью пользователь всегда
видит в вопросе «да/нет», к какому клиенту относится действие. Хранится в Redis, без него — в памяти процесса.
"""

import asyncio
import time

import structlog

from src.core.redis import redis

logger = structlog.get_logger()

TTL_SECONDS = 1800
_REDIS_TIMEOUT = 1.0  # подвисший Redis не должен тормозить каждую команду ассистенту


def _key(workspace_id: int | None, user_id: int) -> str:
    return f"ai:focus:{workspace_id}:{user_id}"


class FocusStore:
    def __init__(self) -> None:
        self._memory: dict[str, tuple[float, int]] = {}

    async def remember(self, workspace_id: int | None, user_id: int, client_id: int) -> None:
        key = _key(workspace_id, user_id)
        try:
            await asyncio.wait_for(redis.set(key, str(client_id), ex=TTL_SECONDS), _REDIS_TIMEOUT)
            self._memory.pop(key, None)
            return
        except Exception as exc:
            await logger.adebug("ai_focus_redis_unavailable", error=str(exc))
        self._memory[key] = (time.monotonic() + TTL_SECONDS, client_id)

    async def recall(self, workspace_id: int | None, user_id: int) -> int | None:
        key = _key(workspace_id, user_id)
        try:
            raw = await asyncio.wait_for(redis.get(key), _REDIS_TIMEOUT)
            if raw is not None:
                return int(raw.decode() if isinstance(raw, bytes) else raw)
        except Exception as exc:
            await logger.adebug("ai_focus_redis_unavailable", error=str(exc))
        item = self._memory.get(key)
        if item is None or item[0] < time.monotonic():
            self._memory.pop(key, None)
            return None
        return item[1]

    async def forget(self, workspace_id: int | None, user_id: int) -> None:
        key = _key(workspace_id, user_id)
        self._memory.pop(key, None)
        try:
            await asyncio.wait_for(redis.delete(key), _REDIS_TIMEOUT)
        except Exception:
            pass


focus_store = FocusStore()
