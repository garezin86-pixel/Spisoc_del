"""Отключённая компания (workspaces.is_active=False) и принудительный обрыв WebSocket."""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.websockets import WebSocketDisconnect

from src.admin.views.workspace_admin import WorkspaceAdmin
from src.bot.middlewares import workspace_context as wc
from src.core.security import hash_password
from src.core.ws_manager import WSManager, ws_manager
from src.models import UserModel
from src.models.webhook import WebhookModel
from src.models.workspace import WorkspaceModel
from src.repositories.other_repositories import NotificationSettingsRepository
from src.repositories.webhook_repository import WebhookRepository
from src.routers.ws_router import router as ws_router
from src.services.calendar_service import CalendarService

pytestmark = pytest.mark.asyncio
PASSWORD = "password123"


def _uniq(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _company(maker, *, active: bool = True):
    """Компания + активный пользователь в ней. Возвращает (workspace_id, login, user_id)."""
    login = _uniq("emp")
    async with maker() as s:
        ws = WorkspaceModel(name="Co", slug=_uniq("co"), is_active=active)
        s.add(ws)
        await s.commit()
        user = UserModel(username=login, login=login, password_hash=hash_password(PASSWORD), workspace_id=ws.id)
        s.add(user)
        await s.commit()
        return ws.id, login, user.id


async def _disable(maker, ws_id: int):
    async with maker() as s:
        await s.execute(update(WorkspaceModel).where(WorkspaceModel.id == ws_id).values(is_active=False))
        await s.commit()


async def _login(client, login):
    return await client.post("/auth/login", json={"username": login, "password": PASSWORD})


# ── Вход и токены ────────────────────────────────────────────────────────────
async def test_login_rejected_for_disabled_company(client, maker):
    _, login, _ = await _company(maker, active=False)
    resp = await _login(client, login)
    assert resp.status_code == 401
    assert "Company" in resp.text


async def test_wrong_password_does_not_reveal_company_state(client, maker):
    _, login, _ = await _company(maker, active=False)
    resp = await client.post("/auth/login", json={"username": login, "password": "wrong-password"})
    assert resp.status_code == 401
    assert "Company" not in resp.text  # причина раскрывается только после верного пароля


async def test_existing_access_token_stops_working_when_company_disabled(client, maker):
    ws_id, login, _ = await _company(maker)
    login_resp = await _login(client, login)
    assert login_resp.status_code == 200
    headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}
    assert (await client.get("/api/tokens", headers=headers)).status_code == 200

    await _disable(maker, ws_id)
    resp = await client.get("/api/tokens", headers=headers)
    assert resp.status_code == 401 and "Company" in resp.text


