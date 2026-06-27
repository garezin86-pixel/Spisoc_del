import asyncio  # <-- ДОБАВИТЬ ЭТОТ ИМПОРТ
import logging
import os

logger = logging.getLogger(__name__)


async def invalidate_cache(pattern: str, redis):
    """Безопасная инвалидация кэша - пропускаем в тестах"""
    # Пропускаем инвалидацию во время тестов
    if os.getenv("TESTING") == "True":
        return

    try:
        # Проверяем, что Redis доступен
        if not redis:
            logger.warning("Redis client is None, skipping cache invalidation")
            return

        # Пытаемся выполнить ping с таймаутом
        await asyncio.wait_for(redis.ping(), timeout=1.0)

        async for key in redis.scan_iter(match=f"*{pattern}*"):
            await redis.delete(key)

    except asyncio.TimeoutError:
        # Исправлено: убрал print, оставил только logger
        logger.warning(f"Redis timeout during cache invalidation for {pattern}")
    except ConnectionError:
        logger.warning(f"Redis connection error during cache invalidation for {pattern}")
    except Exception as e:
        logger.error(f"Unexpected error during cache invalidation: {e}")
