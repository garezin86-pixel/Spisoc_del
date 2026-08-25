# tests/test_health_router.py
"""
Тесты для /health.

Регресс: раньше health-check проверял только Postgres. Реальный инцидент —
Redis был недоступен, логин/refresh/WebSocket не работали вообще, а
/health при этом отвечал 200 "ok", потому что Redis не проверялся. Мониторинг
аптайма ничего бы не заметил.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db import get_session
from src.routers.health_router import router as health_router

pytestmark = pytest.mark.asyncio


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(health_router)
    return test_app


@pytest.fixture
async def client(app, engine):
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_session():
        async with async_session() as sess:
            yield sess

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    async def test_all_healthy_returns_200(self, client, mock_redis_for_tests):
        mock_redis_for_tests.ping = AsyncMock(return_value=True)

        resp = await client.get("/health")

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "db": "ok", "redis": "ok"}

    async def test_redis_down_returns_503_not_200(self, client, mock_redis_for_tests):
        """Главный регресс-тест: раньше эта ситуация давала 200 'ok'."""
        mock_redis_for_tests.ping = AsyncMock(side_effect=ConnectionError("Redis недоступен"))

        resp = await client.get("/health")

        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["redis"] == "error"
        assert body["db"] == "ok"

    async def test_db_down_returns_503(self, client, mock_redis_for_tests, monkeypatch):
        mock_redis_for_tests.ping = AsyncMock(return_value=True)

        async def broken_execute(*args, **kwargs):
            raise ConnectionError("Postgres недоступен")

        monkeypatch.setattr(AsyncSession, "execute", broken_execute)

        resp = await client.get("/health")

        assert resp.status_code == 503
        body = resp.json()
        assert body["db"] == "error"
        assert body["redis"] == "ok"

    async def test_both_down_returns_503_with_both_errors(self, client, mock_redis_for_tests, monkeypatch):
        mock_redis_for_tests.ping = AsyncMock(side_effect=ConnectionError("Redis недоступен"))

        async def broken_execute(*args, **kwargs):
            raise ConnectionError("Postgres недоступен")

        monkeypatch.setattr(AsyncSession, "execute", broken_execute)

        resp = await client.get("/health")

        assert resp.status_code == 503
        assert resp.json() == {"status": "degraded", "db": "error", "redis": "error"}
