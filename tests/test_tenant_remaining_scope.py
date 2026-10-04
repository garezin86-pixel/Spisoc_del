"""Остатки изоляции workspace: контекст бота, админ-панель бота, логины, WebSocket, iCal, ключи вложений."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.handlers import admin as admin_handlers
from src.bot.middlewares.workspace_context import WorkspaceContextMiddleware
from src.core.security import hash_password
from src.db.tenant_scope import current_workspace_id, workspace_context
from src.models import GroupModel, SpisokModel, UserModel
from src.models.workspace import WorkspaceModel
from src.repositories.calendar_repository import CalendarRepository
from src.repositories.users_repository import UserRepository
from src.services.calendar_service import CalendarService
from src.services.local_storage_service import LocalStorageService
from src.services.login_service import generate_unique_login
from src.services.storage_service import R2StorageService

pytestmark = pytest.mark.asyncio


@pytest.fixture
def maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _user(name: str, ws_id: int, *, tg: int | None = None, role: str = "user", login: str | None = None, **kw):
    return UserModel(
        username=name,
        login=login or f"{name}_{uuid.uuid4().hex[:6]}",
        password_hash=hash_password("password123"),
        workspace_id=ws_id,
        telegram_id=tg,
        role=role,
        **kw,
    )


@pytest.fixture
async def world(maker):
    """Две компании: в каждой админ с telegram_id и по одному обычному пользователю."""
    async with maker() as s:
        a = WorkspaceModel(name="A", slug=f"a-{uuid.uuid4().hex[:6]}")
        b = WorkspaceModel(name="B", slug=f"b-{uuid.uuid4().hex[:6]}")
        s.add_all([a, b])
        await s.commit()
        base = int(uuid.uuid4().int % 10**9) * 10
        admin_a, admin_b = (
            _user("admin_a", a.id, tg=base + 1, role="admin"),
            _user("admin_b", b.id, tg=base + 2, role="admin"),
        )
        emp_a, emp_b = _user("emp_a", a.id, tg=base + 3), _user("emp_b", b.id, tg=base + 4)
        s.add_all([admin_a, admin_b, emp_a, emp_b])
        await s.commit()
        return dict(
            a=a.id,
            b=b.id,
            admin_a=admin_a.id,
            admin_b=admin_b.id,
            emp_a=emp_a.id,
            emp_b=emp_b.id,
            tg_admin_a=base + 1,
            tg_admin_b=base + 2,
            tg_emp_b=base + 4,
        )


# ── Контекст workspace ───────────────────────────────────────────────────────
async def test_context_scopes_reads_and_autofills_writes(maker, world):
    with workspace_context(world["a"]):
        async with maker() as s:  # сессия открыта САМИМ кодом, без set_session_workspace
            names = {u.username for u in (await s.scalars(select(UserModel))).all()}
            assert names == {"admin_a", "emp_a"}
            g = GroupModel(name="G")
            s.add(g)
            await s.commit()
            assert g.workspace_id == world["a"]
    assert current_workspace_id() is None  # после блока контекст сброшен
    async with maker() as s:  # вне контекста — прежнее поведение, видны все
        assert len((await s.scalars(select(UserModel))).all()) == 4


async def test_context_is_inherited_by_child_tasks(maker, world):
    """Фоновые задачи, запущенные из хендлера (create_task), остаются в компании хендлера."""

    async def background() -> set[str]:
        async with maker() as s:
            return {u.username for u in (await s.scalars(select(UserModel))).all()}

    with workspace_context(world["b"]):
        names = await asyncio.create_task(background())
    assert names == {"admin_b", "emp_b"}


# ── Middleware бота ──────────────────────────────────────────────────────────
async def test_middleware_binds_update_to_senders_workspace(maker, world):
    seen = {}

    async def handler(event, data):
        seen["ws"] = current_workspace_id()
        async with maker() as s:
            seen["n_users"] = len((await s.scalars(select(UserModel))).all())
        return "ok"

    tg_user = MagicMock(id=world["tg_admin_b"])
    with patch("src.bot.middlewares.workspace_context.get_session_maker", return_value=maker):
        result = await WorkspaceContextMiddleware()(handler, MagicMock(), {"event_from_user": tg_user})

    assert result == "ok" and seen == {"ws": world["b"], "n_users": 2}
    assert current_workspace_id() is None


async def test_middleware_leaves_unregistered_sender_unscoped(maker, world):
    seen = {}

    async def handler(event, data):
        seen["ws"] = current_workspace_id()

    with patch("src.bot.middlewares.workspace_context.get_session_maker", return_value=maker):
        await WorkspaceContextMiddleware()(handler, MagicMock(), {"event_from_user": MagicMock(id=999_999_999_999)})
        await WorkspaceContextMiddleware()(handler, MagicMock(), {})  # апдейт без отправителя
    assert seen["ws"] is None


# ── Админ-панель бота ────────────────────────────────────────────────────────
def _tg_message(text: str, tg_id: int):
    msg = AsyncMock()
    msg.text = text
    msg.from_user = MagicMock(id=tg_id)
    return msg


async def _as_bot_update(maker, tg_id, coro_factory):
    with patch("src.bot.middlewares.workspace_context.get_session_maker", return_value=maker):
        return await WorkspaceContextMiddleware()(
            lambda event, data: coro_factory(), MagicMock(), {"event_from_user": MagicMock(id=tg_id)}
        )


async def test_bot_admin_user_list_shows_only_own_company(maker, world):
    msg = _tg_message("📋 Список пользователей", world["tg_admin_a"])
    with patch.object(admin_handlers, "get_session_maker", return_value=maker):
        await _as_bot_update(maker, world["tg_admin_a"], lambda: admin_handlers.list_users(msg))
    text = msg.answer.call_args.args[0]
    assert "admin_a" in text and "emp_a" in text
    assert "admin_b" not in text and "emp_b" not in text


async def test_bot_admin_cannot_block_user_of_another_company(maker, world):
    msg = _tg_message(str(world["emp_b"]), world["tg_admin_a"])  # админ A вводит id сотрудника B
    state = AsyncMock()
    with patch.object(admin_handlers, "get_session_maker", return_value=maker):
        await _as_bot_update(maker, world["tg_admin_a"], lambda: admin_handlers.block_user(msg, state))
    assert "не найден" in msg.answer.call_args.args[0]
    async with maker() as s:
        assert (await s.get(UserModel, world["emp_b"])).is_active is True


async def test_bot_admin_creates_group_and_user_inside_own_company(maker, world):
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={"username": "Новый Сотрудник", "password": "secret123", "role": "user"})
    group_msg = _tg_message("Отдел продаж", world["tg_admin_b"])
    user_msg = _tg_message("⏭ Пропустить", world["tg_admin_b"])
    with patch.object(admin_handlers, "get_session_maker", return_value=maker):
        await _as_bot_update(maker, world["tg_admin_b"], lambda: admin_handlers.create_group(group_msg, state))
        await _as_bot_update(maker, world["tg_admin_b"], lambda: admin_handlers.add_user_telegram_id(user_msg, state))

    async with maker() as s:
        group = await s.scalar(select(GroupModel).where(GroupModel.name == "Отдел продаж"))
        new_user = await s.scalar(select(UserModel).where(UserModel.username == "Новый Сотрудник"))
    assert group.workspace_id == world["b"]
    assert new_user.workspace_id == world["b"] and new_user.login  # login NOT NULL — раньше не задавался


async def test_bot_admin_add_user_with_taken_telegram_id_gets_friendly_error(maker, world):
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={"username": "Дубль Тг", "password": "secret123", "role": "user"})
    msg = _tg_message(str(world["tg_emp_b"]), world["tg_admin_a"])  # telegram_id сотрудника другой компании
    with patch.object(admin_handlers, "get_session_maker", return_value=maker):
        await _as_bot_update(maker, world["tg_admin_a"], lambda: admin_handlers.add_user_telegram_id(msg, state))
    assert "уже привязан" in msg.answer.call_args.args[0]


# ── Логины глобально уникальны даже в привязанной сессии ─────────────────────
async def test_generated_login_avoids_logins_of_other_companies(maker):
    async with maker() as s:
        a = WorkspaceModel(name="A", slug=f"a-{uuid.uuid4().hex[:6]}")
        b = WorkspaceModel(name="B", slug=f"b-{uuid.uuid4().hex[:6]}")
        s.add_all([a, b])
        await s.commit()
        s.add(_user("Иван Петров", a.id, login="ivan.p"))
        await s.commit()
        ws_b = b.id
    with workspace_context(ws_b):  # админ компании B заводит такого же «Ивана Петрова»
        async with maker() as s:
            login = await generate_unique_login("Иван Петров", UserRepository(s))
    assert login != "ivan.p" and login.startswith("ivan.p")


# ── WebSocket: заблокированный пользователь не подключается ──────────────────
def test_websocket_rejects_inactive_user():
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from src.routers.ws_router import router as ws_router

    uow = MagicMock()
    uow.users.get_by_id = AsyncMock(return_value=MagicMock(id=1, is_active=False, workspace_id=1))

    @asynccontextmanager
    async def fake_uow(*a, **k):
        yield uow

    app = FastAPI()
    app.include_router(ws_router, prefix="/api")
    with (
        patch("src.routers.ws_router.decode_access_token", return_value={"sub": "1"}),
        patch("src.routers.ws_router.UnitOfWork", side_effect=fake_uow),
        patch("src.routers.ws_router.get_session_maker", return_value=MagicMock()),
        TestClient(app) as client,
    ):
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/ws?token=x"):
                pass
    assert exc.value.code == 4001


# ── iCal-фид ────────────────────────────────────────────────────────────────
async def _feed_owner(maker, *, active: bool):
    async with maker() as s:
        ws = WorkspaceModel(name="A", slug=f"a-{uuid.uuid4().hex[:6]}")
        s.add(ws)
        await s.commit()
        owner = _user("owner", ws.id, calendar_feed_token=f"tok-{uuid.uuid4().hex}", is_active=active)
        s.add(owner)
        await s.commit()
        s.add(
            SpisokModel(
                title="Секретная задача",
                author_id=owner.id,
                user_id=owner.id,
                workspace_id=ws.id,
                deadline=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        await s.commit()
        return owner.calendar_feed_token


async def test_calendar_feed_of_blocked_user_stops_working(maker):
    token = await _feed_owner(maker, active=False)
    async with maker() as s:
        assert await CalendarService(CalendarRepository(s)).build_feed_for_token(token) is None


async def test_calendar_feed_of_active_user_still_works(maker):
    token = await _feed_owner(maker, active=True)
    async with maker() as s:
        ics = await CalendarService(CalendarRepository(s)).build_feed_for_token(token)
    assert ics and "Секретная задача" in ics


# ── Ключи вложений ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("storage_cls,prefix", [(LocalStorageService, ""), (R2StorageService, "attachments/")])
def test_storage_key_groups_files_by_company(storage_cls, prefix):
    key = storage_cls.build_key(42, "photo.jpg", workspace_id=3)
    assert key.startswith(f"{prefix}ws-3/42/") and key.endswith("-photo.jpg")


@pytest.mark.parametrize("storage_cls,prefix", [(LocalStorageService, ""), (R2StorageService, "attachments/")])
def test_storage_key_without_workspace_keeps_old_layout(storage_cls, prefix):
    key = storage_cls.build_key(42, "photo.jpg")
    assert key.startswith(f"{prefix}42/") and "ws-" not in key
