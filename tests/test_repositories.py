"""
Примеры тестов с использованием mock-репозиториев.
Никакой БД не нужно — всё в памяти.
"""

from unittest.mock import MagicMock

import pytest

from src.models.group import GroupModel
from src.models.task import SpisokModel, TaskStatus
from src.models.user import UserModel
from src.repositories.mock_repositories import (
    MockGroupRepository,
    MockStatsRepository,
    MockTaskRepository,
    MockUserRepository,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_user(id: int, username: str, role: str = "user", is_active: bool = True) -> UserModel:
    u = MagicMock(spec=UserModel)
    u.id = id
    u.username = username
    u.role = role
    u.is_active = is_active
    u.telegram_id = id * 100
    return u


def make_task(
    id: int,
    user_id: int,
    author_id: int,
    status: TaskStatus = TaskStatus.todo,
) -> SpisokModel:
    t = MagicMock(spec=SpisokModel)
    t.id = id
    t.user_id = user_id
    t.author_id = author_id
    t.status = status

    from datetime import datetime

    t.created_at = datetime.now()

    return t


def make_group(id: int, name: str) -> GroupModel:
    g = MagicMock(spec=GroupModel)
    g.id = id
    g.name = name
    g.users = []
    return g


# ---------------------------------------------------------------------------
# UserRepository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_create_and_get():
    repo = MockUserRepository()
    user = make_user(id=0, username="alice")

    created = await repo.create(user)
    assert created.id == 1

    fetched = await repo.get_by_id(1)
    assert fetched is not None
    assert fetched.username == "alice"


@pytest.mark.asyncio
async def test_user_get_by_username():
    repo = MockUserRepository(users=[make_user(1, "bob")])
    user = await repo.get_by_username("bob")
    assert user is not None
    assert user.username == "bob"


@pytest.mark.asyncio
async def test_user_set_role():
    user = make_user(1, "charlie", role="user")
    repo = MockUserRepository(users=[user])

    await repo.set_role("charlie", "admin")

    admin = await repo.get_admin_by_username("charlie")
    assert admin is not None


@pytest.mark.asyncio
async def test_user_delete():
    user = make_user(1, "dave")
    repo = MockUserRepository(users=[user])

    await repo.delete(user)

    assert await repo.get_by_id(1) is None
    assert await repo.get_all() == []


@pytest.mark.asyncio
async def test_users_limit():
    users = [make_user(i, f"user_{i}") for i in range(1, 6)]
    repo = MockUserRepository(users=users)

    page = await repo.get_users_limit(limit=2, offset=2)
    assert len(page) == 2
    assert page[0].username == "user_3"


# ---------------------------------------------------------------------------
# TaskRepository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_create_and_delete():
    repo = MockTaskRepository()
    task = make_task(id=0, user_id=1, author_id=2)

    created = await repo.create(task)
    assert created.id == 1

    await repo.delete(created)
    assert await repo.get_by_id(1) is None


@pytest.mark.asyncio
async def test_get_user_tasks_by_status():
    tasks = [
        make_task(1, user_id=1, author_id=2, status=TaskStatus.done),
        make_task(2, user_id=1, author_id=2, status=TaskStatus.todo),
        make_task(3, user_id=1, author_id=2, status=TaskStatus.todo),
    ]

    repo = MockTaskRepository(tasks=tasks)

    todo = await repo.get_user_tasks_by_status(
        user_id=1,
        status=TaskStatus.todo,
    )
    assert len(todo) == 2

    done = await repo.get_user_tasks_by_status(
        user_id=1,
        status=TaskStatus.done,
    )
    assert len(done) == 1


@pytest.mark.asyncio
async def test_assigned_tasks_stats():
    tasks = [
        make_task(1, user_id=5, author_id=1, status=TaskStatus.done),
        make_task(2, user_id=5, author_id=1, status=TaskStatus.todo),
        make_task(3, user_id=5, author_id=1, status=TaskStatus.todo),
    ]

    repo = MockTaskRepository(tasks=tasks)

    stats = await repo.get_assigned_tasks(pk=5)

    assert stats.total == 3
    assert stats.done == 1
    assert stats.todo == 2


# ---------------------------------------------------------------------------
# GroupRepository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_create_and_add_user():
    group_repo = MockGroupRepository()
    group = make_group(id=0, name="dev-team")
    user = make_user(1, "eve")

    created_group = await group_repo.create(group)
    await group_repo.add_user_in_group(created_group, user)

    users = await group_repo.get_group_users(created_group.id)
    assert len(users) == 1
    assert users[0].username == "eve"


@pytest.mark.asyncio
async def test_group_remove_user():
    user = make_user(1, "frank")
    group = make_group(1, "ops")
    group.users = [user]

    repo = MockGroupRepository(groups=[group])
    await repo.delete_user_group(group, user)

    users = await repo.get_group_users(1)
    assert users == []


@pytest.mark.asyncio
async def test_user_groups():
    user = make_user(1, "grace")
    group1 = make_group(1, "alpha")
    group1.users = [user]
    group2 = make_group(2, "beta")
    group2.users = []

    repo = MockGroupRepository(groups=[group1, group2])
    groups = await repo.get_user_groups(user_id=1)
    assert len(groups) == 1
    assert groups[0].name == "alpha"


# ---------------------------------------------------------------------------
# StatsRepository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats():
    users = [
        make_user(1, "u1", role="admin", is_active=True),
        make_user(2, "u2", role="user", is_active=True),
        make_user(3, "u3", role="user", is_active=False),
    ]
    tasks = [
        make_task(1, 1, 2, status=TaskStatus.done),
        make_task(2, 1, 2, status=TaskStatus.todo),
    ]
    groups = [make_group(1, "g1"), make_group(2, "g2")]

    repo = MockStatsRepository(users=users, tasks=tasks, groups=groups)

    u_stats = await repo.get_users_stats()
    assert u_stats.total_users == 3
    assert u_stats.active_users == 2
    assert u_stats.admin_users == 1

    t_stats = await repo.get_tasks_stats()
    assert t_stats.total_tasks == 2
    assert t_stats.done_tasks == 1
    assert t_stats.pending_tasks == 1

    assert await repo.get_groups_count() == 2
    assert await repo.get_comments_count() == 0

    # check_connection не бросает исключений
    await repo.check_connection()
