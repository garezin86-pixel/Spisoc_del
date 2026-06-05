import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded

from src.db import get_engine
from src.admin.setup import setup_admin
from src.routers import api_router
from src.core.limiter import limiter
from src.core.config import (
    REDIS_DB,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
    FRONTEND_URL,
)

from redis.asyncio import Redis
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from src.utils.cache_manager import cache_manager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from src.utils.reminders import (
    remind_deadline_24h,
    remind_deadline_1h,
    notify_overdue,
    send_weekly_report,
)

# import logging
import structlog
from src.core.sentry import setup_sentry
from src.core.logging import setup_logging
from prometheus_fastapi_instrumentator import Instrumentator

setup_sentry()
setup_logging()

logger = structlog.get_logger()

scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler

    print("🚀 Starting application...")
    await logger.ainfo("app_starting")

    # ── Redis Cache ─────────────────────
    redis = Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=False,
    )
    FastAPICache.init(RedisBackend(redis), prefix="fastapi-cache")
    cache_manager.redis = redis
    cache_manager.testing = False
    await logger.ainfo("redis_initialized")

    # ── AsyncIOScheduler ────────────────
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        remind_deadline_24h,
        IntervalTrigger(minutes=10),
        id="deadline_24h",
        replace_existing=True,
    )
    scheduler.add_job(
        remind_deadline_1h,
        IntervalTrigger(minutes=10),
        id="deadline_1h",
        replace_existing=True,
    )
    scheduler.add_job(
        notify_overdue, IntervalTrigger(hours=1), id="overdue", replace_existing=True
    )
    scheduler.add_job(
        send_weekly_report,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="UTC"),
        id="weekly_report",
        replace_existing=True,
    )
    scheduler.start()
    await logger.ainfo("scheduler_started")

    # ── Bot ─────────────────────────────
    yield

    # ── Shutdown ────────────────────────
    print("🔄 Shutting down application...")

    # 1. Сначала останавливаем бота
    await logger.ainfo("app_shutdown")

    # 2. Затем останавливаем scheduler
    if scheduler:
        try:
            # shutdown() без параметров
            scheduler.shutdown()
            # Даём время на завершение (await обязательно!)
            await asyncio.sleep(0.5)
            await logger.ainfo("scheduler_stopped")
        except Exception as e:
            await logger.aerror("scheduler_stop_error", error=str(e))

    # 3. Закрываем Redis
    try:
        await redis.close()
        await logger.ainfo("redis_closed")
    except Exception as e:
        await logger.aerror("redis_close_error", error=str(e))

    await logger.ainfo("app_shutdown_complete")


app = FastAPI(lifespan=lifespan, redirect_slashes=True)

# После создания app — автоматические метрики HTTP запросов
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://192.168.0.147:5173",
        "http://192.168.0.147:5174",
        *([FRONTEND_URL] if FRONTEND_URL else []),
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate limiting ─────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


# Красивый ответ при превышении лимита
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Слишком много запросов. Попробуйте позже."},
    )


app.include_router(api_router)
setup_admin(app, get_engine())

# ── Статика фронтенда (только на проде) ──────────────────────────────────────
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="static")
