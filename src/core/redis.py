from redis.asyncio import Redis

from src.core.config import REDIS_DB, REDIS_HOST, REDIS_PASSWORD, REDIS_PORT

redis = Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD,
    decode_responses=True,
)
