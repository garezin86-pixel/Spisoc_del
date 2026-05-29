# src/utils/cache_manager.py
import os
import asyncio
import logging
import structlog
from typing import Optional
from redis.asyncio import Redis

logger = logging.getLogger(__name__)
event_logger = structlog.get_logger()


class CacheManager:
    """Менеджер для работы с кэшем"""

    def __init__(self, redis_client: Optional[Redis] = None):
        self.redis = redis_client
        self.testing = os.getenv("TESTING") == "True"

    async def invalidate_pattern(self, pattern: str):
        """Инвалидировать все ключи по паттерну"""
        if self.testing or not self.redis:
            return

        try:
            # Проверяем соединение с таймаутом
            try:
                # Оборачиваем await в wait_for
                import inspect

                ping = self.redis.ping()
                if inspect.isawaitable(ping):
                    await asyncio.wait_for(ping, timeout=1.0)

            except (ConnectionError, asyncio.TimeoutError):
                await event_logger.aerror(
                    "cache_error",
                    error="redis_ping_failed",
                    pattern=pattern,
                )
                logger.warning(f"Redis ping timeout for pattern {pattern}")
                return

            # Инвалидируем кэш
            invalidated_count = 0
            async for key in self.redis.scan_iter(match=f"*{pattern}*"):
                await self.redis.delete(key)
                invalidated_count += 1
            await event_logger.ainfo(
                "cache_invalidated",
                pattern=pattern,
                count=invalidated_count,
            )

        except asyncio.TimeoutError:
            await event_logger.aerror(
                "cache_error",
                error="redis_timeout",
                pattern=pattern,
            )
            logger.warning(f"Redis timeout during cache invalidation for {pattern}")
        except ConnectionError:
            await event_logger.aerror(
                "cache_error",
                error="redis_connection_error",
                pattern=pattern,
            )
            logger.warning(
                f"Redis connection error during cache invalidation for {pattern}"
            )
        except Exception as e:
            await event_logger.aerror("cache_error", error=str(e), pattern=pattern)
            logger.error(f"Unexpected error during cache invalidation: {e}")

    async def invalidate_users(self):
        """Инвалидировать кэш пользователей"""
        await self.invalidate_pattern("users")

    async def invalidate_groups(self):
        """Инвалидировать кэш групп"""
        await self.invalidate_pattern("groups")

    async def invalidate_tasks(self):
        """Инвалидировать кэш задач"""
        await self.invalidate_pattern("tasks")


# Создаем глобальный экземпляр (опционально)
cache_manager = CacheManager()
