"""
Интеграционные тесты: /auth эндпоинты.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import make_user


class TestAuthLogin:
    @pytest.mark.asyncio
    async def test_login_success_returns_token(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="login_user", password="mypassword")

        resp = await client.post("/auth/login", json={"username": "login_user", "password": "mypassword"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password_returns_401(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="user_wp", password="correct123")

        resp = await client.post("/auth/login", json={"username": "user_wp", "password": "wrong123"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user_returns_401(self, client):
        resp = await client.post("/auth/login", json={"username": "ghost_user", "password": "pass123"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_empty_body_returns_422(self, client):
        resp = await client.post("/auth/login", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_login_token_is_valid_jwt(self, client, engine):
        import jwt

        from src.core.config import ALGORITHM, SECRET_KEY

        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="jwt_user", password="jwtpass123")

        resp = await client.post("/auth/login", json={"username": "jwt_user", "password": "jwtpass123"})
        token = resp.json()["access_token"]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert "sub" in payload
        assert "exp" in payload

    @pytest.mark.asyncio
    async def test_protected_route_without_token_returns_403(self, client):
        resp = await client.get("/tasks/filter")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_protected_route_with_invalid_token_returns_401(self, client):
        resp = await client.get("/tasks/filter", headers={"Authorization": "Bearer invalid.token.here"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_inactive_user_is_rejected_without_tokens(self, client, engine):
        """Раньше заблокированный получал токены на логине и только потом 401 на первом запросе."""
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="inactive_u", password="pass123", is_active=False)

        resp = await client.post("/auth/login", json={"username": "inactive_u", "password": "pass123"})
        assert resp.status_code == 401
        assert "Account is disabled" in resp.text
        assert "access_token" not in resp.text and "refresh_token" not in resp.text

    @pytest.mark.asyncio
    async def test_login_inactive_user_wrong_password_does_not_reveal_block(self, client, engine):
        """Причина раскрывается только после верного пароля — иначе по ответу можно узнать, кто заблокирован."""
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="inactive_u2", password="pass123", is_active=False)

        resp = await client.post("/auth/login", json={"username": "inactive_u2", "password": "WRONG-pass"})
        assert resp.status_code == 401
        assert "Account is disabled" not in resp.text and "Invalid credentials" in resp.text

    @pytest.mark.asyncio
    async def test_login_inactive_user_gets_no_refresh_token_in_redis(self, client, engine):
        """Refresh-токен записывается в Redis при выдаче токенов; заблокированному он не должен создаваться.
        (Redis в тестах — AsyncMock, поэтому проверяем сам вызов записи, а не содержимое ключей.)"""
        from src.core.redis import get_redis

        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="inactive_u3", password="pass123", is_active=False)
        redis = get_redis()
        redis.set.reset_mock()
        redis.setex.reset_mock()

        await client.post("/auth/login", json={"username": "inactive_u3", "password": "pass123"})

        assert redis.set.await_count == 0 and redis.setex.await_count == 0

    @pytest.mark.asyncio
    async def test_login_active_user_still_gets_refresh_token_in_redis(self, client, engine):
        """Парный к предыдущему: защита от пустого теста — у активного запись в Redis происходит."""
        from src.core.redis import get_redis

        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="active_u3", password="pass123")
        redis = get_redis()
        redis.set.reset_mock()
        redis.setex.reset_mock()

        resp = await client.post("/auth/login", json={"username": "active_u3", "password": "pass123"})

        assert resp.status_code == 200
        assert redis.set.await_count + redis.setex.await_count >= 1
