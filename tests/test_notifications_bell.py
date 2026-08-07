import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.notification_log import NotificationLogModel
from src.models.task import SpisokModel, TaskStatus
from src.repositories.other_repositories import NotificationRepository
from tests.conftest import make_user


async def make_log(session, user_id, task_id=None, content="Текст <b>уведомления</b>", **kwargs):
    log = NotificationLogModel(
        user_id=user_id,
        notification_type=kwargs.pop("notification_type", "task_assigned"),
        task_id=task_id,
        content=content,
        **kwargs,
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)
    return log


class TestNotificationRepository:
    @pytest.mark.asyncio
    async def test_get_for_user_orders_newest_first_and_scopes_by_user(self, session):
        user = await make_user(session)
        other = await make_user(session)
        await make_log(session, other.id)
        first = await make_log(session, user.id, content="Первое")
        second = await make_log(session, user.id, content="Второе")

        repo = NotificationRepository(session)
        logs, total = await repo.get_for_user(user.id, offset=0, limit=20)

        assert total == 2
        assert [logs[0].id, logs[1].id] == [second.id, first.id]

    @pytest.mark.asyncio
    async def test_count_unread(self, session):
        user = await make_user(session)
        await make_log(session, user.id)
        await make_log(session, user.id, is_read=True)

        repo = NotificationRepository(session)
        assert await repo.count_unread(user.id) == 1

    @pytest.mark.asyncio
    async def test_mark_read_only_own_notification(self, session):
        user = await make_user(session)
        other = await make_user(session)
        log = await make_log(session, user.id)

        repo = NotificationRepository(session)
        assert await repo.mark_read(log.id, other.id) is False
        assert await repo.mark_read(log.id, user.id) is True
        assert await repo.count_unread(user.id) == 0

    @pytest.mark.asyncio
    async def test_mark_all_read(self, session):
        user = await make_user(session)
        await make_log(session, user.id)
        await make_log(session, user.id)

        repo = NotificationRepository(session)
        marked = await repo.mark_all_read(user.id)

        assert marked == 2
        assert await repo.count_unread(user.id) == 0


class TestNotificationsEndpointsViaRealApp:
    """Полный HTTP-путь — как test_personal_access_tokens.py::TestPatEndToEndViaRealApp."""

    @pytest.mark.asyncio
    async def test_list_strips_html_and_includes_task_title(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            author = await make_user(sess, username="bell_user1", password="pass123")
            task = SpisokModel(title="Позвонить клиенту", author_id=author.id, status=TaskStatus.todo)
            sess.add(task)
            await sess.commit()
            await sess.refresh(task)
            await make_log(sess, author.id, task_id=task.id, content="📌 <b>Вам назначена задача</b>")

        login = await client.post("/auth/login", json={"username": "bell_user1", "password": "pass123"})
        token = login.json()["access_token"]

        resp = await client.get("/api/notifications", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["content"] == "📌 Вам назначена задача"
        assert item["task_title"] == "Позвонить клиенту"
        assert item["is_read"] is False

    @pytest.mark.asyncio
    async def test_unread_count_and_mark_all_read(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            author = await make_user(sess, username="bell_user2", password="pass123")
            await make_log(sess, author.id)
            await make_log(sess, author.id)

        login = await client.post("/auth/login", json={"username": "bell_user2", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        before = await client.get("/api/notifications/unread-count", headers=headers)
        assert before.json()["count"] == 2

        mark = await client.post("/api/notifications/read-all", headers=headers)
        assert mark.json()["marked"] == 2

        after = await client.get("/api/notifications/unread-count", headers=headers)
        assert after.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_cannot_mark_other_users_notification_read(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            owner = await make_user(sess, username="bell_owner", password="pass123")
            await make_user(sess, username="bell_intruder", password="pass123")
            log = await make_log(sess, owner.id)

        login = await client.post("/auth/login", json={"username": "bell_intruder", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.post(f"/api/notifications/{log.id}/read", headers=headers)
        assert resp.status_code == 404
