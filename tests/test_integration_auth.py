"""
Интеграционные тесты: /auth эндпоинты.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from tests.conftest import make_user


class TestAuthLogin:

    @pytest.mark.asyncio
    async def test_login_success_returns_token(self, client, engine):
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        async with async_session() as sess:
            await make_user(sess, username="login_user", password="mypassword")

        resp = await client.post(
            "/auth/login", json={"username": "login_user", "password": "mypassword"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password_returns_401(self, client, engine):
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        async with async_session() as sess:
            await make_user(sess, username="user_wp", password="correct123")

        resp = await client.post(
            "/auth/login", json={"username": "user_wp", "password": "wrong123"}
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user_returns_401(self, client):
        resp = await client.post(
            "/auth/login", json={"username": "ghost_user", "password": "pass123"}
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_empty_body_returns_422(self, client):
        resp = await client.post("/auth/login", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_login_token_is_valid_jwt(self, client, engine):
        import jwt
        from src.core.config import SECRET_KEY, ALGORITHM

        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        async with async_session() as sess:
            await make_user(sess, username="jwt_user", password="jwtpass123")

        resp = await client.post(
            "/auth/login", json={"username": "jwt_user", "password": "jwtpass123"}
        )
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
        resp = await client.get(
            "/tasks/filter", headers={"Authorization": "Bearer invalid.token.here"}
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_inactive_user_still_gets_token(self, client, engine):
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        async with async_session() as sess:
            await make_user(
                sess, username="inactive_u", password="pass123", is_active=False
            )

        login_resp = await client.post(
            "/auth/login", json={"username": "inactive_u", "password": "pass123"}
        )
        assert login_resp.status_code == 200

        token = login_resp.json()["access_token"]
        protected_resp = await client.get(
            "/tasks/filter", headers={"Authorization": f"Bearer {token}"}
        )
        assert protected_resp.status_code == 401
