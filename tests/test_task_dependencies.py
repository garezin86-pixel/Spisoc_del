# tests/test_task_dependencies.py
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.enums import TaskStatus
from src.models.task import SpisokModel
from src.repositories.groups_repository import GroupRepository
from src.repositories.tag_repository import TagRepository
from src.repositories.task_dependency_repository import TaskDependencyRepository
from src.repositories.task_repository import TaskRepository
from src.repositories.users_repository import UserRepository
from src.services.task_service import TaskService
from tests.conftest import make_user

pytestmark = pytest.mark.asyncio


def build_service(session) -> TaskService:
    return TaskService(
        task_repo=TaskRepository(session),
        user_repo=UserRepository(session),
        group_repo=GroupRepository(session),
        tag_repo=TagRepository(session),
        session=session,
    )


async def _task(session, *, author, title="Задача", status=TaskStatus.todo):
    task = SpisokModel(title=title, author_id=author.id, status=status)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


class TestAddDependency:
    async def test_add_dependency_succeeds(self, session):
        author = await make_user(session)
        service = build_service(session)
        blocked = await _task(session, author=author, title="Заблокированная")
        blocker = await _task(session, author=author, title="Блокер")

        await service.add_dependency(blocked.id, blocker.id, author)

        deps = await service.get_dependencies(blocked.id, author)
        assert [b.id for b in deps.blockers] == [blocker.id]

    async def test_cannot_block_task_by_itself(self, session):
        author = await make_user(session)
        service = build_service(session)
        task = await _task(session, author=author)

        with pytest.raises(Exception) as exc_info:
            await service.add_dependency(task.id, task.id, author)
        assert getattr(exc_info.value, "status_code", None) == 400

    async def test_duplicate_dependency_rejected(self, session):
        author = await make_user(session)
        service = build_service(session)
        blocked = await _task(session, author=author)
        blocker = await _task(session, author=author)
        await service.add_dependency(blocked.id, blocker.id, author)

        with pytest.raises(Exception) as exc_info:
            await service.add_dependency(blocked.id, blocker.id, author)
        assert getattr(exc_info.value, "status_code", None) == 400

    async def test_direct_cycle_rejected(self, session):
        """A блокирует B, затем попытка "B блокирует A" — прямой цикл."""
        author = await make_user(session)
        service = build_service(session)
        a = await _task(session, author=author, title="A")
        b = await _task(session, author=author, title="B")
        await service.add_dependency(b.id, a.id, author)  # A блокирует B

        with pytest.raises(Exception) as exc_info:
            await service.add_dependency(a.id, b.id, author)  # B блокирует A — цикл
        assert getattr(exc_info.value, "status_code", None) == 400

    async def test_transitive_cycle_rejected(self, session):
        """A блокирует B, B блокирует C — попытка "C блокирует A" замкнула бы цикл."""
        author = await make_user(session)
        service = build_service(session)
        a = await _task(session, author=author, title="A")
        b = await _task(session, author=author, title="B")
        c = await _task(session, author=author, title="C")
        await service.add_dependency(b.id, a.id, author)  # A блокирует B
        await service.add_dependency(c.id, b.id, author)  # B блокирует C

        with pytest.raises(Exception) as exc_info:
            await service.add_dependency(a.id, c.id, author)  # C блокирует A — транзитивный цикл
        assert getattr(exc_info.value, "status_code", None) == 400

    async def test_diamond_shape_is_allowed(self, session):
        """A блокирует B и C, оба блокируют D — не цикл, допустимая форма графа."""
        author = await make_user(session)
        service = build_service(session)
        a = await _task(session, author=author, title="A")
        b = await _task(session, author=author, title="B")
        c = await _task(session, author=author, title="C")
        d = await _task(session, author=author, title="D")
        await service.add_dependency(b.id, a.id, author)
        await service.add_dependency(c.id, a.id, author)
        await service.add_dependency(d.id, b.id, author)

        await service.add_dependency(d.id, c.id, author)  # не должно упасть

        deps = await service.get_dependencies(d.id, author)
        assert {x.id for x in deps.blockers} == {b.id, c.id}

    async def test_nonexistent_task_returns_404(self, session):
        author = await make_user(session)
        service = build_service(session)
        task = await _task(session, author=author)

        with pytest.raises(Exception) as exc_info:
            await service.add_dependency(task.id, 999999, author)
        assert getattr(exc_info.value, "status_code", None) == 404

    async def test_no_access_to_foreign_task_rejected(self, session):
        owner = await make_user(session)
        stranger = await make_user(session)
        service = build_service(session)
        blocked = await _task(session, author=owner)
        blocker = await _task(session, author=owner)

        with pytest.raises(Exception) as exc_info:
            await service.add_dependency(blocked.id, blocker.id, stranger)
        assert getattr(exc_info.value, "status_code", None) == 403


class TestRemoveDependency:
    async def test_remove_dependency_succeeds(self, session):
        author = await make_user(session)
        service = build_service(session)
        blocked = await _task(session, author=author)
        blocker = await _task(session, author=author)
        await service.add_dependency(blocked.id, blocker.id, author)

        await service.remove_dependency(blocked.id, blocker.id, author)

        deps = await service.get_dependencies(blocked.id, author)
        assert deps.blockers == []

    async def test_remove_nonexistent_dependency_404(self, session):
        author = await make_user(session)
        service = build_service(session)
        blocked = await _task(session, author=author)
        blocker = await _task(session, author=author)

        with pytest.raises(Exception) as exc_info:
            await service.remove_dependency(blocked.id, blocker.id, author)
        assert getattr(exc_info.value, "status_code", None) == 404


