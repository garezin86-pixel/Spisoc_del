# tests/test_bulk_actions.py
"""
Тесты TaskService.bulk_update_tasks и PATCH /tasks/bulk.

Ключевые инварианты, которые здесь проверяются:
  - задачи без доступа не прерывают всю операцию, а попадают в skipped
  - несуществующие/чужие id тоже попадают в skipped, а не роняют запрос
  - tag_id ДОБАВЛЯЕТ тег, а не заменяет список тегов
  - переход в done проставляет completed_at, выход из done — сбрасывает
  - user_id одновременно сбрасывает group_id (как в reassign_task)
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.tag import TagModel
from src.models.task import SpisokModel, TaskStatus
from src.repositories.groups_repository import GroupRepository
from src.repositories.tag_repository import TagRepository
from src.repositories.task_repository import TaskRepository
from src.repositories.users_repository import UserRepository
from src.schemas.task import BulkTaskUpdate
from src.services.task_service import TaskService
from tests.conftest import make_user


def build_service(session) -> TaskService:
    return TaskService(
        task_repo=TaskRepository(session),
        user_repo=UserRepository(session),
        group_repo=GroupRepository(session),
        tag_repo=TagRepository(session),
        session=session,
    )


async def make_task(session, author, **kwargs) -> SpisokModel:
    task = SpisokModel(title=kwargs.pop("title", "Задача"), author_id=author.id, **kwargs)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


class TestBulkUpdateService:
    @pytest.mark.asyncio
    async def test_status_updated_for_all_tasks(self, session):
        user = await make_user(session)
        t1 = await make_task(session, user, title="A", user_id=user.id)
        t2 = await make_task(session, user, title="B", user_id=user.id)
        service = build_service(session)

        result = await service.bulk_update_tasks(
            BulkTaskUpdate(task_ids=[t1.id, t2.id], status=TaskStatus.in_progress), user
        )

        assert result.updated == 2
        assert result.skipped == []
        await session.refresh(t1)
        await session.refresh(t2)
        assert t1.status == TaskStatus.in_progress
        assert t2.status == TaskStatus.in_progress

    @pytest.mark.asyncio
    async def test_priority_updated(self, session):
        user = await make_user(session)
        task = await make_task(session, user, title="A", user_id=user.id, priority="low")
        service = build_service(session)

        await service.bulk_update_tasks(BulkTaskUpdate(task_ids=[task.id], priority="critical"), user)

        await session.refresh(task)
        assert task.priority.value == "critical"

    @pytest.mark.asyncio
    async def test_moving_to_done_sets_completed_at(self, session):
        user = await make_user(session)
        task = await make_task(session, user, title="A", user_id=user.id, status=TaskStatus.todo)
        service = build_service(session)

        await service.bulk_update_tasks(BulkTaskUpdate(task_ids=[task.id], status=TaskStatus.done), user)

        await session.refresh(task)
        assert task.completed_at is not None

    @pytest.mark.asyncio
    async def test_moving_out_of_done_clears_completed_at(self, session):
        user = await make_user(session)
        task = await make_task(session, user, title="A", user_id=user.id, status=TaskStatus.done)
        service = build_service(session)

        await service.bulk_update_tasks(BulkTaskUpdate(task_ids=[task.id], status=TaskStatus.todo), user)

        await session.refresh(task)
        assert task.completed_at is None

    @pytest.mark.asyncio
    async def test_tag_added_not_replacing_existing_tags(self, session):
        user = await make_user(session)
        task = await make_task(session, user, title="A", user_id=user.id)
        existing_tag = TagModel(name="старый")
        new_tag = TagModel(name="новый")
        session.add_all([existing_tag, new_tag])
        await session.commit()
        await session.refresh(existing_tag)
        await session.refresh(new_tag)
        task.tags.append(existing_tag)
        await session.commit()

        service = build_service(session)
        await service.bulk_update_tasks(BulkTaskUpdate(task_ids=[task.id], tag_id=new_tag.id), user)

        await session.refresh(task)
        tag_names = {t.name for t in task.tags}
        assert tag_names == {"старый", "новый"}

    @pytest.mark.asyncio
    async def test_tag_not_duplicated_if_already_present(self, session):
        user = await make_user(session)
        task = await make_task(session, user, title="A", user_id=user.id)
        tag = TagModel(name="важное")
        session.add(tag)
        await session.commit()
        await session.refresh(tag)
        task.tags.append(tag)
        await session.commit()

        service = build_service(session)
        await service.bulk_update_tasks(BulkTaskUpdate(task_ids=[task.id], tag_id=tag.id), user)

        await session.refresh(task)
        assert len(task.tags) == 1

    @pytest.mark.asyncio
    async def test_reassign_user_clears_group(self, session):
        from src.models.group import GroupModel

        user = await make_user(session)
        new_executor = await make_user(session)
        group = GroupModel(name="test_group_bulk")
        session.add(group)
        await session.commit()
        await session.refresh(group)

        task = await make_task(session, user, title="A", group_id=group.id)
        service = build_service(session)

        await service.bulk_update_tasks(BulkTaskUpdate(task_ids=[task.id], user_id=new_executor.id), user)

        await session.refresh(task)
        assert task.user_id == new_executor.id
        assert task.group_id is None

    @pytest.mark.asyncio
    async def test_task_without_access_is_skipped_not_raised(self, session):
        owner = await make_user(session)
        stranger = await make_user(session)
        task = await make_task(session, owner, title="Чужая", user_id=owner.id)
        service = build_service(session)

        result = await service.bulk_update_tasks(BulkTaskUpdate(task_ids=[task.id], status=TaskStatus.done), stranger)

        assert result.updated == 0
        assert result.skipped == [task.id]
        await session.refresh(task)
        assert task.status != TaskStatus.done

    @pytest.mark.asyncio
    async def test_mixed_access_partial_update(self, session):
        owner = await make_user(session)
        stranger = await make_user(session)
        own_task = await make_task(session, owner, title="Моя", user_id=owner.id)
        foreign_task = await make_task(session, stranger, title="Чужая", user_id=stranger.id)
        service = build_service(session)

        result = await service.bulk_update_tasks(
            BulkTaskUpdate(task_ids=[own_task.id, foreign_task.id], priority="high"), owner
        )

        assert result.updated == 1
        assert result.skipped == [foreign_task.id]

    @pytest.mark.asyncio
    async def test_nonexistent_task_id_is_skipped(self, session):
        user = await make_user(session)
        task = await make_task(session, user, title="A", user_id=user.id)
        service = build_service(session)

        result = await service.bulk_update_tasks(
            BulkTaskUpdate(task_ids=[task.id, 999999], status=TaskStatus.in_progress), user
        )

        assert result.updated == 1
        assert 999999 in result.skipped

    @pytest.mark.asyncio
    async def test_all_tasks_nonexistent_raises_404(self, session):
        from fastapi import HTTPException

        user = await make_user(session)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.bulk_update_tasks(BulkTaskUpdate(task_ids=[999999], status=TaskStatus.done), user)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_nonexistent_tag_id_raises_404(self, session):
        from fastapi import HTTPException

        user = await make_user(session)
        task = await make_task(session, user, title="A", user_id=user.id)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.bulk_update_tasks(BulkTaskUpdate(task_ids=[task.id], tag_id=999999), user)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_single_commit_for_whole_batch(self, session):
        """Экономия — один commit на пачку, а не по одному на задачу.
        Проверяем через spy на session.commit."""
        from unittest.mock import AsyncMock

        user = await make_user(session)
        tasks = [await make_task(session, user, title=f"T{i}", user_id=user.id) for i in range(5)]
        service = build_service(session)

        original_commit = session.commit
        commit_spy = AsyncMock(side_effect=original_commit)
        session.commit = commit_spy

        await service.bulk_update_tasks(
            BulkTaskUpdate(task_ids=[t.id for t in tasks], status=TaskStatus.in_progress), user
        )

        assert commit_spy.call_count == 1


class TestBulkUpdateSchema:
    def test_requires_at_least_one_field(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BulkTaskUpdate(task_ids=[1])

    def test_empty_task_ids_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BulkTaskUpdate(task_ids=[], status=TaskStatus.done)


class TestBulkUpdateEndpoint:
    @pytest.mark.asyncio
    async def test_bulk_update_via_endpoint(self, auth_client):
        client, _ = auth_client
        r1 = await client.post("/tasks/", json={"title": "Bulk 1"})
        r2 = await client.post("/tasks/", json={"title": "Bulk 2"})
        id1, id2 = r1.json()["id"], r2.json()["id"]

        resp = await client.patch(
            "/tasks/bulk",
            json={"task_ids": [id1, id2], "status": "in_progress"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == 2
        assert data["skipped"] == []

        get1 = await client.get(f"/tasks/{id1}")
        assert get1.json()["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_bulk_update_without_auth_returns_401_or_403(self, client):
        resp = await client.patch("/tasks/bulk", json={"task_ids": [1], "status": "done"})
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_bulk_update_empty_body_returns_422(self, auth_client):
        client, _ = auth_client
        r1 = await client.post("/tasks/", json={"title": "X"})
        resp = await client.patch("/tasks/bulk", json={"task_ids": [r1.json()["id"]]})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_bulk_route_not_shadowed_by_task_id_route(self, auth_client):
        """Регрессия на порядок роутов: /tasks/bulk НЕ должен пытаться
        распарситься как /{task_id}."""
        client, _ = auth_client
        resp = await client.patch("/tasks/bulk", json={"task_ids": [1], "priority": "high"})
        assert resp.status_code != 422 or "task_ids" not in str(resp.json())
        # Основная проверка: запрос дошёл до нужного эндпоинта, а не свалился
        # в 422 из-за конвертации "bulk" -> int для path-параметра task_id.
        assert resp.status_code in (200, 404, 400)

    @pytest.mark.asyncio
    async def test_bulk_update_stranger_task_returns_skipped_not_error(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with async_session() as sess:
            await make_user(sess, username="bulk_owner", password="pass123")
        resp1 = await client.post("/auth/login", json={"username": "bulk_owner", "password": "pass123"})
        token1 = resp1.json()["access_token"]
        create_resp = await client.post(
            "/tasks/", json={"title": "Owner task"}, headers={"Authorization": f"Bearer {token1}"}
        )
        task_id = create_resp.json()["id"]

        async with async_session() as sess:
            await make_user(sess, username="bulk_stranger", password="pass123")
        resp2 = await client.post("/auth/login", json={"username": "bulk_stranger", "password": "pass123"})
        token2 = resp2.json()["access_token"]

        resp = await client.patch(
            "/tasks/bulk",
            json={"task_ids": [task_id], "status": "done"},
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == 0
        assert data["skipped"] == [task_id]
