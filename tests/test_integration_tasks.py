"""
Интеграционные тесты: /tasks эндпоинты.
"""

import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from tests.conftest import make_user


@pytest.fixture(autouse=True)
def mock_background_notifications():
    with (
        patch("src.services.task_service.notify_task_assigned", new_callable=AsyncMock),
        patch("src.routers.tasks_router.notify_task_assigned", new_callable=AsyncMock),
    ):
        yield


class TestTasksCreate:

    @pytest.mark.asyncio
    async def test_create_task_success(self, auth_client):
        client, user = auth_client
        resp = await client.post("/tasks/", json={"title": "Написать тесты"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Написать тесты"
        assert data["is_done"] is False

    @pytest.mark.asyncio
    async def test_create_task_without_auth_returns_403(self, client):
        resp = await client.post("/tasks/", json={"title": "No auth task"})
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_create_task_empty_title_returns_422(self, auth_client):
        client, _ = auth_client
        resp = await client.post("/tasks/", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_task_user_and_group_returns_422(self, auth_client, engine):
        """user_id + group_id одновременно — Pydantic возвращает 422."""
        client, user = auth_client
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        async with async_session() as sess:
            from src.models.group import GroupModel

            group = GroupModel(name="test_group_conflict")
            sess.add(group)
            await sess.commit()
            await sess.refresh(group)

        resp = await client.post(
            "/tasks/",
            json={
                "title": "Conflict",
                "user_id": user.id,
                "group_id": group.id,
            },
        )
        assert resp.status_code == 422  # ← Pydantic отклоняет на уровне схемы

    @pytest.mark.asyncio
    async def test_create_task_with_deadline(self, auth_client):
        client, _ = auth_client
        resp = await client.post(
            "/tasks/",
            json={
                "title": "Task with deadline",
                "deadline": "2030-12-31T23:59:00",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["deadline"] is not None


class TestTasksGet:

    @pytest.mark.asyncio
    async def test_get_task_by_id_author(self, auth_client):
        client, user = auth_client
        create_resp = await client.post("/tasks/", json={"title": "My task to get"})
        task_id = create_resp.json()["id"]
        resp = await client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == task_id

    @pytest.mark.asyncio
    async def test_get_task_not_found_returns_404(self, auth_client):
        client, _ = auth_client
        resp = await client.get("/tasks/999999")
        assert resp.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_filter_tasks_returns_list(self, auth_client):
        client, _ = auth_client
        await client.post("/tasks/", json={"title": "Filter task 1"})
        await client.post("/tasks/", json={"title": "Filter task 2"})
        resp = await client.get("/tasks/filter")
        data = resp.json()
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_filter_tasks_by_done(self, auth_client):
        client, _ = auth_client
        await client.post("/tasks/", json={"title": "Done task", "is_done": True})
        await client.post("/tasks/", json={"title": "Pending task", "is_done": False})

        resp = await client.get("/tasks/filter?is_done=true")
        assert resp.status_code == 200
        data = resp.json()
        assert all(t["is_done"] is True for t in data["items"])  # ← data["items"]

    @pytest.mark.asyncio
    async def test_filter_tasks_limit(self, auth_client):
        client, _ = auth_client
        for i in range(5):
            await client.post("/tasks/", json={"title": f"Limit task {i}"})

        resp = await client.get("/tasks/filter?limit=2")
        assert resp.status_code == 200

        data = resp.json()
        assert isinstance(data, dict) and "items" in data
        assert (
            len(data["items"]) <= 2
        ), f"Expected <=2 items, got {len(data['items'])}"  # ← data["items"]

    @pytest.mark.asyncio
    async def test_filter_my_tasks(self, auth_client):
        client, _ = auth_client
        resp = await client.get("/tasks/filter?filter_user_group=user")
        assert resp.status_code == 200


class TestTasksUpdate:

    @pytest.mark.asyncio
    async def test_author_can_update_task(self, auth_client):
        client, _ = auth_client
        create_resp = await client.post("/tasks/", json={"title": "Original"})
        task_id = create_resp.json()["id"]
        resp = await client.patch(f"/tasks/{task_id}", json={"title": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated"

    @pytest.mark.asyncio
    async def test_mark_task_as_done(self, auth_client):
        client, _ = auth_client
        create_resp = await client.post("/tasks/", json={"title": "Task to complete"})
        task_id = create_resp.json()["id"]
        resp = await client.patch(f"/tasks/{task_id}", json={"is_done": True})
        assert resp.status_code == 200
        assert resp.json()["is_done"] is True

    @pytest.mark.asyncio
    async def test_other_user_cannot_update_task(self, client, engine):
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )

        async with async_session() as sess:
            await make_user(sess, username="task_owner", password="pass123")

        resp1 = await client.post(
            "/auth/login", json={"username": "task_owner", "password": "pass123"}
        )
        token1 = resp1.json()["access_token"]

        create_resp = await client.post(
            "/tasks/",
            json={"title": "Owner task"},
            headers={"Authorization": f"Bearer {token1}"},
        )
        task_id = create_resp.json()["id"]

        async with async_session() as sess:
            await make_user(sess, username="task_intruder", password="pass123")

        resp2 = await client.post(
            "/auth/login", json={"username": "task_intruder", "password": "pass123"}
        )
        token2 = resp2.json()["access_token"]

        resp = await client.patch(
            f"/tasks/{task_id}",
            json={"title": "Hacked"},
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_update_nonexistent_task_returns_404(self, auth_client):
        client, _ = auth_client
        resp = await client.patch("/tasks/999999", json={"title": "Ghost"})
        assert resp.status_code == 404


class TestTasksDelete:

    @pytest.mark.asyncio
    async def test_author_can_delete_own_task(self, auth_client):
        client, _ = auth_client
        create_resp = await client.post("/tasks/", json={"title": "To delete"})
        task_id = create_resp.json()["id"]
        resp = await client.delete(f"/tasks/{task_id}")
        assert resp.status_code == 200
        get_resp = await client.get(f"/tasks/{task_id}")
        assert get_resp.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_task_returns_404(self, auth_client):
        client, _ = auth_client
        resp = await client.delete("/tasks/999999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_other_user_cannot_delete_task(self, client, engine):
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )

        async with async_session() as sess:
            await make_user(sess, username="del_owner", password="pass123")

        resp1 = await client.post(
            "/auth/login", json={"username": "del_owner", "password": "pass123"}
        )
        token1 = resp1.json()["access_token"]

        create_resp = await client.post(
            "/tasks/",
            json={"title": "Protected task"},
            headers={"Authorization": f"Bearer {token1}"},
        )
        task_id = create_resp.json()["id"]

        async with async_session() as sess:
            await make_user(sess, username="del_attacker", password="pass123")

        resp2 = await client.post(
            "/auth/login", json={"username": "del_attacker", "password": "pass123"}
        )
        token2 = resp2.json()["access_token"]

        resp = await client.delete(
            f"/tasks/{task_id}", headers={"Authorization": f"Bearer {token2}"}
        )
        assert resp.status_code in (401, 403)


class TestTasksReassign:

    @pytest.mark.asyncio
    async def test_author_can_reassign_to_user(self, auth_client, engine):
        client, user = auth_client
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        async with async_session() as sess:
            target = await make_user(
                sess, username="reassign_target", password="pass123"
            )

        create_resp = await client.post("/tasks/", json={"title": "To reassign"})
        task_id = create_resp.json()["id"]
        resp = await client.patch(f"/tasks/{task_id}/reassign?user_id={target.id}")
        assert resp.status_code == 200
        assert resp.json()["user_id"] == target.id

    @pytest.mark.asyncio
    async def test_reassign_both_user_and_group_returns_400(self, auth_client, engine):
        client, user = auth_client
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        async with async_session() as sess:
            target = await make_user(sess, username="reassign_both", password="pass123")
            from src.models.group import GroupModel

            group = GroupModel(name="reassign_group")
            sess.add(group)
            await sess.commit()
            await sess.refresh(group)

        create_resp = await client.post("/tasks/", json={"title": "Conflict reassign"})
        task_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/tasks/{task_id}/reassign?user_id={target.id}&group_id={group.id}"
        )
        assert resp.status_code == 400
