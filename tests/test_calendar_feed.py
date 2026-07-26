# tests/test_calendar_feed.py
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.enums import TaskStatus
from src.models.task import SpisokModel
from src.repositories.calendar_repository import CalendarRepository
from src.services.calendar_service import CalendarService
from src.utils.ics import build_ics_feed
from tests.conftest import make_user

pytestmark = pytest.mark.asyncio


def build_service(session) -> CalendarService:
    return CalendarService(CalendarRepository(session))


async def _task(
    session, *, author=None, user=None, deadline=None, status=TaskStatus.todo, title="Задача", deleted_at=None
):
    task = SpisokModel(
        title=title,
        author_id=author.id if author else None,
        user_id=user.id if user else None,
        status=status,
        deadline=deadline,
        deleted_at=deleted_at,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


class TestBuildIcsFeed:
    async def test_empty_task_list_produces_valid_empty_calendar(self):
        ics = build_ics_feed([])
        assert ics.startswith("BEGIN:VCALENDAR")
        assert ics.strip().endswith("END:VCALENDAR")
        assert "BEGIN:VEVENT" not in ics

    async def test_task_without_deadline_is_skipped(self, session):
        author = await make_user(session)
        task = await _task(session, author=author, deadline=None)
        ics = build_ics_feed([task])
        assert "BEGIN:VEVENT" not in ics

    async def test_task_with_deadline_produces_vevent(self, session):
        author = await make_user(session)
        deadline = datetime.now(timezone.utc) + timedelta(days=1)
        task = await _task(session, author=author, deadline=deadline, title="Сдать отчёт")
        ics = build_ics_feed([task])
        assert "BEGIN:VEVENT" in ics
        assert f"UID:task-{task.id}@" in ics
        assert "SUMMARY:Сдать отчёт" in ics
        assert deadline.strftime("%Y%m%dT%H%M") in ics

    async def test_uses_crlf_line_endings(self, session):
        author = await make_user(session)
        task = await _task(session, author=author, deadline=datetime.now(timezone.utc))
        ics = build_ics_feed([task])
        assert "\r\n" in ics

    async def test_done_task_is_transparent(self, session):
        author = await make_user(session)
        task = await _task(session, author=author, deadline=datetime.now(timezone.utc), status=TaskStatus.done)
        ics = build_ics_feed([task])
        assert "TRANSP:TRANSPARENT" in ics

    async def test_pending_task_is_opaque(self, session):
        author = await make_user(session)
        task = await _task(session, author=author, deadline=datetime.now(timezone.utc), status=TaskStatus.todo)
        ics = build_ics_feed([task])
        assert "TRANSP:OPAQUE" in ics

    async def test_special_characters_are_escaped(self, session):
        author = await make_user(session)
        task = await _task(
            session, author=author, deadline=datetime.now(timezone.utc), title="Купить: молоко, хлеб; сыр"
        )
        ics = build_ics_feed([task])
        assert "SUMMARY:Купить: молоко\\, хлеб\\; сыр" in ics

    async def test_long_summary_is_folded(self, session):
        author = await make_user(session)
        long_title = "Очень " * 30 + "длинное название задачи"
        task = await _task(session, author=author, deadline=datetime.now(timezone.utc), title=long_title)
        ics = build_ics_feed([task])
        # Свёрнутая строка продолжается строкой, начинающейся с пробела.
        summary_lines = [line for line in ics.split("\r\n") if line.startswith("SUMMARY:") or line.startswith(" ")]
        assert len(summary_lines) > 1


class TestCalendarService:
    async def test_get_or_create_token_generates_once(self, session):
        user = await make_user(session)
        service = build_service(session)

        token1 = await service.get_or_create_token(user)
        token2 = await service.get_or_create_token(user)

        assert token1 == token2

    async def test_regenerate_token_changes_value(self, session):
        user = await make_user(session)
        service = build_service(session)

        token1 = await service.get_or_create_token(user)
        token2 = await service.regenerate_token(user)

        assert token1 != token2

    async def test_old_token_stops_working_after_regenerate(self, session):
        user = await make_user(session)
        service = build_service(session)
        old_token = await service.get_or_create_token(user)

        await service.regenerate_token(user)

        assert await service.build_feed_for_token(old_token) is None

    async def test_build_feed_for_unknown_token_returns_none(self, session):
        service = build_service(session)
        assert await service.build_feed_for_token("not-a-real-token") is None

    async def test_feed_includes_tasks_as_author_and_as_executor(self, session):
        user = await make_user(session)
        other = await make_user(session)
        service = build_service(session)
        token = await service.get_or_create_token(user)

        deadline = datetime.now(timezone.utc) + timedelta(days=2)
        await _task(session, author=user, user=other, deadline=deadline, title="Я автор")
        await _task(session, author=other, user=user, deadline=deadline, title="Я исполнитель")

        ics = await service.build_feed_for_token(token)

        assert "SUMMARY:Я автор" in ics
        assert "SUMMARY:Я исполнитель" in ics

    async def test_feed_excludes_other_users_tasks(self, session):
        user = await make_user(session)
        other = await make_user(session)
        service = build_service(session)
        token = await service.get_or_create_token(user)

        await _task(session, author=other, user=other, deadline=datetime.now(timezone.utc), title="Чужая задача")

        ics = await service.build_feed_for_token(token)

        assert "Чужая задача" not in ics

    async def test_feed_excludes_soft_deleted_tasks(self, session):
        user = await make_user(session)
        service = build_service(session)
        token = await service.get_or_create_token(user)

        await _task(
            session,
            author=user,
            deadline=datetime.now(timezone.utc),
            title="Удалённая задача",
            deleted_at=datetime.now(timezone.utc),
        )

        ics = await service.build_feed_for_token(token)

        assert "Удалённая задача" not in ics


class TestCalendarEndToEndViaRealApp:
    async def _login(self, client, engine, username: str) -> str:
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username=username, password="pass123")
        resp = await client.post("/auth/login", json={"username": username, "password": "pass123"})
        assert resp.status_code == 200
        return resp.json()["access_token"]

    async def test_get_token_before_creation_returns_null(self, client, engine):
        username = f"cal_{uuid.uuid4().hex[:6]}"
        jwt_token = await self._login(client, engine, username)

        resp = await client.get("/api/calendar/token", headers={"Authorization": f"Bearer {jwt_token}"})

        assert resp.status_code == 200
        assert resp.json() is None

    async def test_create_token_returns_feed_url(self, client, engine):
        username = f"cal_{uuid.uuid4().hex[:6]}"
        jwt_token = await self._login(client, engine, username)

        resp = await client.post("/api/calendar/token", headers={"Authorization": f"Bearer {jwt_token}"})

        assert resp.status_code == 200
        feed_url = resp.json()["feed_url"]
        assert "/api/calendar/feed.ics?token=" in feed_url

    async def test_feed_endpoint_requires_no_bearer_auth(self, client, engine):
        """Ключевое свойство фичи: календарный клиент не шлёт Authorization, только ?token=."""
        username = f"cal_{uuid.uuid4().hex[:6]}"
        jwt_token = await self._login(client, engine, username)
        created = await client.post("/api/calendar/token", headers={"Authorization": f"Bearer {jwt_token}"})
        feed_url = created.json()["feed_url"]
        token = feed_url.split("token=")[1]

        resp = await client.get(f"/api/calendar/feed.ics?token={token}")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/calendar")
        assert resp.text.startswith("BEGIN:VCALENDAR")

    async def test_feed_endpoint_rejects_invalid_token(self, client):
        resp = await client.get("/api/calendar/feed.ics?token=garbage")
        assert resp.status_code == 404

    async def test_regenerating_token_invalidates_old_url(self, client, engine):
        username = f"cal_{uuid.uuid4().hex[:6]}"
        jwt_token = await self._login(client, engine, username)
        headers = {"Authorization": f"Bearer {jwt_token}"}

        first = await client.post("/api/calendar/token", headers=headers)
        old_token = first.json()["feed_url"].split("token=")[1]

        await client.post("/api/calendar/token", headers=headers)

        resp = await client.get(f"/api/calendar/feed.ics?token={old_token}")
        assert resp.status_code == 404

    async def test_feed_reflects_created_task_deadline(self, client, engine):
        username = f"cal_{uuid.uuid4().hex[:6]}"
        jwt_token = await self._login(client, engine, username)
        headers = {"Authorization": f"Bearer {jwt_token}"}

        deadline = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0)
        await client.post(
            "/api/tasks",
            json={"title": "Задача с дедлайном", "deadline": deadline.isoformat()},
            headers=headers,
        )
        created = await client.post("/api/calendar/token", headers=headers)
        feed_url = created.json()["feed_url"]
        token = feed_url.split("token=")[1]

        resp = await client.get(f"/api/calendar/feed.ics?token={token}")

        assert "SUMMARY:Задача с дедлайном" in resp.text
