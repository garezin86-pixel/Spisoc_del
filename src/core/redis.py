from redis.asyncio import Redis

from src.core.config import REDIS_DB, REDIS_HOST, REDIS_PASSWORD, REDIS_PORT

redis = Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD,
    decode_responses=True,
)

# --- добавить ниже ---

_redis_instance: Redis | None = None


def set_redis(r: Redis) -> None:
    global _redis_instance
    _redis_instance = r


def get_redis() -> Redis:
    if _redis_instance is None:
        raise RuntimeError("Redis не инициализирован")
    return _redis_instance
