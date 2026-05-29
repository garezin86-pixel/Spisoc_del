"""
Интеграционные тесты: уведомления, комментарии, группы, дедлайн, RBAC.
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
        patch(
            "src.services.comments_service.notify_comment_added", new_callable=AsyncMock
        ),
        patch(
            "src.services.group_service.notify_group_assigned", new_callable=AsyncMock
        ),
    ):
        yield


# ══════════════════════════════════════════════════════════════════
# Уведомления
# ══════════════════════════════════════════════════════════════════


class TestTaskNotifications:

    @pytest.mark.asyncio
    async def test_notify_called_on_task_create(self, auth_client):
        """notify_task_assigned вызывается при создании задачи с исполнителем."""
        client, user = auth_client

        # патчим путь откуда импортируется в task_service
        with patch(
            "src.services.task_service.notify_task_assigned", new_callable=AsyncMock
        ) as mock_notify:
            resp = await client.post(
                "/tasks/",
                json={
                    "title": "Задача с уведомлением",
                    "user_id": user.id,
                },
            )

        assert resp.status_code == 201
        mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_not_called_when_no_assignee(self, auth_client):
        client, _ = auth_client
        with patch(
            "src.services.task_service.notify_task_assigned", new_callable=AsyncMock
        ):
            resp = await client.post("/tasks/", json={"title": "Без исполнителя"})
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_notify_called_on_task_update(self, auth_client):
        client, _ = auth_client
        create_resp = await client.post("/tasks/", json={"title": "Задача"})
        task_id = create_resp.json()["id"]
        with patch(
            "src.services.notifications.notify_task_updated", new_callable=AsyncMock
        ):
            resp = await client.patch(
                f"/tasks/{task_id}", json={"title": "Новое название"}
            )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_notify_task_done_called(self, auth_client):
        client, _ = auth_client
        create_resp = await client.post("/tasks/", json={"title": "Выполнить"})
        task_id = create_resp.json()["id"]
        resp = await client.patch(f"/tasks/{task_id}", json={"is_done": True})
        assert resp.status_code == 200
        assert resp.json()["is_done"] is True


# ══════════════════════════════════════════════════════════════════
# Валидация дедлайна
# ══════════════════════════════════════════════════════════════════


class TestDeadlineValidation:

    @pytest.mark.asyncio
    async def test_deadline_in_past_returns_422(self, auth_client):
        client, _ = auth_client
        resp = await client.post(
            "/tasks/",
            json={
                "title": "Просроченная задача",
                "deadline": "2020-01-01T00:00:00",
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_deadline_in_future_is_accepted(self, auth_client):
        client, _ = auth_client
        resp = await client.post(
            "/tasks/",
            json={
                "title": "Будущая задача",
                "deadline": "2035-12-31T23:59:00",
            },
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_update_deadline_in_past_returns_422(self, auth_client):
        client, _ = auth_client
        create_resp = await client.post("/tasks/", json={"title": "Задача"})
        task_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/tasks/{task_id}", json={"deadline": "2019-06-15T10:00:00"}
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_deadline_null_is_accepted(self, auth_client):
        client, _ = auth_client
        create_resp = await client.post(
            "/tasks/",
            json={
                "title": "Задача с дедлайном",
                "deadline": "2035-01-01T12:00:00",
            },
        )
        task_id = create_resp.json()["id"]
        resp = await client.patch(f"/tasks/{task_id}", json={"deadline": None})
        assert resp.status_code == 200
        assert resp.json()["deadline"] is None


# ══════════════════════════════════════════════════════════════════
# Комментарии
# ══════════════════════════════════════════════════════════════════


class TestComments:

    @pytest.mark.asyncio
    async def test_author_can_add_comment(self, auth_client):
        client, user = auth_client
        create_resp = await client.post(
            "/tasks/", json={"title": "Задача для комментария"}
        )
        task_id = create_resp.json()["id"]

        with patch(
            "src.services.comments_service.notify_comment_added", new_callable=AsyncMock
        ):
            resp = await client.post(
                f"/comments/tasks/{task_id}/comment",
                json={"content": "Мой комментарий"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "Мой комментарий"
        assert data["task_id"] == task_id

    @pytest.mark.asyncio
    async def test_get_comments_for_task(self, auth_client):
        client, _ = auth_client

        # Создаём задачу
        create_resp = await client.post(
            "/tasks/", json={"title": "Задача с комментариями"}
        )
        assert create_resp.status_code == 201
        task_id = create_resp.json()["id"]

        with patch("src.services.comments_service.notify_comment_added"):
            # Создаём комментарии — правильный URL
            await client.post(
                f"/comments/tasks/{task_id}/comment",
                json={"content": "Первый комментарий"},
            )
            await client.post(
                f"/comments/tasks/{task_id}/comment",
                json={"content": "Второй комментарий"},
            )

        # Получаем комментарии — правильный URL!
        resp = await client.get(f"/comments/tasks/{task_id}/comments")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

        data = resp.json()
        assert "items" in data
        assert len(data["items"]) == 2, f"Expected 2 comments, got {len(data['items'])}"

    @pytest.mark.asyncio
    async def test_comment_xss_sanitized(self, auth_client):
        client, _ = auth_client
        create_resp = await client.post("/tasks/", json={"title": "XSS тест"})
        task_id = create_resp.json()["id"]

        with patch(
            "src.services.comments_service.notify_comment_added", new_callable=AsyncMock
        ):
            resp = await client.post(
                f"/comments/tasks/{task_id}/comment",
                json={"content": "<script>alert('xss')</script>"},
            )

        assert resp.status_code == 200
        content = resp.json()["content"]
        assert "<script>" not in content
        assert "&lt;script&gt;" in content

    @pytest.mark.asyncio
    async def test_empty_comment_returns_422(self, auth_client):
        client, _ = auth_client
        create_resp = await client.post("/tasks/", json={"title": "Задача"})
        task_id = create_resp.json()["id"]
        resp = await client.post(
            f"/comments/tasks/{task_id}/comment", json={"content": ""}
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_comment_on_nonexistent_task(self, auth_client):
        client, _ = auth_client
        with patch(
            "src.services.comments_service.notify_comment_added", new_callable=AsyncMock
        ):
            resp = await client.post(
                "/comments/tasks/999999/comment", json={"content": "Комментарий"}
            )
        assert resp.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_notify_comment_called(self, auth_client):
        client, _ = auth_client
        create_resp = await client.post("/tasks/", json={"title": "Задача"})
        task_id = create_resp.json()["id"]

        with patch(
            "src.services.comments_service.notify_comment_added",
            new_callable=AsyncMock,
        ) as mock_notify:
            await client.post(
                f"/comments/tasks/{task_id}/comment",
                json={"content": "Тест уведомления"},
            )

        mock_notify.assert_called_once()


# ══════════════════════════════════════════════════════════════════
# Группы
# ══════════════════════════════════════════════════════════════════


class TestGroups:

    @pytest.mark.asyncio
    async def test_admin_can_create_group(self, admin_client):
        client, _ = admin_client
        resp = await client.post("/groups/", json={"name": "Новая группа"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Новая группа"

    @pytest.mark.asyncio
    async def test_regular_user_cannot_create_group(self, auth_client):
        client, _ = auth_client
        resp = await client.post("/groups/", json={"name": "Запрещённая группа"})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_duplicate_group_returns_400(self, admin_client):
        client, _ = admin_client
        await client.post("/groups/", json={"name": "Группа-дубль"})
        resp = await client.post("/groups/", json={"name": "Группа-дубль"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_get_groups_list(self, auth_client, admin_client):
        admin_c, _ = admin_client
        await admin_c.post("/groups/", json={"name": "Список-группа-1"})
        client, _ = auth_client
        resp = await client.get("/groups/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_admin_can_add_user_to_group(self, admin_client, engine):
        client, _ = admin_client
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        async with async_session() as sess:
            user = await make_user(sess, username="group_member", password="pass123")
        group_resp = await client.post("/groups/", json={"name": "Тест-группа"})
        group_id = group_resp.json()["id"]
        resp = await client.post(f"/groups/{group_id}/users/{user.id}")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_can_remove_user_from_group(self, admin_client, engine):
        client, _ = admin_client
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        async with async_session() as sess:
            user = await make_user(
                sess, username="to_remove_from_group", password="pass123"
            )
        group_resp = await client.post("/groups/", json={"name": "Группа-удаление"})
        group_id = group_resp.json()["id"]
        await client.post(f"/groups/{group_id}/users/{user.id}")
        resp = await client.delete(f"/groups/{group_id}/users/{user.id}")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_regular_user_cannot_add_to_group(self, auth_client, engine):
        client, _ = auth_client
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        async with async_session() as sess:
            user = await make_user(sess, username="nogroup_user", password="pass123")
        resp = await client.post(f"/groups/1/users/{user.id}")
        assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════════


class TestRBAC:

    @pytest.mark.asyncio
    async def test_manager_can_edit_any_task(self, client, engine):
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )

        async with async_session() as sess:
            await make_user(sess, username="rbac_owner", password="pass123")
            await make_user(
                sess, username="rbac_manager", password="pass123", role="manager"
            )

        r1 = await client.post(
            "/auth/login", json={"username": "rbac_owner", "password": "pass123"}
        )
        token1 = r1.json()["access_token"]
        task_resp = await client.post(
            "/tasks/",
            json={"title": "Owner task"},
            headers={"Authorization": f"Bearer {token1}"},
        )
        task_id = task_resp.json()["id"]

        r2 = await client.post(
            "/auth/login", json={"username": "rbac_manager", "password": "pass123"}
        )
        token2 = r2.json()["access_token"]
        resp = await client.patch(
            f"/tasks/{task_id}",
            json={"title": "Manager edited"},
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Manager edited"

    @pytest.mark.asyncio
    async def test_manager_can_list_users(self, client, engine):
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        async with async_session() as sess:
            await make_user(
                sess, username="mgr_list", password="pass123", role="manager"
            )

        r = await client.post(
            "/auth/login", json={"username": "mgr_list", "password": "pass123"}
        )
        token = r.json()["access_token"]
        resp = await client.get("/users/", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_user_cannot_list_users(self, auth_client):
        client, _ = auth_client
        resp = await client.get("/users/")
        assert resp.status_code == 403

    # tests/test_integration_new.py
    @pytest.mark.asyncio
    async def test_get_groups_pagination(self, admin_client):
        client, _ = admin_client

        # Создаем 15 групп
        for i in range(15):
            await client.post("/groups/", json={"name": f"Group {i}"})

        # Тест первой страницы
        resp1 = await client.get("/groups/?page=1&size=10")
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert len(data1["items"]) == 10
        assert data1["total"] == 15
        assert data1["page"] == 1
        assert data1["size"] == 10
        assert data1["pages"] == 2

        # Тест второй страницы
        resp2 = await client.get("/groups/?page=2&size=10")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["items"]) == 5
        assert data2["page"] == 2

        # Тест несуществующей страницы
        resp3 = await client.get("/groups/?page=3&size=10")
        assert resp3.status_code == 200
        assert len(resp3.json()["items"]) == 0

    @pytest.mark.asyncio
    async def test_get_group_users_pagination(self, admin_client, engine):
        client, _ = admin_client

        # Создаем группу
        group_resp = await client.post("/groups/", json={"name": "Test Group"})
        group_id = group_resp.json()["id"]

        # Добавляем 15 пользователей
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        async with async_session() as sess:
            for i in range(15):
                user = await make_user(sess, username=f"user_{i}")
                await client.post(f"/groups/{group_id}/users/{user.id}")

        # Проверяем пагинацию
        resp = await client.get(f"/groups/{group_id}/users?page=1&size=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 10
        assert data["total"] == 15
        assert data["pages"] == 2

    @pytest.mark.asyncio
    async def test_pagination_validation(self, admin_client):
        client, _ = admin_client

        # page не может быть 0
        resp1 = await client.get("/groups/?page=0&size=10")
        assert resp1.status_code == 422

        # size не может быть больше 100
        resp2 = await client.get("/groups/?page=1&size=200")
        assert resp2.status_code == 422

        # size не может быть 0
        resp3 = await client.get("/groups/?page=1&size=0")
        assert resp3.status_code == 422
