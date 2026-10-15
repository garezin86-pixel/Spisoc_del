# ruff: noqa: F811  (фикстуры world и mock_reminder_bot подставляются по имени аргумента)
# tests/test_event_reminders.py
"""Напоминание о скорой встрече/звонке (Этап 4): remind_event_upcoming шлёт ответственному в Telegram один раз.

Берутся запланированные события, которые начнутся в ближайшие 30 минут; повторно не шлём; перенос времени и возврат
отменённого в planned сбрасывают отметку; настройки, отключённая компания, заблокированный пользователь, нет Telegram,
удалённое событие и чужой клиент напоминаний не дают; сбой отправки не ставит отметку (повтор в следующий прогон).
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.audit import AuditLog
from src.models.client import ClientModel
from src.models.notification_log import NotificationLogModel
from src.models.notification_settings import NotificationSettingsModel
from src.models.scheduled_event import ScheduledEventModel
from src.models.user import UserModel
from src.models.workspace import WorkspaceModel
from src.services.reminders.service import remind_event_upcoming
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)
from tests.test_reminders_service import mock_reminder_bot  # noqa: F401  (фикстура: бот-мок и тестовая БД)


def _in(minutes: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


@pytest.fixture
async def ws(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        w = WorkspaceModel(name="A", slug=f"a-{uuid.uuid4().hex[:6]}")
        s.add(w)
        await s.commit()
        await s.refresh(w)
    return maker, w


async def _user(session, ws_id, *, telegram_id=True, is_active=True):
    user = UserModel(
        username=f"u_{uuid.uuid4().hex[:6]}",
        login=f"l_{uuid.uuid4().hex[:8]}",
        password_hash="x",
        role="manager",
        workspace_id=ws_id,
        telegram_id=int(uuid.uuid4().int % 10**9) if telegram_id else None,
        is_active=is_active,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _event(session, ws_id, assignee, *, minutes=20, **kwargs):
    owner_id = kwargs.pop("client_owner_id", assignee.id if assignee else None)
    client = ClientModel(name=kwargs.pop("client_name", "Ромашка"), workspace_id=ws_id, owner_id=owner_id)
    session.add(client)
    await session.commit()
    await session.refresh(client)
    event = ScheduledEventModel(
        client_id=client.id,
        type=kwargs.pop("type", "meeting"),
        starts_at=_in(minutes),
        assignee_id=assignee.id if assignee else None,
        workspace_id=ws_id,
        **kwargs,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


async def _reload(maker, event_id):
    async with maker() as s:
        return (await s.execute(select(ScheduledEventModel).where(ScheduledEventModel.id == event_id))).scalar_one()


async def test_sends_once_to_assignee_and_logs(ws, mock_reminder_bot):
    maker, w = ws
    async with maker() as s:
        user = await _user(s, w.id)
        event = await _event(s, w.id, user, minutes=20, title="Демо", duration_minutes=45)
    await remind_event_upcoming()

    assert mock_reminder_bot.send_message.await_count == 1
    kwargs = mock_reminder_bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == user.telegram_id
    assert "Встреча через" in kwargs["text"] and "Демо" in kwargs["text"] and "Ромашка" in kwargs["text"]
    assert "45 мин" in kwargs["text"]
    async with maker() as s:
        logs = (
            (await s.execute(select(NotificationLogModel).where(NotificationLogModel.user_id == user.id)))
            .scalars()
            .all()
        )
    assert [(log.notification_type, log.success, log.task_id) for log in logs] == [("event_reminder", True, None)]
    assert (await _reload(maker, event.id)).reminded_at is not None

    await remind_event_upcoming()  # повторный прогон — без повтора
    assert mock_reminder_bot.send_message.await_count == 1


async def test_call_text_and_minutes(ws, mock_reminder_bot):
    maker, w = ws
    async with maker() as s:
        user = await _user(s, w.id)
        await _event(s, w.id, user, minutes=10, type="call")
    await remind_event_upcoming()
    text = mock_reminder_bot.send_message.await_args.kwargs["text"]
    assert text.startswith("📞 Звонок через ") and "мин: Ромашка" in text


async def test_only_events_inside_the_window(ws, mock_reminder_bot):
    maker, w = ws
    async with maker() as s:
        user = await _user(s, w.id)
        await _event(s, w.id, user, minutes=90, client_name="Позже")
        await _event(s, w.id, user, minutes=-5, client_name="Уже началась")
    await remind_event_upcoming()
    assert mock_reminder_bot.send_message.await_count == 0


@pytest.mark.parametrize(
    "kind",
    ["no_telegram", "blocked", "setting_off", "workspace_off", "deleted_event", "cancelled", "done", "no_assignee"],
)
async def test_not_sent_when_not_allowed(ws, mock_reminder_bot, kind):
    maker, w = ws
    async with maker() as s:
        user = await _user(s, w.id, telegram_id=kind != "no_telegram", is_active=kind != "blocked")
        event = await _event(
            s,
            w.id,
            None if kind == "no_assignee" else user,
            status=kind if kind in ("cancelled", "done") else "planned",
        )
        if kind == "setting_off":
            s.add(NotificationSettingsModel(user_id=user.id, notify_event_reminder=False))
        if kind == "workspace_off":
            row = (await s.execute(select(WorkspaceModel).where(WorkspaceModel.id == w.id))).scalar_one()
            row.is_active = False
        if kind == "deleted_event":
            event.deleted_at = datetime.now(timezone.utc)
        await s.commit()
    await remind_event_upcoming()
    assert mock_reminder_bot.send_message.await_count == 0


async def test_send_failure_keeps_event_for_retry(ws, mock_reminder_bot):
    maker, w = ws
    async with maker() as s:
        user = await _user(s, w.id)
        event = await _event(s, w.id, user)
    mock_reminder_bot.send_message = AsyncMock(side_effect=RuntimeError("telegram down"))
    await remind_event_upcoming()
    assert (await _reload(maker, event.id)).reminded_at is None
    async with maker() as s:
        log = (
            (await s.execute(select(NotificationLogModel).where(NotificationLogModel.user_id == user.id)))
            .scalars()
            .one()
        )
    assert log.success is False

    mock_reminder_bot.send_message = AsyncMock()
    await remind_event_upcoming()
    assert mock_reminder_bot.send_message.await_count == 1


async def test_reminded_at_is_not_audited(ws, mock_reminder_bot):
    maker, w = ws
    async with maker() as s:
        user = await _user(s, w.id)
        event = await _event(s, w.id, user)
    await remind_event_upcoming()
    async with maker() as s:
        audit = (
            (
                await s.execute(
                    select(AuditLog).where(AuditLog.entity_type == "scheduled_events", AuditLog.entity_id == event.id)
                )
            )
            .scalars()
            .all()
        )
    assert all("reminded_at" not in (a.new_values or {}) for a in audit)


async def test_reschedule_and_reopen_reset_the_mark(client, world, mock_reminder_bot):
    maker, ids, logins = world
    async with maker() as s:
        owner = (await s.execute(select(UserModel).where(UserModel.id == ids["owner"]))).scalar_one()
        owner.telegram_id, owner.is_active = 777002, True
        await s.commit()
    h = await _headers(client, logins, "a_manager")
    created = await client.post(
        f"/api/clients/{ids['ca']}/events",
        json={"type": "meeting", "starts_at": _in(15).isoformat(), "assignee_id": ids["owner"]},
        headers=h,
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]
    url = f"/api/events/{event_id}"

    await remind_event_upcoming()
    assert mock_reminder_bot.send_message.await_count == 1
    assert (await client.patch(url, json={"title": "Без переноса"}, headers=h)).status_code == 200
    await remind_event_upcoming()
    assert mock_reminder_bot.send_message.await_count == 1  # правка текста отметку не сбрасывает

    assert (await client.patch(url, json={"starts_at": _in(20).isoformat()}, headers=h)).status_code == 200
    assert (await _reload(maker, event_id)).reminded_at is None  # перенос — новое напоминание
    await remind_event_upcoming()
    assert mock_reminder_bot.send_message.await_count == 2

    await client.patch(url, json={"status": "cancelled"}, headers=h)
    await remind_event_upcoming()
    assert mock_reminder_bot.send_message.await_count == 2  # отменённое молчит
    await client.patch(url, json={"status": "planned"}, headers=h)
    assert (await _reload(maker, event_id)).reminded_at is None  # вернули в работу
    await remind_event_upcoming()
    assert mock_reminder_bot.send_message.await_count == 3
