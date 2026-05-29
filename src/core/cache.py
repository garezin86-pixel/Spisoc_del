from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from redis.asyncio import Redis

from src.core.config import REDIS_DB, REDIS_HOST, REDIS_PASSWORD, REDIS_PORT


@asynccontextmanager
async def lifespan(app: FastAPI):

    redis = Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=False,
    )

    FastAPICache.init(RedisBackend(redis), prefix="fastapi-cache")

    yield

    await redis.close()
