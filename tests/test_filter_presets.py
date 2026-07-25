# tests/test_filter_presets.py
"""
Тесты FilterPresetRepository (уровень репозитория, реальная БД через session)
и GET/POST/DELETE /tasks/presets (уровень HTTP, через auth_client).
"""

import pytest

from src.models.filter_preset import FilterPresetModel
from src.models.task import TaskStatus
from src.repositories.filter_preset_repository import FilterPresetRepository
from tests.conftest import make_user


class TestFilterPresetRepository:
    @pytest.mark.asyncio
    async def test_create_and_get_by_id(self, session):
        user = await make_user(session)
        repo = FilterPresetRepository(session)
        preset = FilterPresetModel(user_id=user.id, name="Мои горящие", status=TaskStatus.in_progress)

        created = await repo.create(preset)

        assert created.id is not None
        fetched = await repo.get_by_id(created.id)
        assert fetched is not None
        assert fetched.name == "Мои горящие"

    @pytest.mark.asyncio
    async def test_get_all_for_user_scoped_correctly(self, session):
        user1 = await make_user(session)
        user2 = await make_user(session)
        repo = FilterPresetRepository(session)
        await repo.create(FilterPresetModel(user_id=user1.id, name="Пресет 1"))
        await repo.create(FilterPresetModel(user_id=user1.id, name="Пресет 2"))
        await repo.create(FilterPresetModel(user_id=user2.id, name="Чужой пресет"))

        presets = await repo.get_all_for_user(user1.id)

        names = {p.name for p in presets}
        assert names == {"Пресет 1", "Пресет 2"}

    @pytest.mark.asyncio
    async def test_delete_removes_preset(self, session):
        user = await make_user(session)
        repo = FilterPresetRepository(session)
        preset = await repo.create(FilterPresetModel(user_id=user.id, name="Временный"))

        await repo.delete(preset)

        assert await repo.get_by_id(preset.id) is None

    @pytest.mark.asyncio
    async def test_get_by_id_nonexistent_returns_none(self, session):
        repo = FilterPresetRepository(session)
        assert await repo.get_by_id(999999) is None

    @pytest.mark.asyncio
    async def test_get_all_for_user_empty_when_no_presets(self, session):
        user = await make_user(session)
        repo = FilterPresetRepository(session)
        assert await repo.get_all_for_user(user.id) == []

    @pytest.mark.asyncio
    async def test_get_all_ordered_by_created_at(self, session):
        user = await make_user(session)
        repo = FilterPresetRepository(session)
        first = await repo.create(FilterPresetModel(user_id=user.id, name="Первый"))
        second = await repo.create(FilterPresetModel(user_id=user.id, name="Второй"))

        presets = await repo.get_all_for_user(user.id)

        assert [p.id for p in presets] == [first.id, second.id]


