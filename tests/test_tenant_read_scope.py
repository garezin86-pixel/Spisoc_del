"""Чтение/изменение данных изолировано по workspace (src/db/tenant_scope.py)."""

import uuid

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.security import hash_password
from src.db.tenant_scope import set_session_workspace
from src.models import SpisokModel, UserModel
from src.models.project import ProjectModel
from src.models.workspace import WorkspaceModel
from src.repositories.users_repository import UserRepository


def _user(name: str, ws_id: int) -> UserModel:
    return UserModel(
        username=name,
        login=f"{name}_{uuid.uuid4().hex[:6]}",
        password_hash=hash_password("password123"),
        workspace_id=ws_id,
    )


@pytest.fixture
async def two_workspaces(engine):
    """Два workspace; в каждом пользователь «ivan» (username уникален только внутри workspace)
    и задача. Данные создаются «платформенной» сессией без привязки к workspace."""
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        a = WorkspaceModel(name="A", slug=f"a-{uuid.uuid4().hex[:6]}")
        b = WorkspaceModel(name="B", slug=f"b-{uuid.uuid4().hex[:6]}")
        s.add_all([a, b])
        await s.commit()
        ua, ub = _user("ivan", a.id), _user("ivan", b.id)
        s.add_all([ua, ub])
        await s.commit()
        ta = SpisokModel(title="task A", author_id=ua.id, workspace_id=a.id)
        tb = SpisokModel(title="task B", author_id=ub.id, workspace_id=b.id)
        s.add_all([ta, tb])
        await s.commit()
        ids = dict(a=a.id, b=b.id, ua=ua.id, ub=ub.id, ta=ta.id, tb=tb.id)
    return maker, ids


def _scoped(maker, ws_id):
    s = maker()
    set_session_workspace(s.sync_session, ws_id)
    return s


async def test_select_by_id_cannot_cross_workspace(two_workspaces):
    maker, ids = two_workspaces
    async with _scoped(maker, ids["a"]) as s:
        repo = UserRepository(s)
        assert await repo.get_by_id(ids["ua"]) is not None
        assert await repo.get_by_id(ids["ub"]) is None  # чужой пользователь по id
        assert await s.get(UserModel, ids["ub"]) is None  # session.get тоже идёт в SQL
        assert (await s.execute(select(SpisokModel).where(SpisokModel.id == ids["tb"]))).first() is None


async def test_username_lookup_is_scoped(two_workspaces):
    maker, ids = two_workspaces
    async with _scoped(maker, ids["a"]) as s:
        user = await UserRepository(s).get_by_username("ivan")
        assert user is not None and user.id == ids["ua"]
    async with _scoped(maker, ids["b"]) as s:
        user = await UserRepository(s).get_by_username("ivan")
        assert user is not None and user.id == ids["ub"]


async def test_get_all_and_count_are_scoped(two_workspaces):
    maker, ids = two_workspaces
    async with _scoped(maker, ids["a"]) as s:
        repo = UserRepository(s)
        assert [u.id for u in await repo.get_all()] == [ids["ua"]]
        assert await repo.get_total_count(UserModel) == 1
        assert await s.scalar(select(func.count()).select_from(UserModel)) == 1


async def test_join_and_alias_are_scoped(two_workspaces):
    maker, ids = two_workspaces
    async with _scoped(maker, ids["a"]) as s:
        rows = (
            await s.execute(
                select(SpisokModel.title, UserModel.username).join(UserModel, UserModel.id == SpisokModel.author_id)
            )
        ).all()
        assert [r.title for r in rows] == ["task A"]


async def test_update_and_delete_cannot_touch_other_workspace(two_workspaces):
    maker, ids = two_workspaces
    async with _scoped(maker, ids["a"]) as s:
        await s.execute(update(UserModel).where(UserModel.username == "ivan").values(role="manager"))
        await s.execute(delete(SpisokModel).where(SpisokModel.id == ids["tb"]))
        await s.commit()
    async with maker() as s:  # платформенная сессия видит всё
        roles = {u.id: u.role for u in (await s.execute(select(UserModel))).scalars()}
        assert roles[ids["ua"]] == "manager"
        assert roles[ids["ub"]] != "manager"
        assert (await s.get(SpisokModel, ids["tb"])) is not None


async def test_session_without_workspace_is_unscoped(two_workspaces):
    """Документируем fail-open: логин/бот/планировщик пока видят всё."""
    maker, ids = two_workspaces
    async with maker() as s:
        assert await s.get(UserModel, ids["ua"]) is not None
        assert await s.get(UserModel, ids["ub"]) is not None


async def test_autofill_and_scope_work_together(two_workspaces):
    maker, ids = two_workspaces
    async with _scoped(maker, ids["b"]) as s:
        p = ProjectModel(name="P", owner_id=ids["ub"])
        s.add(p)
        await s.commit()
        assert p.workspace_id == ids["b"]
    async with _scoped(maker, ids["a"]) as s:
        assert (await s.execute(select(ProjectModel))).first() is None
