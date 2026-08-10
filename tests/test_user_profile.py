import io

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.task import SpisokModel, TaskStatus
from src.repositories.audit_repository import AuditRepository
from src.services.activity_service import ActivityService
from tests.conftest import make_user


async def make_task(session, author, **kwargs):
    task = SpisokModel(title=kwargs.pop("title", "Задача"), author_id=author.id, **kwargs)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


class TestUserProfileViaRealApp:
    @pytest.mark.asyncio
    async def test_update_own_position(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            user = await make_user(sess, username="profile_user1", password="pass123")

        login = await client.post("/auth/login", json={"username": "profile_user1", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.patch(f"/users/{user.id}", json={"position": "Backend-разработчик"}, headers=headers)

        assert resp.status_code == 200
        assert resp.json()["position"] == "Backend-разработчик"

    @pytest.mark.asyncio
    async def test_cannot_edit_other_users_position(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="profile_user2", password="pass123")
            other = await make_user(sess, username="profile_user3", password="pass123")

        login = await client.post("/auth/login", json={"username": "profile_user2", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.patch(f"/users/{other.id}", json={"position": "Hacked"}, headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_avatar_upload_rejects_non_image(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="avatar_user1", password="pass123")

        login = await client.post("/auth/login", json={"username": "avatar_user1", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.post(
            "/users/me/avatar",
            headers=headers,
            files={"file": ("doc.txt", io.BytesIO(b"not an image"), "text/plain")},
        )

        assert resp.status_code == 415

    @pytest.mark.asyncio
    async def test_avatar_upload_rejects_oversized_file(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="avatar_user2", password="pass123")

        login = await client.post("/auth/login", json={"username": "avatar_user2", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        big_payload = b"0" * (6 * 1024 * 1024)  # 6 МБ > лимита 5 МБ
        resp = await client.post(
            "/users/me/avatar",
            headers=headers,
            files={"file": ("big.png", io.BytesIO(big_payload), "image/png")},
        )

        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_avatar_upload_and_serve_roundtrip(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            user = await make_user(sess, username="avatar_user3", password="pass123")

        login = await client.post("/auth/login", json={"username": "avatar_user3", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        upload = await client.post(
            "/users/me/avatar",
            headers=headers,
            files={"file": ("me.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 100), "image/png")},
        )
        assert upload.status_code == 200

        # Отдача аватара НЕ требует авторизации (см. users_router.get_user_avatar)
        avatar_resp = await client.get(f"/users/{user.id}/avatar")
        assert avatar_resp.status_code == 200

    @pytest.mark.asyncio
    async def test_avatar_delete_then_404(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            user = await make_user(sess, username="avatar_user4", password="pass123")

        login = await client.post("/auth/login", json={"username": "avatar_user4", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        await client.post(
            "/users/me/avatar",
            headers=headers,
            files={"file": ("me.png", io.BytesIO(b"fake-png-bytes"), "image/png")},
        )
        delete_resp = await client.delete("/users/me/avatar", headers=headers)
        assert delete_resp.status_code == 204

        avatar_resp = await client.get(f"/users/{user.id}/avatar")
        assert avatar_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_user_without_avatar_returns_404(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            user = await make_user(sess, username="avatar_user5", password="pass123")

        resp = await client.get(f"/users/{user.id}/avatar")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_any_authenticated_user_can_view_others_stats(self, client, engine):
        """Видимость статистики теперь общая, как у задач/ленты (см. users_router)."""
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="viewer_user", password="pass123")
            target = await make_user(sess, username="target_user", password="pass123")

        login = await client.post("/auth/login", json={"username": "viewer_user", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.get(f"/users/{target.id}/stats", headers=headers)

        assert resp.status_code == 200


class TestTargetUserIdTaskFilter:
    @pytest.mark.asyncio
    async def test_target_user_id_shows_their_assigned_tasks(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            viewer = await make_user(sess, username="filter_viewer", password="pass123")
            target = await make_user(sess, username="filter_target", password="pass123")
            await make_task(sess, viewer, title="Задача вьюера", user_id=viewer.id, status=TaskStatus.todo)
            await make_task(sess, viewer, title="Задача таргета", user_id=target.id, status=TaskStatus.todo)

        login = await client.post("/auth/login", json={"username": "filter_viewer", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.get(
            "/tasks/filter",
            params={"filter_user_group": "user", "target_user_id": target.id},
            headers=headers,
        )

        assert resp.status_code == 200
        titles = [t["title"] for t in resp.json()["items"]]
        assert titles == ["Задача таргета"]

    @pytest.mark.asyncio
    async def test_without_target_user_id_defaults_to_self(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            viewer = await make_user(sess, username="filter_viewer2", password="pass123")
            other = await make_user(sess, username="filter_other2", password="pass123")
            await make_task(sess, viewer, title="Моя задача", user_id=viewer.id, status=TaskStatus.todo)
            await make_task(sess, viewer, title="Чужая задача", user_id=other.id, status=TaskStatus.todo)

        login = await client.post("/auth/login", json={"username": "filter_viewer2", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.get("/tasks/filter", params={"filter_user_group": "user"}, headers=headers)

        titles = [t["title"] for t in resp.json()["items"]]
        assert titles == ["Моя задача"]


class TestUserScopedActivityFeed:
    @pytest.mark.asyncio
    async def test_user_id_filters_feed_to_their_events_only(self, session):
        author_a = await make_user(session)
        author_b = await make_user(session)
        session.info["audit_user_id"] = author_a.id
        await make_task(session, author_a, title="Задача A", status=TaskStatus.todo)

        session.info["audit_user_id"] = author_b.id
        await make_task(session, author_b, title="Задача B", status=TaskStatus.todo)

        service = ActivityService(AuditRepository(session), session)
        feed, total = await service.get_feed(offset=0, limit=50, user_id=author_a.id)

        assert total == 1
        assert feed[0]["task_title"] == "Задача A"
        assert feed[0]["username"] == author_a.username

    @pytest.mark.asyncio
    async def test_no_user_id_returns_everyone(self, session):
        author_a = await make_user(session)
        author_b = await make_user(session)
        session.info["audit_user_id"] = author_a.id
        await make_task(session, author_a, title="Задача A", status=TaskStatus.todo)
        session.info["audit_user_id"] = author_b.id
        await make_task(session, author_b, title="Задача B", status=TaskStatus.todo)

        service = ActivityService(AuditRepository(session), session)
        _feed, total = await service.get_feed(offset=0, limit=50)

        assert total == 2