class TestFilterPresetEndpoints:
    @pytest.mark.asyncio
    async def test_create_preset_via_endpoint(self, auth_client):
        client, _ = auth_client
        resp = await client.post(
            "/tasks/presets",
            json={"name": "Мои горящие", "status": "in_progress", "priority": "high"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Мои горящие"
        assert data["status"] == "in_progress"
        assert data["priority"] == "high"
        assert "id" in data and "created_at" in data

    @pytest.mark.asyncio
    async def test_create_preset_without_optional_fields(self, auth_client):
        client, _ = auth_client
        resp = await client.post("/tasks/presets", json={"name": "Просто именной"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] is None
        assert data["priority"] is None

    @pytest.mark.asyncio
    async def test_create_preset_empty_name_returns_422(self, auth_client):
        client, _ = auth_client
        resp = await client.post("/tasks/presets", json={"name": ""})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_duplicate_name_returns_400_not_500(self, auth_client):
        client, _ = auth_client
        resp1 = await client.post("/tasks/presets", json={"name": "Дубликат"})
        assert resp1.status_code == 201

        resp2 = await client.post("/tasks/presets", json={"name": "Дубликат"})
        assert resp2.status_code == 400

    @pytest.mark.asyncio
    async def test_same_name_allowed_for_different_users(self, client, engine):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="preset_user1", password="pass123")
            await make_user(sess, username="preset_user2", password="pass123")

        resp1 = await client.post("/auth/login", json={"username": "preset_user1", "password": "pass123"})
        token1 = resp1.json()["access_token"]
        resp2 = await client.post("/auth/login", json={"username": "preset_user2", "password": "pass123"})
        token2 = resp2.json()["access_token"]

        r1 = await client.post(
            "/tasks/presets", json={"name": "Общее имя"}, headers={"Authorization": f"Bearer {token1}"}
        )
        r2 = await client.post(
            "/tasks/presets", json={"name": "Общее имя"}, headers={"Authorization": f"Bearer {token2}"}
        )
        assert r1.status_code == 201
        assert r2.status_code == 201

    @pytest.mark.asyncio
    async def test_list_presets_scoped_to_current_user(self, client, engine):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="list_user1", password="pass123")
            await make_user(sess, username="list_user2", password="pass123")

        resp1 = await client.post("/auth/login", json={"username": "list_user1", "password": "pass123"})
        token1 = resp1.json()["access_token"]
        resp2 = await client.post("/auth/login", json={"username": "list_user2", "password": "pass123"})
        token2 = resp2.json()["access_token"]

        await client.post(
            "/tasks/presets", json={"name": "Пресет юзера 1"}, headers={"Authorization": f"Bearer {token1}"}
        )
        await client.post(
            "/tasks/presets", json={"name": "Пресет юзера 2"}, headers={"Authorization": f"Bearer {token2}"}
        )

        resp = await client.get("/tasks/presets", headers={"Authorization": f"Bearer {token1}"})
        names = {p["name"] for p in resp.json()}
        assert names == {"Пресет юзера 1"}

    @pytest.mark.asyncio
    async def test_delete_own_preset(self, auth_client):
        client, _ = auth_client
        create_resp = await client.post("/tasks/presets", json={"name": "На удаление"})
        preset_id = create_resp.json()["id"]

        resp = await client.delete(f"/tasks/presets/{preset_id}")
        assert resp.status_code == 200

        list_resp = await client.get("/tasks/presets")
        assert all(p["id"] != preset_id for p in list_resp.json())

    @pytest.mark.asyncio
    async def test_delete_nonexistent_preset_returns_404(self, auth_client):
        client, _ = auth_client
        resp = await client.delete("/tasks/presets/999999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cannot_delete_other_users_preset(self, client, engine):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="preset_owner", password="pass123")
            await make_user(sess, username="preset_intruder", password="pass123")

        resp1 = await client.post("/auth/login", json={"username": "preset_owner", "password": "pass123"})
        token1 = resp1.json()["access_token"]
        create_resp = await client.post(
            "/tasks/presets", json={"name": "Приватный"}, headers={"Authorization": f"Bearer {token1}"}
        )
        preset_id = create_resp.json()["id"]

        resp2 = await client.post("/auth/login", json={"username": "preset_intruder", "password": "pass123"})
        token2 = resp2.json()["access_token"]

        resp = await client.delete(f"/tasks/presets/{preset_id}", headers={"Authorization": f"Bearer {token2}"})
        assert resp.status_code == 404  # не 403 — специально не палим факт существования чужого id

    @pytest.mark.asyncio
    async def test_presets_without_auth_return_401_or_403(self, client):
        resp = await client.get("/tasks/presets")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_presets_endpoint_not_shadowed_by_task_id_route(self, auth_client):
        """Регрессия на порядок роутов: GET /tasks/presets не должен пытаться
        распарситься как GET /{task_id} (task_id="presets" -> 422)."""
        client, _ = auth_client
        resp = await client.get("/tasks/presets")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
