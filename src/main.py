import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from prometheus_fastapi_instrumentator import Instrumentator
from redis.asyncio import Redis
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.admin.setup import setup_admin
from src.core.config import (
    FRONTEND_URL,
    REDIS_DB,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
)
from src.core.limiter import limiter
from src.core.logging import setup_logging
from src.core.sentry import setup_sentry
from src.db import get_engine
from src.routers import api_router
from src.routers.health_router import router as health_router
from src.utils.cache_manager import cache_manager
from src.utils.reminders import (
    notify_overdue,
    remind_deadline_1h,
    remind_deadline_24h,
    send_weekly_report,
)

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
    from src.core.redis import set_redis

    set_redis(redis)
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
    scheduler.add_job(notify_overdue, IntervalTrigger(hours=1), id="overdue", replace_existing=True)
    scheduler.add_job(
        send_weekly_report,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="UTC"),
        id="weekly_report",
        replace_existing=True,
    )
    scheduler.start()
    await logger.ainfo("scheduler_started")

    yield

    # ── Shutdown ────────────────────────
    print("🔄 Shutting down application...")
    await logger.ainfo("app_shutdown")

    if scheduler:
        try:
            scheduler.shutdown()
            await asyncio.sleep(0.5)
            await logger.ainfo("scheduler_stopped")
        except Exception as e:
            await logger.aerror("scheduler_stop_error", error=str(e))

    try:
        await redis.close()
        await logger.ainfo("redis_closed")
    except Exception as e:
        await logger.aerror("redis_close_error", error=str(e))

    await logger.ainfo("app_shutdown_complete")


app = FastAPI(
    lifespan=lifespan,
    redirect_slashes=True,
    title="Spisok Del API",
    description="""
## Описание

REST API для системы управления задачами **Spisok Del**.

Поддерживает:
- управление задачами (создание, фильтрация, soft/hard delete, корзина)
- управление пользователями и группами
- комментарии к задачам
- Telegram-уведомления (назначение, дедлайны, комментарии, выполнение)
- JWT-авторизацию
- кэширование через Redis
- аудит-лог изменений

## Аутентификация

Все эндпоинты (кроме `/api/auth/login`) требуют заголовок:

```
Authorization: Bearer <access_token>
```

Токен получается через `POST /api/auth/login`.

## Роли

| Роль      | Возможности |
|-----------|-------------|
| `user`    | Свои задачи, просмотр групп, комментарии |
| `manager` | Управление участниками групп, просмотр всех пользователей |
| `admin`   | Полный доступ: создание пользователей/групп, удаление |

## Пагинация

Все списочные эндпоинты поддерживают параметры:
- `page` — номер страницы (по умолчанию 1)
- `size` — размер страницы (по умолчанию 20, максимум 100)

Ответ всегда содержит `total`, `page`, `size`, `pages`.
""",
    version="1.0.0",
    contact={
        "name": "Spisok Del",
    },
    openapi_tags=[
        {"name": "Auth", "description": "Авторизация и получение JWT-токена"},
        {
            "name": "Tasks",
            "description": "CRUD задач, фильтрация, корзина, восстановление",
        },
        {"name": "Users", "description": "Управление пользователями"},
        {"name": "Groups", "description": "Управление группами и их участниками"},
        {"name": "Comments", "description": "Комментарии к задачам"},
    ],
)


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


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Слишком много запросов. Попробуйте позже."},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    await logger.aerror(
        "unhandled_exception",
        error=str(exc),
        path=request.url.path,
        method=request.method,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Внутренняя ошибка сервера"},
    )


app.include_router(api_router)
app.include_router(health_router)
setup_admin(app, get_engine())


# ── Локальное хранилище вложений (временная замена R2, см. active_storage.py) ─
from src.core.config import ATTACHMENTS_STORAGE_PATH  # noqa: E402

ATTACHMENTS_DIR = Path(ATTACHMENTS_STORAGE_PATH).resolve()
ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/attachments-storage", StaticFiles(directory=ATTACHMENTS_DIR), name="attachments-storage")


# ── Статика фронтенда (только на проде) ──────────────────────────────────────
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="static")
