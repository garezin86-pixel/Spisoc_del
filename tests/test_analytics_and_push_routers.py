# tests/test_analytics_and_push_routers.py
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.user import UserRole
from tests.conftest import make_user


async def make_manager_in_db(engine, username, password="pass123"):
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as sess:
        user = await make_user(sess, username=username, password=password)
        user.role = UserRole.manager
        await sess.commit()
    return username, password


async def make_plain_user_in_db(engine, username, password="pass123"):
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as sess:
        await make_user(sess, username=username, password=password)
    return username, password


async def login(client, username, password):
    resp = await client.post("/auth/login", json={"username": username, "password": password})
    return resp.json()["access_token"]


class TestAnalyticsRouter:
    @pytest.mark.asyncio
    async def test_manager_can_access_dashboard(self, client, engine):
        username, password = await make_manager_in_db(engine, f"mgr_{uuid.uuid4().hex[:6]}")
        token = await login(client, username, password)

        resp = await client.get("/api/analytics/dashboard", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        assert "executor_completion" in resp.json()
        assert "project_overdue" in resp.json()

    @pytest.mark.asyncio
    async def test_regular_user_forbidden(self, client, engine):
        username, password = await make_plain_user_in_db(engine, f"usr_{uuid.uuid4().hex[:6]}")
        token = await login(client, username, password)

        resp = await client.get("/api/analytics/dashboard", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_unauthenticated_rejected(self, client):
        resp = await client.get("/api/analytics/dashboard")
        assert resp.status_code in (401, 403)


class TestPushRouter:
    @pytest.mark.asyncio
    async def test_vapid_public_key_accessible_without_auth(self, client):
        resp = await client.get("/api/push/vapid-public-key")
        assert resp.status_code == 200
        assert "public_key" in resp.json()

    @pytest.mark.asyncio
    async def test_subscribe_and_list(self, client, engine):
        username, password = await make_plain_user_in_db(engine, f"usr_{uuid.uuid4().hex[:6]}")
        token = await login(client, username, password)

        subscribe_resp = await client.post(
            "/api/push/subscribe",
            json={
                "endpoint": f"https://fcm.googleapis.com/fcm/send/{uuid.uuid4().hex}",
                "keys": {"p256dh": "fake-key", "auth": "fake-auth"},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert subscribe_resp.status_code == 201

        list_resp = await client.get("/api/push/subscriptions", headers={"Authorization": f"Bearer {token}"})
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1

    @pytest.mark.asyncio
    async def test_unsubscribe(self, client, engine):
        username, password = await make_plain_user_in_db(engine, f"usr_{uuid.uuid4().hex[:6]}")
        token = await login(client, username, password)
        endpoint = f"https://fcm.googleapis.com/fcm/send/{uuid.uuid4().hex}"

        await client.post(
            "/api/push/subscribe",
            json={"endpoint": endpoint, "keys": {"p256dh": "k", "auth": "a"}},
            headers={"Authorization": f"Bearer {token}"},
        )

        unsub_resp = await client.post(
            "/api/push/unsubscribe",
            json={"endpoint": endpoint},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert unsub_resp.status_code == 200

        list_resp = await client.get("/api/push/subscriptions", headers={"Authorization": f"Bearer {token}"})
        assert list_resp.json() == []

    @pytest.mark.asyncio
    async def test_subscribe_requires_auth(self, client):
        resp = await client.post(
            "/api/push/subscribe",
            json={"endpoint": "https://x.example.com/1", "keys": {"p256dh": "k", "auth": "a"}},
        )
        assert resp.status_code in (401, 403)