class TestClosingBlockedTask:
    async def test_cannot_close_task_with_open_blocker(self, session):
        author = await make_user(session)
        service = build_service(session)
        blocked = await _task(session, author=author, title="Заблокированная")
        blocker = await _task(session, author=author, title="Блокер", status=TaskStatus.todo)
        await service.add_dependency(blocked.id, blocker.id, author)

        with pytest.raises(Exception) as exc_info:
            await service.update_task_status(blocked.id, TaskStatus.done, author)
        assert getattr(exc_info.value, "status_code", None) == 409
        assert str(blocker.id) in str(exc_info.value.detail)

    async def test_can_close_task_after_blocker_done(self, session):
        author = await make_user(session)
        service = build_service(session)
        blocked = await _task(session, author=author)
        blocker = await _task(session, author=author, status=TaskStatus.todo)
        await service.add_dependency(blocked.id, blocker.id, author)

        await service.update_task_status(blocker.id, TaskStatus.done, author)
        result = await service.update_task_status(blocked.id, TaskStatus.done, author)

        assert result.status == TaskStatus.done

    async def test_can_move_blocked_task_to_non_done_status(self, session):
        """Блокеры мешают закрыть, но не мешают двигать по канбану до done."""
        author = await make_user(session)
        service = build_service(session)
        blocked = await _task(session, author=author, status=TaskStatus.todo)
        blocker = await _task(session, author=author, status=TaskStatus.todo)
        await service.add_dependency(blocked.id, blocker.id, author)

        result = await service.update_task_status(blocked.id, TaskStatus.in_progress, author)

        assert result.status == TaskStatus.in_progress

    async def test_update_task_generic_endpoint_also_blocked(self, session):
        """Тот же guard должен работать и через update_task (не только update_task_status)."""
        from src.schemas.task import SpisokUpdate

        author = await make_user(session)
        service = build_service(session)
        blocked = await _task(session, author=author)
        blocker = await _task(session, author=author, status=TaskStatus.todo)
        await service.add_dependency(blocked.id, blocker.id, author)

        with pytest.raises(Exception) as exc_info:
            await service.update_task(blocked.id, SpisokUpdate(status=TaskStatus.done), author)
        assert getattr(exc_info.value, "status_code", None) == 409

    async def test_task_with_no_dependencies_closes_normally(self, session):
        author = await make_user(session)
        service = build_service(session)
        task = await _task(session, author=author)

        result = await service.update_task_status(task.id, TaskStatus.done, author)

        assert result.status == TaskStatus.done

    async def test_reopening_done_task_not_affected_by_blockers(self, session):
        """Guard срабатывает только на переход В done, не из него."""
        author = await make_user(session)
        service = build_service(session)
        blocked = await _task(session, author=author, status=TaskStatus.done)
        blocker = await _task(session, author=author, status=TaskStatus.todo)
        # Добавляем блокер уже ПОСЛЕ того, как blocked закрыта — реалистичный
        # сценарий: кто-то повесил зависимость на уже готовую задачу.
        await service.add_dependency(blocked.id, blocker.id, author)

        result = await service.update_task_status(blocked.id, TaskStatus.in_progress, author)

        assert result.status == TaskStatus.in_progress


class TestTaskDependencyRepositoryCycles:
    async def test_would_create_cycle_false_for_empty_graph(self, session):
        repo = TaskDependencyRepository(session)
        assert await repo.would_create_cycle(1, 2) is False

    async def test_would_create_cycle_true_for_direct_reverse(self, session):
        author = await make_user(session)
        a = await _task(session, author=author)
        b = await _task(session, author=author)
        repo = TaskDependencyRepository(session)
        await repo.add(a.id, b.id)  # a блокирует b

        assert await repo.would_create_cycle(b.id, a.id) is True  # b блокирует a — цикл


class TestTaskDependencyEndToEndViaRealApp:
    async def _login(self, client, engine, username: str) -> str:
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username=username, password="pass123")
        resp = await client.post("/auth/login", json={"username": username, "password": "pass123"})
        assert resp.status_code == 200
        return resp.json()["access_token"]

    async def test_full_flow_via_http(self, client, engine):
        username = f"dep_{uuid.uuid4().hex[:6]}"
        jwt_token = await self._login(client, engine, username)
        headers = {"Authorization": f"Bearer {jwt_token}"}

        blocked_resp = await client.post("/api/tasks", json={"title": "Заблокированная"}, headers=headers)
        blocker_resp = await client.post("/api/tasks", json={"title": "Блокер"}, headers=headers)
        blocked_id = blocked_resp.json()["id"]
        blocker_id = blocker_resp.json()["id"]

        add_resp = await client.post(
            f"/api/tasks/{blocked_id}/dependencies", json={"blocker_task_id": blocker_id}, headers=headers
        )
        assert add_resp.status_code == 201

        close_resp = await client.patch(f"/api/tasks/{blocked_id}/status", json={"status": "done"}, headers=headers)
        assert close_resp.status_code == 409

        deps_resp = await client.get(f"/api/tasks/{blocked_id}/dependencies", headers=headers)
        assert deps_resp.status_code == 200
        assert deps_resp.json()["blockers"][0]["id"] == blocker_id

        await client.patch(f"/api/tasks/{blocker_id}/status", json={"status": "done"}, headers=headers)
        close_resp2 = await client.patch(f"/api/tasks/{blocked_id}/status", json={"status": "done"}, headers=headers)
        assert close_resp2.status_code == 200

        remove_resp = await client.delete(f"/api/tasks/{blocked_id}/dependencies/{blocker_id}", headers=headers)
        assert remove_resp.status_code == 200
