"""Регистрация компаний, приглашения и вход по приглашению (веб и Telegram)."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.handlers import start as start_handlers
from src.core.security import hash_password
from src.models import UserModel
from src.models.workspace import WorkspaceModel
from src.models.workspace_invite import WorkspaceInviteModel
from src.repositories.users_repository import UserRepository
from src.repositories.workspace_repository import WorkspaceRepository
from src.services.workspace_service import WorkspaceService, build_company_slug_base

pytestmark = pytest.mark.asyncio

PASSWORD = "password123"


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _make_company(maker, name: str, admin_name: str | None = None):
    """Workspace + админ (role=admin) напрямую в БД. Возвращает (workspace_id, admin_login)."""
    admin_name = admin_name or _uniq("admin")
    async with maker() as s:
        ws = WorkspaceModel(name=name, slug=_uniq("co"))
        s.add(ws)
        await s.commit()
        s.add(
            UserModel(
                username=admin_name,
                login=admin_name,
                password_hash=hash_password(PASSWORD),
                role="admin",
                workspace_id=ws.id,
            )
        )
        await s.commit()
        return ws.id, admin_name


async def _headers(client, login: str) -> dict:
    resp = await client.post("/auth/login", json={"username": login, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _new_invite(client, headers) -> dict:
    resp = await client.post("/api/workspace/invites", headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _user_by_login(maker, login: str) -> UserModel:
    async with maker() as s:
        return await s.scalar(select(UserModel).where(UserModel.login == login))


async def _user_by_username(maker, username: str) -> UserModel:
    # login генерируется из username транслитерацией (см. login_service), поэтому с username не совпадает
    async with maker() as s:
        return await s.scalar(select(UserModel).where(UserModel.username == username))


# ── Приглашения: создание, список, отзыв ─────────────────────────────────────
async def test_admin_creates_invite_with_7_day_expiry(client, maker):
    _, admin = await _make_company(maker, "A")
    invite = await _new_invite(client, await _headers(client, admin))

    assert invite["bot_start_param"] == f"ws_{invite['token']}"
    assert len(invite["bot_start_param"]) <= 64  # лимит Telegram на параметр deep link
    expires = datetime.fromisoformat(invite["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    assert timedelta(days=6, hours=23) < expires - datetime.now(timezone.utc) < timedelta(days=7, minutes=1)


async def test_non_admin_cannot_manage_invites(client, maker):
    ws_id, admin = await _make_company(maker, "A")
    invite = await _new_invite(client, await _headers(client, admin))
    joined = await client.post(
        "/auth/register", json={"username": _uniq("emp"), "password": PASSWORD, "invite_token": invite["token"]}
    )
    assert joined.status_code == 201
    async with maker() as s:
        emp = await s.scalar(select(UserModel).where(UserModel.workspace_id == ws_id, UserModel.role == "user"))
    headers = await _headers(client, emp.login)

    assert (await client.post("/api/workspace/invites", headers=headers)).status_code == 403
    assert (await client.get("/api/workspace/invites", headers=headers)).status_code == 403
    assert (await client.delete(f"/api/workspace/invites/{invite['id']}", headers=headers)).status_code == 403


async def test_invites_are_isolated_between_companies(client, maker):
    _, admin_a = await _make_company(maker, "A")
    _, admin_b = await _make_company(maker, "B")
    ha, hb = await _headers(client, admin_a), await _headers(client, admin_b)
    inv_a = await _new_invite(client, ha)

    listed_b = (await client.get("/api/workspace/invites", headers=hb)).json()
    assert listed_b == []  # админ B не видит приглашений A
    assert (await client.delete(f"/api/workspace/invites/{inv_a['id']}", headers=hb)).status_code == 404
    assert [i["id"] for i in (await client.get("/api/workspace/invites", headers=ha)).json()] == [inv_a["id"]]


async def test_revoked_invite_stops_working_and_leaves_active_list(client, maker):
    _, admin = await _make_company(maker, "A")
    h = await _headers(client, admin)
    invite = await _new_invite(client, h)

    revoked = await client.delete(f"/api/workspace/invites/{invite['id']}", headers=h)
    assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None
    assert (await client.get("/api/workspace/invites", headers=h)).json() == []
    assert len((await client.get("/api/workspace/invites?include_inactive=true", headers=h)).json()) == 1

    resp = await client.post(
        "/auth/register", json={"username": _uniq("emp"), "password": PASSWORD, "invite_token": invite["token"]}
    )
    assert resp.status_code == 400


# ── Регистрация по приглашению ───────────────────────────────────────────────
async def test_register_by_invite_joins_company_as_plain_user(client, maker):
    ws_id, admin = await _make_company(maker, "A")
    invite = await _new_invite(client, await _headers(client, admin))
    name = _uniq("emp")

    resp = await client.post(
        "/auth/register",
        # role в запросе — попытка повысить себя; схема её не принимает, роль определяет только сценарий
        json={"username": name, "password": PASSWORD, "invite_token": invite["token"], "role": "admin"},
    )
    assert resp.status_code == 201
    assert resp.json()["access_token"] and resp.json()["refresh_token"]

    user = await _user_by_username(maker, name)
    assert user.workspace_id == ws_id
    assert user.role == "user"
    assert user.is_platform_admin is False


async def test_invite_can_be_used_many_times(client, maker):
    ws_id, admin = await _make_company(maker, "A")
    invite = await _new_invite(client, await _headers(client, admin))
    for _ in range(3):
        resp = await client.post(
            "/auth/register", json={"username": _uniq("emp"), "password": PASSWORD, "invite_token": invite["token"]}
        )
        assert resp.status_code == 201
    async with maker() as s:
        n = len(
            (await s.scalars(select(UserModel).where(UserModel.workspace_id == ws_id, UserModel.role == "user"))).all()
        )
    assert n == 3


async def test_expired_or_unknown_invite_is_rejected(client, maker):
    _, admin = await _make_company(maker, "A")
    invite = await _new_invite(client, await _headers(client, admin))
    async with maker() as s:
        await s.execute(
            update(WorkspaceInviteModel)
            .where(WorkspaceInviteModel.id == invite["id"])
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await s.commit()

    for token in (invite["token"], "does-not-exist-123"):
        resp = await client.post(
            "/auth/register", json={"username": _uniq("emp"), "password": PASSWORD, "invite_token": token}
        )
        assert resp.status_code == 400


async def test_invite_of_disabled_company_is_rejected(client, maker):
    ws_id, admin = await _make_company(maker, "A")
    invite = await _new_invite(client, await _headers(client, admin))
    async with maker() as s:
        await s.execute(update(WorkspaceModel).where(WorkspaceModel.id == ws_id).values(is_active=False))
        await s.commit()
    resp = await client.post(
        "/auth/register", json={"username": _uniq("emp"), "password": PASSWORD, "invite_token": invite["token"]}
    )
    assert resp.status_code == 400


async def test_same_username_allowed_in_different_companies_but_not_within_one(client, maker):
    _, admin_a = await _make_company(maker, "A")
    _, admin_b = await _make_company(maker, "B")
    inv_a = await _new_invite(client, await _headers(client, admin_a))
    inv_b = await _new_invite(client, await _headers(client, admin_b))

    ok_a = await client.post(
        "/auth/register", json={"username": "Иван Петров", "password": PASSWORD, "invite_token": inv_a["token"]}
    )
    ok_b = await client.post(
        "/auth/register", json={"username": "Иван Петров", "password": PASSWORD, "invite_token": inv_b["token"]}
    )
    dup_a = await client.post(
        "/auth/register", json={"username": "Иван Петров", "password": PASSWORD, "invite_token": inv_a["token"]}
    )

    assert ok_a.status_code == 201 and ok_b.status_code == 201
    assert dup_a.status_code == 400
    async with maker() as s:
        rows = (await s.scalars(select(UserModel).where(UserModel.username == "Иван Петров"))).all()
    assert len({u.workspace_id for u in rows}) == 2
    assert len({u.login for u in rows}) == 2  # login уникален глобально


# ── Регистрация новой компании ───────────────────────────────────────────────
async def test_company_registration_is_disabled_by_default(client):
    resp = await client.post(
        "/auth/register", json={"username": _uniq("founder"), "password": PASSWORD, "company_name": "Ромашка"}
    )
    assert resp.status_code == 403


async def test_company_registration_creates_workspace_and_admin(client, maker):
    name = _uniq("founder")
    with patch("src.services.workspace_service.ALLOW_COMPANY_REGISTRATION", True):
        resp = await client.post(
            "/auth/register", json={"username": name, "password": PASSWORD, "company_name": "ООО  Ромашка"}
        )
    assert resp.status_code == 201

    user = await _user_by_username(maker, name)
    assert user.role == "admin"
    assert user.is_platform_admin is False  # доступ в SQLAdmin по регистрации не выдаётся никогда
    async with maker() as s:
        ws = await s.get(WorkspaceModel, user.workspace_id)
    assert ws.name == "ООО Ромашка"  # лишние пробелы схлопнуты
    assert ws.slug.startswith("ooo-romashka")

    # Основатель сразу может приглашать сотрудников в свою (и только свою) компанию.
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    invite = await _new_invite(client, headers)
    async with maker() as s:
        assert (await s.get(WorkspaceInviteModel, invite["id"])).workspace_id == user.workspace_id


async def test_two_companies_with_same_name_get_distinct_slugs(client, maker):
    with patch("src.services.workspace_service.ALLOW_COMPANY_REGISTRATION", True):
        for _ in range(2):
            resp = await client.post(
                "/auth/register", json={"username": _uniq("founder"), "password": PASSWORD, "company_name": "Ромашка"}
            )
            assert resp.status_code == 201
    async with maker() as s:
        slugs = (await s.scalars(select(WorkspaceModel.slug).where(WorkspaceModel.slug.like("romashka%")))).all()
    assert len(slugs) == len(set(slugs)) == 2


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"company_name": "Ромашка", "invite_token": "abcdefgh1234"},
        {"company_name": "Р"},
        {"invite_token": "bad token!"},
    ],
)
async def test_register_requires_exactly_one_valid_scenario(client, extra):
    resp = await client.post("/auth/register", json={"username": _uniq("u"), "password": PASSWORD, **extra})
    assert resp.status_code == 422


def test_company_slug_base():
    assert build_company_slug_base("ООО «Ромашка и Ко»") == "ooo-romashka-i-ko"
    assert build_company_slug_base("🚀🚀") == "company"
    assert len(build_company_slug_base("a" * 200)) <= 48


# ── Telegram: мгновенное присоединение по токену ─────────────────────────────
async def _service_and_invite(maker, session):
    ws_id, admin_login = await _make_company(maker, "A")
    admin = await _user_by_login(maker, admin_login)
    service = WorkspaceService(WorkspaceRepository(session), UserRepository(session))
    return service, ws_id, await service.create_invite(admin)


async def test_telegram_join_creates_user_in_invites_company(maker):
    async with maker() as admin_session:
        _, ws_id, invite = await _service_and_invite(maker, admin_session)
    async with maker() as s:
        service = WorkspaceService(WorkspaceRepository(s), UserRepository(s))
        result = await service.join_by_invite_telegram(invite.token, 555000111, "Пётр Сидоров")

    assert result is not None
    assert result.user.workspace_id == ws_id
    assert result.user.role == "user"
    assert result.user.telegram_id == 555000111
    assert result.user.must_change_password is True
    assert result.user.username == "Пётр Сидоров" and result.login.startswith("petr.s")


async def test_telegram_join_same_display_name_gets_suffix(maker):
    async with maker() as s0:
        _, _, invite = await _service_and_invite(maker, s0)
    names = []
    for tg_id in (555000201, 555000202):
        async with maker() as s:
            service = WorkspaceService(WorkspaceRepository(s), UserRepository(s))
            res = await service.join_by_invite_telegram(invite.token, tg_id, "Анна Иванова")
            names.append((res.user.username, res.login))
    assert names[0][0] != names[1][0] and names[0][1] != names[1][1]


async def test_telegram_join_invalid_invite_returns_none(maker):
    async with maker() as s:
        service = WorkspaceService(WorkspaceRepository(s), UserRepository(s))
        assert await service.join_by_invite_telegram("nope-nope-nope", 555000301, "X Y") is None


def _tg_message(tg_id: int, full_name: str = "Мария Кузнецова"):
    msg = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = tg_id
    msg.from_user.full_name = full_name
    msg.from_user.username = "maria"
    return msg


async def test_start_with_ws_param_goes_to_join_before_no_access_check():
    message = _tg_message(1)
    command = MagicMock()
    command.args = "ws_AbCdEfGh1234"
    with patch.object(start_handlers, "_join_workspace", new=AsyncMock()) as join:
        await start_handlers.cmd_start_deeplink(message, command, AsyncMock())
    join.assert_awaited_once_with(message, "AbCdEfGh1234")
    message.answer.assert_not_called()  # никакого «нет доступа» раньше времени


async def test_join_handler_end_to_end_creates_user_and_sends_credentials(maker):
    async with maker() as s0:
        _, ws_id, invite = await _service_and_invite(maker, s0)
    message = _tg_message(555000401)

    with patch.object(start_handlers, "get_session_maker", return_value=maker):
        await start_handlers._join_workspace(message, invite.token)

    text = message.answer.call_args.args[0]
    assert "Логин" in text and "Пароль" in text
    async with maker() as s:
        user = await s.scalar(select(UserModel).where(UserModel.telegram_id == 555000401))
    assert user is not None and user.workspace_id == ws_id
    assert f"<code>{user.login}</code>" in text


async def test_join_handler_rejects_bad_token_and_existing_user(maker):
    message = _tg_message(555000501)
    with patch.object(start_handlers, "get_session_maker", return_value=maker):
        await start_handlers._join_workspace(message, "bad")  # не проходит формат токена
        await start_handlers._join_workspace(message, "validformat1234")  # формат ок, но такого токена нет
    assert all("недействительно" in c.args[0] for c in message.answer.call_args_list)

    async with maker() as s0:
        _, _, invite = await _service_and_invite(maker, s0)
    with patch.object(start_handlers, "get_session_maker", return_value=maker):
        await start_handlers._join_workspace(_tg_message(555000502), invite.token)
        again = _tg_message(555000502)
        await start_handlers._join_workspace(again, invite.token)
    assert "уже зарегистрированы" in again.answer.call_args.args[0]


# ── Публичные эндпоинты для экрана регистрации ───────────────────────────────
async def test_registration_options_reflect_flag(client):
    off = await client.get("/auth/registration-options")
    assert off.status_code == 200 and off.json() == {"company_registration_enabled": False}
    with patch("src.services.workspace_service.ALLOW_COMPANY_REGISTRATION", True):
        on = await client.get("/auth/registration-options")
    assert on.json() == {"company_registration_enabled": True}


async def test_invite_preview_returns_company_name_without_auth(client, maker):
    _, admin = await _make_company(maker, "Ромашка")
    invite = await _new_invite(client, await _headers(client, admin))
    resp = await client.get(f"/auth/invite/{invite['token']}")
    assert resp.status_code == 200 and resp.json() == {"company_name": "Ромашка"}


async def test_invite_preview_rejects_revoked_expired_and_unknown_identically(client, maker):
    _, admin = await _make_company(maker, "A")
    h = await _headers(client, admin)
    revoked = await _new_invite(client, h)
    await client.delete(f"/api/workspace/invites/{revoked['id']}", headers=h)
    expired = await _new_invite(client, h)
    async with maker() as s:
        await s.execute(
            update(WorkspaceInviteModel)
            .where(WorkspaceInviteModel.id == expired["id"])
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await s.commit()

    bodies = []
    for token in (revoked["token"], expired["token"], "does-not-exist-123"):
        resp = await client.get(f"/auth/invite/{token}")
        assert resp.status_code == 400
        bodies.append(resp.json())
    assert bodies[0] == bodies[1] == bodies[2]  # по ответу не отличить «истекло» от «не было»


async def test_register_returns_login_that_can_be_used_to_sign_in_again(client, maker):
    """Логин отличается от username («Иван Петров» → petrov.i) и нигде больше не показывается —
    без него в ответе человек не смог бы войти повторно."""
    _, admin = await _make_company(maker, "A")
    invite = await _new_invite(client, await _headers(client, admin))
    resp = await client.post(
        "/auth/register", json={"username": "Иван Петров", "password": PASSWORD, "invite_token": invite["token"]}
    )
    assert resp.status_code == 201
    login = resp.json()["login"]
    assert login and login != "Иван Петров"

    again = await client.post("/auth/login", json={"username": login, "password": PASSWORD})
    assert again.status_code == 200