async def test_refresh_token_rejected_when_company_disabled(client, maker):
    ws_id, login, _ = await _company(maker)
    refresh = (await _login(client, login)).json()["refresh_token"]
    await _disable(maker, ws_id)
    resp = await client.post("/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401


async def test_personal_access_token_stops_working_when_company_disabled(client, maker):
    ws_id, login, _ = await _company(maker)
    jwt = (await _login(client, login)).json()["access_token"]
    created = await client.post("/api/tokens", json={"name": "ci"}, headers={"Authorization": f"Bearer {jwt}"})
    pat = created.json()["token"]
    assert (await client.get("/api/tokens", headers={"Authorization": f"Bearer {pat}"})).status_code == 200

    await _disable(maker, ws_id)
    assert (await client.get("/api/tokens", headers={"Authorization": f"Bearer {pat}"})).status_code == 401


async def test_reenabled_company_works_again(client, maker):
    ws_id, login, _ = await _company(maker)
    await _disable(maker, ws_id)
    assert (await _login(client, login)).status_code == 401
    async with maker() as s:
        await s.execute(update(WorkspaceModel).where(WorkspaceModel.id == ws_id).values(is_active=True))
        await s.commit()
    assert (await _login(client, login)).status_code == 200


async def test_other_company_is_unaffected(client, maker):
    ws_a, _, _ = await _company(maker)
    _, login_b, _ = await _company(maker)
    await _disable(maker, ws_a)
    assert (await _login(client, login_b)).status_code == 200


# ── iCal, получатели, вебхуки ────────────────────────────────────────────────
async def test_calendar_feed_of_disabled_company_returns_none(maker):
    ws_id, _, user_id = await _company(maker)
    async with maker() as s:
        user = await s.get(UserModel, user_id)
        token = user.calendar_feed_token = "t" * 64
        await s.commit()
    await _disable(maker, ws_id)

    async with maker() as s:
        from src.repositories.calendar_repository import CalendarRepository

        assert await CalendarService(CalendarRepository(s)).build_feed_for_token(token) is None


async def test_workspace_is_active_works_in_python_and_in_sql(maker):
    ws_on, _, uid_on = await _company(maker)
    ws_off, _, uid_off = await _company(maker, active=False)
    async with maker() as s:
        on = await s.get(UserModel, uid_on)
        off = await s.get(UserModel, uid_off)
        assert on.workspace_is_active is True and off.workspace_is_active is False
        ids = set((await s.scalars(select(UserModel.id).where(UserModel.workspace_is_active))).all())
        assert uid_on in ids and uid_off not in ids


async def test_notification_recipient_queries_skip_disabled_company(maker):
    from src.models.notification_settings import NotificationSettingsModel

    _, _, uid_on = await _company(maker)
    ws_off, _, uid_off = await _company(maker)
    async with maker() as s:
        for uid in (uid_on, uid_off):
            u = await s.get(UserModel, uid)
            u.telegram_id = uid + 9_000_000
            s.add(NotificationSettingsModel(user_id=uid, weekly_report_enabled=True, notify_group_assigned=True))
        await s.commit()
    await _disable(maker, ws_off)

    async with maker() as s:
        repo = NotificationSettingsRepository(s)
        for method in (repo.get_users_with_weekly_report, repo.get_users_with_group_notifications):
            got = {u.id for u in await method()}
            assert uid_on in got and uid_off not in got, method.__name__


async def test_webhooks_of_disabled_company_are_not_selected(maker):
    _, _, uid_on = await _company(maker)
    ws_off, _, uid_off = await _company(maker)
    async with maker() as s:
        for uid in (uid_on, uid_off):
            user = await s.get(UserModel, uid)
            s.add(
                WebhookModel(
                    user_id=uid,
                    url="https://example.com/h",
                    secret="s",
                    secret_prefix="s",
                    events=["task.created"],
                    workspace_id=user.workspace_id,
                )
            )
        await s.commit()
    await _disable(maker, ws_off)

    async with maker() as s:
        hooks = await WebhookRepository(s).get_active_for_users([uid_on, uid_off])
    assert [h.user_id for h in hooks] == [uid_on]


# ── WebSocket ────────────────────────────────────────────────────────────────
def _ws_app():
    app = FastAPI()
    app.include_router(ws_router, prefix="/api")
    return app


def _fake_uow(user):
    uow = MagicMock()
    uow.users.get_by_id = AsyncMock(return_value=user)

    @asynccontextmanager
    async def _cm(*a, **k):
        yield uow

    return _cm


async def test_ws_connect_rejected_when_company_disabled():
    user = MagicMock(id=1, is_active=True, workspace_is_active=False, workspace_id=5)
    with (
        patch("src.routers.ws_router.decode_access_token", return_value={"sub": "1"}),
        patch("src.routers.ws_router.UnitOfWork", side_effect=_fake_uow(user)),
        patch("src.routers.ws_router.get_session_maker", return_value=MagicMock()),
        TestClient(_ws_app()) as client,
    ):
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/ws?token=t"):
                pass
    assert exc.value.code == 4001
    ws_manager._connections.clear()


def _sock():
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    return ws


async def test_disconnect_user_closes_all_tabs_with_4001():
    mgr = WSManager()
    a1, a2, b = _sock(), _sock(), _sock()
    await mgr.connect(a1, 1, 10)
    await mgr.connect(a2, 1, 10)
    await mgr.connect(b, 2, 10)

    assert await mgr.disconnect_user(1) == 2
    for ws in (a1, a2):
        ws.close.assert_awaited_once()
        assert ws.close.await_args.kwargs["code"] == 4001
    b.close.assert_not_awaited()
    assert mgr.total_connections == 1


async def test_disconnect_user_when_not_connected_is_noop():
    assert await WSManager().disconnect_user(42) == 0


async def test_disconnect_survives_already_closed_socket():
    mgr = WSManager()
    ws = _sock()
    ws.close.side_effect = RuntimeError("already closed")
    await mgr.connect(ws, 1, 10)
    assert await mgr.disconnect_user(1) == 1
    assert mgr.total_connections == 0


async def test_disconnect_workspace_closes_only_that_company():
    mgr = WSManager()
    mine, other = _sock(), _sock()
    await mgr.connect(mine, 1, 10)
    await mgr.connect(other, 2, 20)
    assert await mgr.disconnect_workspace(10) == 1
    mine.close.assert_awaited_once()
    other.close.assert_not_awaited()


async def test_workspace_admin_disabling_closes_sockets_enabling_does_not():
    view = WorkspaceAdmin()
    request = MagicMock()
    request.session.get.return_value = 1
    with patch("src.admin.views.workspace_admin.ws_manager") as mgr:
        mgr.disconnect_workspace = AsyncMock(return_value=3)
        await view.after_model_change({}, WorkspaceModel(id=7, name="x", slug="x", is_active=True), False, request)
        mgr.disconnect_workspace.assert_not_awaited()
        await view.after_model_change({}, WorkspaceModel(id=7, name="x", slug="x", is_active=False), False, request)
        mgr.disconnect_workspace.assert_awaited_once_with(7)


# ── Telegram-бот ─────────────────────────────────────────────────────────────
def _session_returning(row):
    session = MagicMock()
    result = MagicMock()
    result.first.return_value = row
    session.execute = AsyncMock(return_value=result)

    @asynccontextmanager
    async def _cm():
        yield session

    return lambda: _cm()


def _row(ws_id, active):
    row = MagicMock()
    row.workspace_id, row.is_active = ws_id, active
    return row


async def test_bot_denies_message_from_disabled_company_without_calling_handler():
    handler = AsyncMock()
    update_obj = MagicMock(callback_query=None, message=MagicMock(answer=AsyncMock()))
    with patch.object(wc, "get_session_maker", return_value=_session_returning(_row(3, False))):
        out = await wc.WorkspaceContextMiddleware()(handler, update_obj, {"event_from_user": MagicMock(id=77)})
    assert out is None
    handler.assert_not_awaited()
    update_obj.message.answer.assert_awaited_once()
    assert "отключён" in update_obj.message.answer.await_args.args[0]


async def test_bot_denies_callback_from_disabled_company():
    handler = AsyncMock()
    update_obj = MagicMock(message=None, callback_query=MagicMock(answer=AsyncMock()))
    with patch.object(wc, "get_session_maker", return_value=_session_returning(_row(3, False))):
        await wc.WorkspaceContextMiddleware()(handler, update_obj, {"event_from_user": MagicMock(id=77)})
    handler.assert_not_awaited()
    update_obj.callback_query.answer.assert_awaited_once()
    assert update_obj.callback_query.answer.await_args.kwargs["show_alert"] is True


async def test_bot_lets_active_company_and_unregistered_users_through():
    for row in (_row(3, True), None):
        handler = AsyncMock(return_value="handled")
        with patch.object(wc, "get_session_maker", return_value=_session_returning(row)):
            out = await wc.WorkspaceContextMiddleware()(handler, MagicMock(), {"event_from_user": MagicMock(id=77)})
        assert out == "handled"


async def test_bot_admin_blocking_user_disconnects_websocket():
    from src.bot.handlers import admin as bot_admin

    target = MagicMock(id=55, username="vasya", is_active=True)
    uow = MagicMock()
    uow.users.get_by_id = AsyncMock(return_value=target)
    uow.users.update = AsyncMock()

    @asynccontextmanager
    async def _uow(*a, **k):
        yield uow

    message = MagicMock(text="55", answer=AsyncMock())
    state = MagicMock(clear=AsyncMock())
    handler_fn = bot_admin.block_user
    with (
        patch.object(bot_admin, "UnitOfWork", side_effect=_uow),
        patch.object(bot_admin, "get_session_maker", return_value=MagicMock()),
        patch.object(bot_admin, "ws_manager") as mgr,
    ):
        mgr.disconnect_user = AsyncMock()
        await handler_fn(message, state)
    assert target.is_active is False
    mgr.disconnect_user.assert_awaited_once_with(55)
