from typing import Awaitable, cast

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.core.redis import get_redis
from src.db import SessionDep

router = APIRouter(tags=["System"])


@router.get("/health", include_in_schema=False)
async def health(session: SessionDep):
    # ВАЖНО: раньше проверялся только Postgres. Redis у нас не опциональный
    # кэш — без него не работает логин, refresh-токены и WebSocket (см.
    # auth_service.py: getdel/set на каждый login/refresh). "База ОК, а
    # приложение всё равно лежит" — ровно та ситуация, которую словили на
    # реальном инстансе: Redis был недоступен, а health-check при этом
    # ничего не проверял и не смог бы предупредить мониторинг.
    try:
        await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    try:
        # redis-py типизирует ping() как Union[Awaitable[bool], bool] — общая
        # сигнатура для sync/async/pipeline клиентов. На redis.asyncio.Redis
        # в рантайме это всегда корутина, но pyright не может сузить Union
        # статически и ругается "bool не awaitable". cast — не подавление
        # проверки вслепую, а явное указание реального типа в данном месте.
        await cast(Awaitable[bool], get_redis().ping())
        redis_status = "ok"
    except Exception:
        redis_status = "error"

    healthy = db_status == "ok" and redis_status == "ok"
    body = {
        "status": "ok" if healthy else "degraded",
        "db": db_status,
        "redis": redis_status,
    }
    # 503 при проблеме — не только 200 с "degraded" в теле. Большинство
    # аптайм-мониторов (UptimeRobot, Healthchecks.io, k8s/Docker healthcheck)
    # смотрят на HTTP-статус, а не парсят JSON — со старым кодом они бы
    # видели "всё ок" даже при полностью упавшем Redis.
    return JSONResponse(status_code=200 if healthy else 503, content=body)
