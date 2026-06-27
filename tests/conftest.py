"""
Фикстуры для тестов.
"""

import sys
import os
import uuid
import pytest
import asyncio
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.utils.cache_manager import cache_manager
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.db import Base
from src.models import UserModel, SpisokModel, GroupModel, CommentModel  # noqa: F401
from src.core.security import hash_password

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest_asyncio.fixture
async def engine():
    _engine = create_async_engine(TEST_DB_URL, echo=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield _engine
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()


@pytest_asyncio.fixture
async def session(engine):
    async_session = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    async with async_session() as sess:
        yield sess


def unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def make_user(
    session: AsyncSession,
    username: str = None,
    password: str = "password123",  # ← минимум 6 символов
    role: str = "user",
    is_active: bool = True,
) -> UserModel:
    if username is None:
        username = unique("user")
    user = UserModel(
        username=username,
        password_hash=hash_password(password),
        role=role,
        is_active=is_active,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def make_task(
    session: AsyncSession,
    title: str = "Test task",
    author_id: int = None,
    user_id: int = None,
    is_done: bool = False,
) -> SpisokModel:
    task = SpisokModel(
        title=title, is_done=is_done, author_id=author_id, user_id=user_id
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


def _disable_rate_limits():
    try:
        import slowapi

        slowapi.Limiter.limit = lambda self, *a, **kw: lambda f: f
    except ImportError:
        pass


_disable_rate_limits()


@pytest_asyncio.fixture
async def client(engine):
    from fastapi import FastAPI
    from src.routers import (
        api_router,
        auth_router,
        users_router,
        tasks_router,
        group_router,
        comments_router,
    )
    from src.db import get_session

    app = FastAPI()
    app.include_router(api_router)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(tasks_router)
    app.include_router(group_router)
    app.include_router(comments_router)

    async_session = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async def override_get_session():
        async with async_session() as sess:
            yield sess

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=True,
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client(engine, client):
    async_session = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    username = unique("auth_user")
    password = "pass123456"  # ← минимум 6 символов

    async with async_session() as sess:
        user = await make_user(sess, username=username, password=password)

    resp = await client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    client.headers.update({"Authorization": f"Bearer {resp.json()['access_token']}"})
    return client, user


@pytest_asyncio.fixture
async def admin_client(engine, client):
    async_session = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    username = unique("admin_user")
    password = "adminpass123"  # ← минимум 6 символов

    async with async_session() as sess:
        admin = await make_user(
            sess, username=username, password=password, role="admin"
        )

    resp = await client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, f"Admin login failed: {resp.text}"
    client.headers.update({"Authorization": f"Bearer {resp.json()['access_token']}"})
    return client, admin


# Устанавливаем тестовый режим
os.environ["TESTING"] = "True"


@pytest.fixture(autouse=True)
def reset_cache_manager():
    """Сбрасывает cache_manager перед каждым тестом"""
    cache_manager.testing = True
    cache_manager.redis = None
    yield


@pytest.fixture(autouse=True)
def mock_fastapi_cache_for_list_endpoints():
    """Специально мокает FastAPICache для эндпоинтов GET /users/ и /groups/"""

    # Создаем мок для FastAPICache
    mock_cache = MagicMock()
    mock_cache.get_prefix.return_value = "test-prefix"
    mock_cache.get_backend.return_value = MagicMock()

    # Патчим FastAPICache напрямую
    with patch("fastapi_cache.FastAPICache", mock_cache):
        with patch("fastapi_cache.decorator.FastAPICache", mock_cache):
            # Также мокаем сам декоратор cache
            with patch("fastapi_cache.decorator.cache") as cache_decorator:
                # Декоратор должен возвращать исходную функцию
                cache_decorator.side_effect = lambda *args, **kwargs: lambda func: func
                yield


@pytest_asyncio.fixture(scope="session")
async def redis_client():
    """Redis клиент для интеграционных тестов (опционально)"""
    if os.getenv("USE_REAL_REDIS") == "True":
        from redis import asyncio as aioredis

        redis = await aioredis.from_url("redis://localhost:6379", decode_responses=True)
        yield redis
        await redis.close()
    else:
        yield None


@pytest.fixture
def mock_get_bot():
    """Мок для get_bot, возвращающий мок-бота"""
    with patch("src.services.notifications.get_bot") as mock_get_bot_func:
        # Создаём мок-бота
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()
        mock_get_bot_func.return_value = mock_bot
        yield mock_bot


# conftest.py — добавить в конец
@pytest_asyncio.fixture
async def notification_session(engine):
    """Отдельная сессия для сервисов уведомлений (без транзакции)"""
    async_session = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    async with async_session() as sess:
        yield sess


# добавить новую фикстуру
@pytest.fixture(autouse=True)
def mock_redis_for_tests():
    """Мокает Redis для всех тестов — set_redis вызывается автоматически."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock(return_value=1)

    from src.core.redis import set_redis

    set_redis(mock_redis)
    yield mock_redis
    set_redis(None)  # сбрасываем после каждого теста
