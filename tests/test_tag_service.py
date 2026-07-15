# tests/test_tag_service.py
import uuid

import pytest
from fastapi import HTTPException

from src.models.task import SpisokModel
from src.repositories.groups_repository import GroupRepository
from src.repositories.tag_repository import TagRepository
from src.repositories.task_repository import TaskRepository
from src.schemas.tag import TagCreate
from src.services.tag_service import TagService
from tests.conftest import make_user


def build_service(session):
    return TagService(
        tag_repo=TagRepository(session),
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


class TestCreateTag:
    @pytest.mark.asyncio
    async def test_creates_tag_with_default_color(self, session):
        service = build_service(session)

        tag = await service.create_tag(TagCreate(name="клиент-X"))

        assert tag.name == "клиент-X"
        assert tag.color == "#6b7280"

    @pytest.mark.asyncio
    async def test_creates_tag_with_custom_color(self, session):
        service = build_service(session)

        tag = await service.create_tag(TagCreate(name="срочно", color="#ef4444"))

        assert tag.color == "#ef4444"

    @pytest.mark.asyncio
    async def test_duplicate_name_rejected(self, session):
        service = build_service(session)
        await service.create_tag(TagCreate(name="дубликат"))

        with pytest.raises(HTTPException) as exc:
            await service.create_tag(TagCreate(name="дубликат"))

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_duplicate_name_case_insensitive(self, session):
        service = build_service(session)
        await service.create_tag(TagCreate(name="Клиент"))

        with pytest.raises(HTTPException) as exc:
            await service.create_tag(TagCreate(name="клиент"))

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_color_format_rejected(self):
        with pytest.raises(ValueError):
            TagCreate(name="X", color="red")

    @pytest.mark.asyncio
    async def test_strips_leading_hash_from_name(self):
        tag_data = TagCreate(name="#срочно")
        assert tag_data.name == "срочно"

    @pytest.mark.asyncio
    async def test_empty_name_rejected(self):
        with pytest.raises(ValueError):
            TagCreate(name="   ")


class TestListTags:
    @pytest.mark.asyncio
    async def test_returns_all_tags_sorted(self, session):
        service = build_service(session)
        await service.create_tag(TagCreate(name="Ю-тег"))
        await service.create_tag(TagCreate(name="А-тег"))

        tags = await service.list_tags()

        assert [t.name for t in tags] == ["А-тег", "Ю-тег"]


class TestDeleteTag:
    @pytest.mark.asyncio
    async def test_deletes_tag(self, session):
        service = build_service(session)
        tag = await service.create_tag(TagCreate(name="Удалить"))

        await service.delete_tag(tag.id)

        tags = await service.list_tags()
        assert tags == []

    @pytest.mark.asyncio
    async def test_nonexistent_tag_raises_404(self, session):
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.delete_tag(999999)

        assert exc.value.status_code == 404


class TestSetTaskTags:
    @pytest.mark.asyncio
    async def test_attaches_tags_to_task(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        service = build_service(session)
        tag1 = await service.create_tag(TagCreate(name="A"))
        tag2 = await service.create_tag(TagCreate(name="B"))

        updated = await service.set_task_tags(task.id, [tag1.id, tag2.id], author)

        names = {t.name for t in updated.tags}
        assert names == {"A", "B"}

    @pytest.mark.asyncio
    async def test_replaces_existing_tags_not_appends(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        service = build_service(session)
        tag1 = await service.create_tag(TagCreate(name="A"))
        tag2 = await service.create_tag(TagCreate(name="B"))
        await service.set_task_tags(task.id, [tag1.id], author)

        updated = await service.set_task_tags(task.id, [tag2.id], author)

        names = {t.name for t in updated.tags}
        assert names == {"B"}

    @pytest.mark.asyncio
    async def test_empty_list_clears_tags(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        service = build_service(session)
        tag1 = await service.create_tag(TagCreate(name="A"))
        await service.set_task_tags(task.id, [tag1.id], author)

        updated = await service.set_task_tags(task.id, [], author)

        assert updated.tags == []

    @pytest.mark.asyncio
    async def test_nonexistent_tag_id_raises_404(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.set_task_tags(task.id, [999999], author)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_stranger_forbidden(self, session):
        author = await make_user(session)
        task = await make_task(session, author)
        stranger = await make_stranger(session)
        service = build_service(session)
        tag = await service.create_tag(TagCreate(name="A"))

        with pytest.raises(HTTPException) as exc:
            await service.set_task_tags(task.id, [tag.id], stranger)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_nonexistent_task_raises_404(self, session):
        author = await make_user(session)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.set_task_tags(999999, [], author)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_same_tag_shared_across_tasks(self, session):
        """Тег общий на всю команду — может висеть одновременно на нескольких задачах."""
        author = await make_user(session)
        task1 = await make_task(session, author)
        task2 = await make_task(session, author)
        service = build_service(session)
        tag = await service.create_tag(TagCreate(name="общий"))

        await service.set_task_tags(task1.id, [tag.id], author)
        await service.set_task_tags(task2.id, [tag.id], author)

        t1 = await service.set_task_tags(task1.id, [tag.id], author)
        t2 = await service.set_task_tags(task2.id, [tag.id], author)
        assert t1.tags[0].id == t2.tags[0].id == tag.id
