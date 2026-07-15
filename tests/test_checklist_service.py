# tests/test_checklist_service.py
import uuid

import pytest
from fastapi import HTTPException

from src.models.task import SpisokModel
from src.repositories.checklist_repository import ChecklistRepository
from src.repositories.groups_repository import GroupRepository
from src.repositories.task_repository import TaskRepository
from src.schemas.checklist import ChecklistItemCreate, ChecklistItemUpdate
from src.services.checklist_service import ChecklistService
from tests.conftest import make_user


def build_service(session):
    return ChecklistService(
        checklist_repo=ChecklistRepository(session),
        task_repo=TaskRepository(session),
        group_repo=GroupRepository(session),
    )


async def make_task(session, author, **kwargs):
    task = SpisokModel(title=kwargs.pop("title", "Задача"), author_id=author.id, **kwargs)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def make_stranger(session):
    return await make_user(session, username=f"stranger_{uuid.uuid4().hex[:6]}", password="pass123")


class TestAddItem:
    @pytest.mark.asyncio
    async def test_author_can_add_item(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        service = build_service(session)

        item = await service.add_item(task.id, ChecklistItemCreate(title="Собрать документы"), author)

        assert item.title == "Собрать документы"
        assert item.is_done is False
        assert item.task_id == task.id

    @pytest.mark.asyncio
    async def test_stranger_forbidden(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        stranger = await make_stranger(session)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.add_item(task.id, ChecklistItemCreate(title="X"), stranger)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_auto_assigns_incrementing_order_index(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        service = build_service(session)

        item1 = await service.add_item(task.id, ChecklistItemCreate(title="Первый"), author)
        item2 = await service.add_item(task.id, ChecklistItemCreate(title="Второй"), author)

        assert item1.order_index == 0
        assert item2.order_index == 1

    @pytest.mark.asyncio
    async def test_explicit_order_index_respected(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        service = build_service(session)

        item = await service.add_item(task.id, ChecklistItemCreate(title="X", order_index=5), author)

        assert item.order_index == 5

    @pytest.mark.asyncio
    async def test_nonexistent_task_raises_404(self, session):
        author = await make_user(session)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.add_item(999999, ChecklistItemCreate(title="X"), author)

        assert exc.value.status_code == 404


class TestListItems:
    @pytest.mark.asyncio
    async def test_returns_items_ordered(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        service = build_service(session)
        await service.add_item(task.id, ChecklistItemCreate(title="Б", order_index=1), author)
        await service.add_item(task.id, ChecklistItemCreate(title="А", order_index=0), author)

        items = await service.list_items(task.id, author)

        assert [i.title for i in items] == ["А", "Б"]

    @pytest.mark.asyncio
    async def test_executor_can_view(self, session):
        author = await make_user(session)
        executor = await make_stranger(session)
        task = await make_task(session, author, user_id=executor.id)
        service = build_service(session)
        await service.add_item(task.id, ChecklistItemCreate(title="X"), author)

        items = await service.list_items(task.id, executor)

        assert len(items) == 1


class TestUpdateItem:
    @pytest.mark.asyncio
    async def test_marks_done(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        service = build_service(session)
        item = await service.add_item(task.id, ChecklistItemCreate(title="X"), author)

        updated = await service.update_item(task.id, item.id, ChecklistItemUpdate(is_done=True), author)

        assert updated.is_done is True

    @pytest.mark.asyncio
    async def test_rename_title(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        service = build_service(session)
        item = await service.add_item(task.id, ChecklistItemCreate(title="Старое"), author)

        updated = await service.update_item(task.id, item.id, ChecklistItemUpdate(title="Новое"), author)

        assert updated.title == "Новое"

    @pytest.mark.asyncio
    async def test_item_from_another_task_returns_404(self, session):
        author = await make_user(session)
        task1 = await make_task(session, author)
        task2 = await make_task(session, author)
        service = build_service(session)
        item = await service.add_item(task1.id, ChecklistItemCreate(title="X"), author)

        with pytest.raises(HTTPException) as exc:
            await service.update_item(task2.id, item.id, ChecklistItemUpdate(is_done=True), author)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_stranger_forbidden(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        stranger = await make_stranger(session)
        service = build_service(session)
        item = await service.add_item(task.id, ChecklistItemCreate(title="X"), author)

        with pytest.raises(HTTPException) as exc:
            await service.update_item(task.id, item.id, ChecklistItemUpdate(is_done=True), stranger)

        assert exc.value.status_code == 403


class TestDeleteItem:
    @pytest.mark.asyncio
    async def test_deletes_item(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        service = build_service(session)
        item = await service.add_item(task.id, ChecklistItemCreate(title="X"), author)

        await service.delete_item(task.id, item.id, author)

        items = await service.list_items(task.id, author)
        assert items == []

    @pytest.mark.asyncio
    async def test_nonexistent_item_raises_404(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(task.id, 999999, author)

        assert exc.value.status_code == 404


class TestReorder:
    @pytest.mark.asyncio
    async def test_reorders_items(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        service = build_service(session)
        item1 = await service.add_item(task.id, ChecklistItemCreate(title="Первый"), author)
        item2 = await service.add_item(task.id, ChecklistItemCreate(title="Второй"), author)

        result = await service.reorder(task.id, {item1.id: 5, item2.id: 1}, author)

        by_id = {i.id: i.order_index for i in result}
        assert by_id[item1.id] == 5
        assert by_id[item2.id] == 1

    @pytest.mark.asyncio
    async def test_ignores_item_ids_from_other_tasks(self, session):
        """Защита от подмены: id пункта чужой задачи в теле запроса не должен её тронуть."""
        author = await make_user(session)
        task1 = await make_task(session, author)
        task2 = await make_task(session, author)
        service = build_service(session)
        foreign_item = await service.add_item(task2.id, ChecklistItemCreate(title="Чужой"), author)

        await service.reorder(task1.id, {foreign_item.id: 99}, author)

        foreign_items = await service.list_items(task2.id, author)
        assert foreign_items[0].order_index != 99


class TestCascadeDelete:
    @pytest.mark.asyncio
    async def test_checklist_items_deleted_when_task_hard_deleted(self, session):
        """
        cascade="all, delete-orphan" на relationship — пункты чек-листа не должны
        сиротеть в БД при удалении задачи.

        Загружаем задачу через репозиторий (как это происходит в реальном
        потоке приложения) перед удалением — иначе SQLAlchemy ORM не видит
        загруженную коллекцию checklist_items и не может каскадно её удалить
        на уровне Python; а ondelete=CASCADE на уровне БД в SQLite без явного
        PRAGMA foreign_keys=ON (которое тестовый движок не включает) не сработает.
        В реальном Postgres в проде FK-каскад сработал бы в любом случае.
        """
        author = await make_user(session)
        task = await make_task(session, author)
        service = build_service(session)
        await service.add_item(task.id, ChecklistItemCreate(title="X"), author)

        task_repo = TaskRepository(session)
        loaded_task = await task_repo.get_by_id_include_deleted(task.id)
        await session.refresh(loaded_task, ["checklist_items"])

        await session.delete(loaded_task)
        await session.commit()

        repo = ChecklistRepository(session)
        remaining = await repo.get_by_task(task.id)
        assert remaining == []
