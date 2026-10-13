# ruff: noqa: F811  (фикстуры world и mock_reminder_bot подставляются по имени аргумента)
# tests/test_contact_reminders.py
"""«Связаться снова»: дата следующего контакта у клиента и напоминание ответственному.

API: дата ставится при создании/правке (не в прошлом), очищается null; фильтры списка contact_due и owner_id.
Рассылка: remind_contact_due шлёт в Telegram ответственному один раз на дату; уважает настройки, отключённую
компанию, заблокированного пользователя, отсутствие Telegram; смена даты — новое напоминание.
"""

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.audit import AuditLog
from src.models.client import ClientModel
from src.models.notification_log import NotificationLogModel
from src.models.notification_settings import NotificationSettingsModel
from src.models.user import UserModel
from src.models.workspace import WorkspaceModel
from src.services.reminders.service import remind_contact_due
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)
from tests.test_reminders_service import mock_reminder_bot  # noqa: F401  (фикстура: бот-мок и тестовая БД)


def _day(delta: int) -> str:
    return (date.today() + timedelta(days=delta)).isoformat()


# ── API ──────────────────────────────────────────────────────────────────────
async def test_set_and_clear_next_contact(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    created = await client.post("/api/clients", json={"name": "Новый", "next_contact_at": _day(3)}, headers=h)
    assert created.status_code == 201 and created.json()["next_contact_at"] == _day(3)

    url = f"/api/clients/{ids['ca']}"
    resp = await client.patch(url, json={"next_contact_at": _day(7)}, headers=h)
    assert resp.status_code == 200 and resp.json()["next_contact_at"] == _day(7)
    cleared = await client.patch(url, json={"next_contact_at": None}, headers=h)
    assert cleared.status_code == 200 and cleared.json()["next_contact_at"] is None


async def test_next_contact_in_past_rejected(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    assert (
        await client.patch(f"/api/clients/{ids['ca']}", json={"next_contact_at": _day(-5)}, headers=h)
    ).status_code == 422
    assert (
        await client.post("/api/clients", json={"name": "X", "next_contact_at": _day(-5)}, headers=h)
    ).status_code == 422
    # сегодня и вчера (допуск на часовые пояса) — можно
    assert (
        await client.patch(f"/api/clients/{ids['ca']}", json={"next_contact_at": _day(0)}, headers=h)
    ).status_code == 200


async def test_owner_sets_date_but_stranger_cannot(client, world):
    _, ids, logins = world
    ho = await _headers(client, logins, "owner")  # ответственный за ca
    assert (
        await client.patch(f"/api/clients/{ids['ca']}", json={"next_contact_at": _day(2)}, headers=ho)
    ).status_code == 200
    h = await _headers(client, logins, "other")
    assert (
        await client.patch(f"/api/clients/{ids['ca']}", json={"next_contact_at": _day(5)}, headers=h)
    ).status_code == 403


async def test_contact_due_and_owner_filters(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    due = (await client.post("/api/clients", json={"name": "Просрочен"}, headers=h)).json()
    later = (await client.post("/api/clients", json={"name": "Позже", "next_contact_at": _day(10)}, headers=h)).json()
    await client.post("/api/clients", json={"name": "Без даты"}, headers=h)
    await client.patch(f"/api/clients/{due['id']}", json={"next_contact_at": _day(0)}, headers=h)

    def names(resp):
        return [c["name"] for c in resp.json()["items"]]

    assert names(await client.get("/api/clients", params={"contact_due": "true"}, headers=h)) == ["Просрочен"]
    assert later["id"] and "Позже" in names(await client.get("/api/clients", headers=h))  # без фильтра — все
    mine = await client.get("/api/clients", params={"owner_id": ids["a_manager"]}, headers=h)
    assert sorted(names(mine)) == ["Без даты", "Позже", "Просрочен"]  # «Ромашка» — у owner
    assert names(await client.get("/api/clients", params={"owner_id": ids["owner"]}, headers=h)) == ["Ромашка"]


async def test_notified_mark_not_in_audit_history(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    await client.patch(f"/api/clients/{ids['ca']}", json={"next_contact_at": _day(1)}, headers=h)
    async with maker() as s:
        row = (await s.execute(select(ClientModel).where(ClientModel.id == ids["ca"]))).scalar_one()
        row.next_contact_notified_at = row.created_at  # как это делает рассылка
        await s.commit()
        audit = (
            (
                await s.execute(
                    select(AuditLog).where(AuditLog.entity_type == "clients", AuditLog.entity_id == ids["ca"])
                )
            )
            .scalars()
            .all()
        )
    assert all("next_contact_notified_at" not in (a.new_values or {}) for a in audit)


# ── рассылка ─────────────────────────────────────────────────────────────────
async def _owner(session, ws_id, *, telegram_id=True, is_active=True, name=None):
    user = UserModel(
        username=name or f"u_{uuid.uuid4().hex[:6]}",
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


async def _client_row(session, ws_id, owner, *, due_in=0, **kwargs):
    row = ClientModel(
        name=kwargs.pop("name", "Ромашка"),
        workspace_id=ws_id,
        owner_id=owner.id if owner else None,
        next_contact_at=date.today() + timedelta(days=due_in),
        **kwargs,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@pytest.fixture
async def ws(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        w = WorkspaceModel(name="A", slug=f"a-{uuid.uuid4().hex[:6]}")
        s.add(w)
        await s.commit()
        await s.refresh(w)
    return maker, w


async def test_sends_once_to_owner_and_logs(ws, mock_reminder_bot):
    maker, w = ws
    async with maker() as s:
        owner = await _owner(s, w.id)
        c = await _client_row(s, w.id, owner, phone="+380501112233", name="Ромашка и компания")
    await remind_contact_due()

    assert mock_reminder_bot.send_message.await_count == 1
    kwargs = mock_reminder_bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == owner.telegram_id
    assert "Ромашка и компания" in kwargs["text"] and "+380501112233" in kwargs["text"]
    async with maker() as s:
        logs = (
            (await s.execute(select(NotificationLogModel).where(NotificationLogModel.user_id == owner.id)))
            .scalars()
            .all()
        )
        row = (await s.execute(select(ClientModel).where(ClientModel.id == c.id))).scalar_one()
    assert [(log.notification_type, log.success, log.task_id) for log in logs] == [("contact_due", True, None)]
    assert row.next_contact_notified_at is not None

    await remind_contact_due()  # повторный прогон — без повтора
    assert mock_reminder_bot.send_message.await_count == 1


async def test_future_date_and_no_owner_not_sent(ws, mock_reminder_bot):
    maker, w = ws
    async with maker() as s:
        owner = await _owner(s, w.id)
        await _client_row(s, w.id, owner, due_in=3, name="Позже")
        await _client_row(s, w.id, None, name="Без ответственного")
    await remind_contact_due()
    assert mock_reminder_bot.send_message.await_count == 0


async def test_overdue_marked_in_text(ws, mock_reminder_bot):
    maker, w = ws
    async with maker() as s:
        owner = await _owner(s, w.id)
        await _client_row(s, w.id, owner, due_in=-4)
    await remind_contact_due()
    assert "просрочено на 4 дн." in mock_reminder_bot.send_message.await_args.kwargs["text"]


@pytest.mark.parametrize("kind", ["no_telegram", "blocked", "setting_off", "workspace_off", "deleted_client"])
async def test_not_sent_when_not_allowed(ws, mock_reminder_bot, kind):
    maker, w = ws
    async with maker() as s:
        owner = await _owner(s, w.id, telegram_id=kind != "no_telegram", is_active=kind != "blocked")
        c = await _client_row(s, w.id, owner)
        if kind == "setting_off":
            s.add(NotificationSettingsModel(user_id=owner.id, notify_contact_due=False))
        if kind == "workspace_off":
            ws_row = (await s.execute(select(WorkspaceModel).where(WorkspaceModel.id == w.id))).scalar_one()
            ws_row.is_active = False
        if kind == "deleted_client":
            c.deleted_at = c.created_at
        await s.commit()
    await remind_contact_due()
    assert mock_reminder_bot.send_message.await_count == 0


async def test_changing_date_resets_and_sends_again(client, world, mock_reminder_bot):
    maker, ids, logins = world
    async with maker() as s:
        owner = (await s.execute(select(UserModel).where(UserModel.id == ids["owner"]))).scalar_one()
        owner.telegram_id, owner.is_active = 777001, True
        await s.commit()
    h = await _headers(client, logins, "a_manager")
    await client.patch(f"/api/clients/{ids['ca']}", json={"next_contact_at": _day(0)}, headers=h)
    await remind_contact_due()
    assert mock_reminder_bot.send_message.await_count == 1

    await client.patch(f"/api/clients/{ids['ca']}", json={"next_contact_at": _day(0)}, headers=h)  # та же дата
    await remind_contact_due()
    assert mock_reminder_bot.send_message.await_count == 1  # без повтора

    await client.patch(f"/api/clients/{ids['ca']}", json={"next_contact_at": _day(1)}, headers=h)  # новая дата
    async with maker() as s:
        row = (await s.execute(select(ClientModel).where(ClientModel.id == ids["ca"]))).scalar_one()
        assert row.next_contact_notified_at is None  # отметка сброшена
        row.next_contact_at = date.today()  # «наступил» новый день
        await s.commit()
    await remind_contact_due()
    assert mock_reminder_bot.send_message.await_count == 2


async def test_send_failure_keeps_client_for_retry(ws, mock_reminder_bot):
    maker, w = ws
    async with maker() as s:
        owner = await _owner(s, w.id)
        c = await _client_row(s, w.id, owner)
    mock_reminder_bot.send_message = AsyncMock(side_effect=RuntimeError("telegram down"))
    await remind_contact_due()
    async with maker() as s:
        row = (await s.execute(select(ClientModel).where(ClientModel.id == c.id))).scalar_one()
        log = (
            (await s.execute(select(NotificationLogModel).where(NotificationLogModel.user_id == owner.id)))
            .scalars()
            .one()
        )
    assert row.next_contact_notified_at is None and log.success is False  # отметки нет — попробуем в следующий прогон
    mock_reminder_bot.send_message = AsyncMock()
    await remind_contact_due()
    assert mock_reminder_bot.send_message.await_count == 1
