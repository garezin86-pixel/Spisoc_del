# src/utils/dashboard_cache.py
"""Кэш дашборда в Redis: ключ на (компания, пользователь, пояс, пороги), TTL 45 секунд.

Кэш best-effort: недоступный или медленный Redis не ломает дашборд — это просто промах. Сброс (шаг 3 плана) —
`invalidate_user` / `invalidate_workspace` при изменениях задач, клиентов, сделок и событий.
Клиент Redis берётся из общего `cache_manager` в момент вызова (как и у остальных кэшей проекта); в тестах
(`cache_manager.testing`) кэш выключен.
"""

import asyncio

import structlog

from src.utils.cache_manager import cache_manager

logger = structlog.get_logger()

DASHBOARD_TTL_SECONDS = 45
_REDIS_TIMEOUT = 1.0  # дашборд не должен ждать медленный Redis дольше секунды


def dashboard_key(workspace_id: int, user_id: int, tz: str, stale_days: int, events_days: int) -> str:
    return f"dashboard:{workspace_id}:{user_id}:{tz}:{stale_days}:{events_days}"


class DashboardCache:
    @staticmethod
    def _redis():
        if cache_manager.testing or not cache_manager.redis:
            return None
        return cache_manager.redis

    async def get(self, key: str) -> str | None:
        redis = self._redis()
        if redis is None:
            return None
        try:
            raw = await asyncio.wait_for(redis.get(key), _REDIS_TIMEOUT)
        except Exception as exc:  # Redis — не критичный путь
            await logger.awarning("dashboard_cache_get_failed", error=str(exc))
            return None
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else raw

    async def set(self, key: str, payload: str) -> None:
        redis = self._redis()
        if redis is None:
            return
        try:
            await asyncio.wait_for(redis.set(key, payload, ex=DASHBOARD_TTL_SECONDS), _REDIS_TIMEOUT)
        except Exception as exc:
            await logger.awarning("dashboard_cache_set_failed", error=str(exc))

    async def _delete_matching(self, pattern: str) -> int:
        redis = self._redis()
        if redis is None:
            return 0
        deleted = 0
        try:
            async with asyncio.timeout(_REDIS_TIMEOUT * 3):
                async for key in redis.scan_iter(match=pattern, count=200):
                    await redis.delete(key)
                    deleted += 1
        except Exception as exc:
            await logger.awarning("dashboard_cache_invalidate_failed", pattern=pattern, error=str(exc))
        return deleted

    async def invalidate_user(self, workspace_id: int, user_id: int) -> int:
        """Сбросить все варианты дашборда пользователя (любой пояс и пороги)."""
        return await self._delete_matching(f"dashboard:{workspace_id}:{user_id}:*")

    async def invalidate_workspace(self, workspace_id: int) -> int:
        """Сбросить дашборды всех пользователей компании (изменение, затрагивающее нескольких)."""
        return await self._delete_matching(f"dashboard:{workspace_id}:*")


dashboard_cache = DashboardCache()
