# src/ai/pending_store.py
"""Хранилище ожидающего решения пользователя («Создать сделку? да/нет», «Какой клиент?») для веба и API.

В Telegram это состояние держит FSM бота; у HTTP-клиента его нет, поэтому оно хранится на сервере: по одному на
пользователя (новая команда заменяет прежнее), 10 минут, в Redis. Если Redis недоступен — в памяти процесса (для
разработки и тестов; при нескольких воркерах без Redis подтверждение может прийти не на тот процесс — тогда
пользователь получит «устарело» и повторит команду).

`take` атомарный (GETDEL): двойной клик по «Да» или два запроса подряд выполнят действие один раз.
"""

import asyncio
import json
import secrets
import time

import structlog

from src.ai.types import Pending
from src.core.redis import redis

logger = structlog.get_logger()

TTL_SECONDS = 600
_REDIS_TIMEOUT = 1.0  # подвисший Redis не должен тормозить каждую команду ассистенту


def _key(workspace_id: int | None, user_id: int) -> str:
    return f"ai:pending:{workspace_id}:{user_id}"


class PendingStore:
    def __init__(self) -> None:
        self._memory: dict[str, tuple[float, str]] = {}

    # ── низкоуровневое: Redis, а при его недоступности — память процесса ─────
    async def _set(self, key: str, payload: str) -> None:
        try:
            await asyncio.wait_for(redis.set(key, payload, ex=TTL_SECONDS), _REDIS_TIMEOUT)
            self._memory.pop(key, None)
            return
        except Exception as exc:
            await logger.awarning("ai_pending_redis_unavailable", error=str(exc))
        self._memory[key] = (time.monotonic() + TTL_SECONDS, payload)

    async def _get(self, key: str, *, delete: bool) -> str | None:
        try:
            raw = await asyncio.wait_for(redis.getdel(key) if delete else redis.get(key), _REDIS_TIMEOUT)
            if raw is not None:
                return raw.decode() if isinstance(raw, bytes) else raw
        except Exception as exc:
            await logger.awarning("ai_pending_redis_unavailable", error=str(exc))
        item = self._memory.pop(key, None) if delete else self._memory.get(key)
        if item is None:
            return None
        expires, payload = item
        if expires < time.monotonic():
            self._memory.pop(key, None)
            return None
        return payload

    # ── API ──────────────────────────────────────────────────────────────────
    async def save(self, workspace_id: int | None, user_id: int, pending: Pending) -> str:
        """Запомнить ожидание (заменяет прежнее). Возвращает id — клиент присылает его вместе с ответом."""
        pending_id = secrets.token_urlsafe(12)
        await self._set(
            _key(workspace_id, user_id),
            json.dumps({"id": pending_id, "pending": pending.to_dict()}, ensure_ascii=False),
        )
        return pending_id

    async def peek(self, workspace_id: int | None, user_id: int, pending_id: str) -> Pending | None:
        """Посмотреть, не забирая (проверка варианта выбора до выполнения)."""
        raw = await self._get(_key(workspace_id, user_id), delete=False)
        return self._parse(raw, pending_id)

    async def take(self, workspace_id: int | None, user_id: int, pending_id: str) -> Pending | None:
        """Забрать ожидание атомарно. Чужой/устаревший id — None, а настоящее ожидание остаётся на месте."""
        key = _key(workspace_id, user_id)
        raw = await self._get(key, delete=True)
        pending = self._parse(raw, pending_id)
        if pending is None and raw is not None:
            await self._set(key, raw)  # пришёл старый id: актуальное ожидание не теряем
        return pending

    async def clear(self, workspace_id: int | None, user_id: int) -> bool:
        """Сбросить ожидание (новая команда). True — что-то было."""
        return await self._get(_key(workspace_id, user_id), delete=True) is not None

    @staticmethod
    def _parse(raw: str | None, pending_id: str) -> Pending | None:
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            if not secrets.compare_digest(str(data.get("id", "")), pending_id):
                return None
            return Pending.from_dict(data["pending"])
        except (ValueError, KeyError, TypeError):
            return None


pending_store = PendingStore()
