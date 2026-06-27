"""
Интеграционные тесты: /users эндпоинты.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import make_user


class TestUsersCreate:
    @pytest.mark.asyncio
    async def test_admin_can_create_user(self, admin_client):
        client, admin = admin_client
        resp = await client.post(
            "/users/",
            json={"username": "brand_new_user", "password": "pass1234", "role": "user"},
        )
        assert resp.status_code == 201
        assert resp.json()["username"] == "brand_new_user"

    @pytest.mark.asyncio
    async def test_regular_user_cannot_create_user(self, auth_client):
        client, _ = auth_client
        resp = await client.post("/users/", json={"username": "another_user", "password": "pass1234"})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_duplicate_user_returns_400(self, admin_client):
        client, _ = admin_client
        await client.post("/users/", json={"username": "dup_user", "password": "pass1234"})
        resp = await client.post("/users/", json={"username": "dup_user", "password": "pass1234"})
        assert resp.status_code == 400  # ← пароль теперь корректный

    @pytest.mark.asyncio
    async def test_create_user_without_auth_returns_401_or_403(self, client):
        resp = await client.post("/users/", json={"username": "noauth", "password": "pass123"})
        assert resp.status_code in (401, 403)


class TestUsersGet:
    @pytest.mark.asyncio
    async def test_user_can_get_self(self, auth_client):
        client, user = auth_client
        resp = await client.get(f"/users/{user.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == user.id

    @pytest.mark.asyncio
    async def test_user_cannot_get_other_user(self, auth_client, engine):
        client, _ = auth_client
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            other = await make_user(sess, username="other_get_user", password="pass123")
        resp = await client.get(f"/users/{other.id}")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_get_any_user(self, admin_client, engine):
        client, _ = admin_client
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            user = await make_user(sess, username="visible_to_admin", password="pass123")
        resp = await client.get(f"/users/{user.id}")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_nonexistent_user_returns_4xx(self, auth_client):
        client, _ = auth_client
        resp = await client.get("/users/999999")
        assert resp.status_code in (401, 404)

    @pytest.mark.asyncio
    async def test_admin_can_list_users(self, admin_client):
        client, _ = admin_client
        resp = await client.get("/users/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_regular_user_cannot_list_users(self, auth_client):
        client, _ = auth_client
        resp = await client.get("/users/")
        assert resp.status_code == 403


class TestUsersUpdate:
    @pytest.mark.asyncio
    async def test_user_can_update_own_username(self, auth_client):
        client, user = auth_client
        resp = await client.patch(f"/users/{user.id}", json={"username": "updated_name_xyz"})
        assert resp.status_code == 200
        assert resp.json()["username"] == "updated_name_xyz"

    @pytest.mark.asyncio
    async def test_user_cannot_update_other_user(self, auth_client, engine):
        client, _ = auth_client
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            other = await make_user(sess, username="other_upd_user", password="pass123")
        resp = await client.patch(f"/users/{other.id}", json={"username": "hacked"})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_user_can_update_own_password(self, auth_client):
        client, user = auth_client
        resp = await client.patch(f"/users/{user.id}", json={"password": "newpass456"})
        assert resp.status_code == 200
        login_resp = await client.post("/auth/login", json={"username": user.username, "password": "newpass456"})
        assert login_resp.status_code == 200


class TestUsersDelete:
    @pytest.mark.asyncio
    async def test_admin_can_delete_user(self, admin_client, engine):
        client, _ = admin_client
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            user = await make_user(sess, username="to_be_deleted", password="pass123")
        resp = await client.delete(f"/users/{user.id}")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_regular_user_cannot_delete(self, auth_client, engine):
        client, _ = auth_client
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            other = await make_user(sess, username="nodelete_user", password="pass123")
        resp = await client.delete(f"/users/{other.id}")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_nonexistent_user_returns_4xx(self, admin_client):
        client, _ = admin_client
        resp = await client.delete("/users/999999")
        assert resp.status_code in (401, 404)
