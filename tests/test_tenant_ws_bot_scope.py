"""Изоляция workspace для WebSocket, Telegram-бота и фоновых уведомлений."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.security import hash_password
from src.core.ws_manager import WSManager
from src.db.unit_of_work import UnitOfWork
from src.models import SpisokModel, UserModel
from src.models.comment import CommentModel
from src.models.workspace import WorkspaceModel
from src.repositories.users_repository import UserRepository
from src.services.notifications import notify_comment_added
from tests.test_notifications import NotificationSettings, unique_tg_id

pytestmark = pytest.mark.asyncio


def _user(name: str, ws_id: int, tg: int | None = None) -> UserModel:
    return UserModel(
        username=name,
        login=f"{name}_{uuid.uuid4().hex[:6]}",
        password_hash=hash_password("password123"),
        workspace_id=ws_id,
        telegram_id=tg,
    )


def _settings(user_id: int) -> NotificationSettings:
    return NotificationSettings(user_id=user_id)


@pytest.fixture
async def world(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        a = WorkspaceModel(name="A", slug=f"a-{uuid.uuid4().hex[:6]}")
        b = WorkspaceModel(name="B", slug=f"b-{uuid.uuid4().hex[:6]}")
        s.add_all([a, b])
        await s.commit()
        tg_a, tg_b = unique_tg_id(), unique_tg_id()
        ua = _user("author_a", a.id, tg_a)
        ub = _user("petya", b.id, tg_b)  # пользователь ДРУГОЙ компании
        s.add_all([ua, ub])
        await s.commit()
        s.add_all([_settings(ua.id), _settings(ub.id)])
        task = SpisokModel(title="t", author_id=ua.id, user_id=ua.id, workspace_id=a.id)
        s.add(task)
        await s.commit()
        return maker, dict(a=a.id, b=b.id, ua=ua.id, ub=ub.id, tg_a=tg_a, tg_b=tg_b, task=task.id)


# ── WebSocket ────────────────────────────────────────────────────────────────
async def _connect(mgr: WSManager, user_id: int, ws_id: int | None):
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    await mgr.connect(ws, user_id, ws_id)
    return ws


async def test_broadcast_all_reaches_only_same_workspace():
    mgr = WSManager()
    a1 = await _connect(mgr, 1, 10)
    a2 = await _connect(mgr, 2, 10)
    b1 = await _connect(mgr, 3, 20)
    await mgr.broadcast_all("chat_message", {"x": 1}, workspace_id=10)
    a1.send_text.assert_awaited_once()
    a2.send_text.assert_awaited_once()
    b1.send_text.assert_not_awaited()


async def test_broadcast_all_forgets_workspace_after_disconnect():
    mgr = WSManager()
    ws = await _connect(mgr, 1, 10)
    mgr.disconnect(ws, 1)
    assert 1 not in mgr._workspace_of


async def test_broadcast_all_requires_explicit_workspace():
    with pytest.raises(TypeError):
        await WSManager().broadcast_all("e", {})  # type: ignore[call-arg]


# ── Telegram-бот ─────────────────────────────────────────────────────────────
async def test_get_by_telegram_id_binds_session_to_users_workspace(world):
    maker, ids = world
    async with maker() as s:
        repo = UserRepository(s)
        user = await repo.get_by_telegram_id(ids["tg_a"])
        assert user is not None and user.workspace_id == ids["a"]
        # дальше сессия видит только компанию A
        assert [u.id for u in await repo.get_all()] == [ids["ua"]]
        assert await repo.get_by_id(ids["ub"]) is None


async def test_get_by_telegram_id_unknown_user_leaves_session_unscoped(world):
    maker, ids = world
    async with maker() as s:
        repo = UserRepository(s)
        assert await repo.get_by_telegram_id(999_999_999_999) is None
        assert len(await repo.get_all()) == 2


async def test_unit_of_work_workspace_param_and_set_workspace(world):
    maker, ids = world
    async with UnitOfWork(maker, workspace_id=ids["b"]) as uow:
        assert [u.id for u in await uow.users.get_all()] == [ids["ub"]]
    async with UnitOfWork(maker) as uow:
        assert len(await uow.users.get_all()) == 2
        uow.set_workspace(ids["a"])
        assert [u.id for u in await uow.users.get_all()] == [ids["ua"]]


# ── Фоновые уведомления ──────────────────────────────────────────────────────
async def test_mention_does_not_notify_user_from_other_workspace(world, engine):
    maker, ids = world
    async with maker() as s:
        comment = CommentModel(content="глянь @petya", task_id=ids["task"], user_id=ids["ua"], workspace_id=ids["a"])
        s.add(comment)
        await s.commit()
        comment_id = comment.id

    with (
        patch("src.services.notifications.get_bot") as get_bot,
        patch("src.services.notifications.get_session_maker", return_value=maker),
    ):
        bot = AsyncMock()
        get_bot.return_value = bot
        await notify_comment_added(comment_id)

    sent_to = {c.kwargs["chat_id"] for c in bot.send_message.call_args_list}
    assert ids["tg_b"] not in sent_to
