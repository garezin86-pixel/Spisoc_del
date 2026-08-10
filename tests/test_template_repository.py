# tests/test_template_repository.py
"""
Тесты для src/repositories/template_repository.py.

Основной риск здесь — правила видимости шаблонов (private/group/global),
т.к. это довольно сложные условия с подзапросом по группам пользователя.
Ошибка в access_condition означает либо утечку чужих приватных шаблонов,
либо то, что пользователь не видит свои же групповые шаблоны.
"""

import uuid

import pytest

from src.models.group import GroupModel
from src.repositories.template_repository import TemplateRepository
from src.schemas.template import TemplateCreate, TemplateItemCreate, TemplateUpdate
from tests.conftest import make_user


async def make_group(session, members=None):
    group = GroupModel(name=f"group_{uuid.uuid4().hex[:6]}")
    for m in members or []:
        group.users.append(m)
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return group


class TestCreate:
    @pytest.mark.asyncio
    async def test_creates_template_with_items(self, session):
        owner = await make_user(session)
        repo = TemplateRepository(session)

        data = TemplateCreate(
            title="Онбординг",
            items=[
                TemplateItemCreate(title="Завести доступы", order_index=0),
                TemplateItemCreate(title="Настроить рабочее место", order_index=1),
            ],
        )
        template = await repo.create(owner.id, data)

        assert template.id is not None
        assert template.owner_id == owner.id
        assert template.visibility == "private"
        assert len(template.items) == 2

    @pytest.mark.asyncio
    async def test_items_default_order_index_uses_enumeration(self, session):
        owner = await make_user(session)
        repo = TemplateRepository(session)

        data = TemplateCreate(
            title="Шаблон",
            items=[
                TemplateItemCreate(title="Первый"),
                TemplateItemCreate(title="Второй"),
            ],
        )
        template = await repo.create(owner.id, data)

        items_sorted = sorted(template.items, key=lambda i: i.order_index)
        assert items_sorted[0].title == "Первый"
        assert items_sorted[1].title == "Второй"

    @pytest.mark.asyncio
    async def test_creates_template_without_items(self, session):
        owner = await make_user(session)
        repo = TemplateRepository(session)

        template = await repo.create(owner.id, TemplateCreate(title="Пустой шаблон"))

        assert template.items == []

    @pytest.mark.asyncio
    async def test_creates_group_template(self, session):
        owner = await make_user(session)
        group = await make_group(session, members=[owner])
        repo = TemplateRepository(session)

        template = await repo.create(
            owner.id, TemplateCreate(title="Групповой шаблон", visibility="group", group_id=group.id)
        )

        assert template.visibility == "group"
        assert template.group_id == group.id


class TestGetAllVisibility:
    @pytest.mark.asyncio
    async def test_owner_sees_own_private_template(self, session):
        owner = await make_user(session)
        repo = TemplateRepository(session)
        await repo.create(owner.id, TemplateCreate(title="Моё приватное"))

        templates = await repo.get_all(owner.id)

        assert any(t.title == "Моё приватное" for t in templates)

    @pytest.mark.asyncio
    async def test_stranger_does_not_see_private_template(self, session):
        owner = await make_user(session)
        stranger = await make_user(session)
        repo = TemplateRepository(session)
        await repo.create(owner.id, TemplateCreate(title="Чужое приватное"))

        templates = await repo.get_all(stranger.id)

        assert not any(t.title == "Чужое приватное" for t in templates)

    @pytest.mark.asyncio
    async def test_everyone_sees_global_template(self, session):
        owner = await make_user(session)
        stranger = await make_user(session)
        repo = TemplateRepository(session)
        await repo.create(owner.id, TemplateCreate(title="Глобальный", visibility="global"))

        templates = await repo.get_all(stranger.id)

        assert any(t.title == "Глобальный" for t in templates)

    @pytest.mark.asyncio
    async def test_group_member_sees_group_template(self, session):
        owner = await make_user(session)
        member = await make_user(session)
        group = await make_group(session, members=[owner, member])
        repo = TemplateRepository(session)
        await repo.create(owner.id, TemplateCreate(title="Групповой", visibility="group", group_id=group.id))

        templates = await repo.get_all(member.id)

        assert any(t.title == "Групповой" for t in templates)

    @pytest.mark.asyncio
    async def test_non_member_does_not_see_group_template(self, session):
        owner = await make_user(session)
        outsider = await make_user(session)
        group = await make_group(session, members=[owner])
        repo = TemplateRepository(session)
        await repo.create(owner.id, TemplateCreate(title="Групповой", visibility="group", group_id=group.id))

        templates = await repo.get_all(outsider.id)

        assert not any(t.title == "Групповой" for t in templates)

    @pytest.mark.asyncio
    async def test_visibility_filter_private(self, session):
        owner = await make_user(session)
        repo = TemplateRepository(session)
        await repo.create(owner.id, TemplateCreate(title="Приватный"))
        await repo.create(owner.id, TemplateCreate(title="Глобальный", visibility="global"))

        templates = await repo.get_all(owner.id, visibility_filter="private")

        titles = {t.title for t in templates}
        assert "Приватный" in titles
        assert "Глобальный" not in titles

    @pytest.mark.asyncio
    async def test_visibility_filter_global(self, session):
        owner = await make_user(session)
        repo = TemplateRepository(session)
        await repo.create(owner.id, TemplateCreate(title="Приватный"))
        await repo.create(owner.id, TemplateCreate(title="Глобальный", visibility="global"))

        templates = await repo.get_all(owner.id, visibility_filter="global")

        titles = {t.title for t in templates}
        assert "Глобальный" in titles
        assert "Приватный" not in titles

    @pytest.mark.asyncio
    async def test_visibility_filter_group(self, session):
        owner = await make_user(session)
        group = await make_group(session, members=[owner])
        repo = TemplateRepository(session)
        await repo.create(owner.id, TemplateCreate(title="Приватный"))
        await repo.create(owner.id, TemplateCreate(title="Групповой", visibility="group", group_id=group.id))

        templates = await repo.get_all(owner.id, visibility_filter="group")

        titles = {t.title for t in templates}
        assert "Групповой" in titles
        assert "Приватный" not in titles


class TestGetById:
    @pytest.mark.asyncio
    async def test_owner_can_get_private(self, session):
        owner = await make_user(session)
        repo = TemplateRepository(session)
        created = await repo.create(owner.id, TemplateCreate(title="Приватный"))

        result = await repo.get_by_id(created.id, owner.id)

        assert result is not None
        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_stranger_cannot_get_private(self, session):
        owner = await make_user(session)
        stranger = await make_user(session)
        repo = TemplateRepository(session)
        created = await repo.create(owner.id, TemplateCreate(title="Приватный"))

        result = await repo.get_by_id(created.id, stranger.id)

        assert result is None

    @pytest.mark.asyncio
    async def test_anyone_can_get_global(self, session):
        owner = await make_user(session)
        stranger = await make_user(session)
        repo = TemplateRepository(session)
        created = await repo.create(owner.id, TemplateCreate(title="Глобальный", visibility="global"))

        result = await repo.get_by_id(created.id, stranger.id)

        assert result is not None

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent(self, session):
        owner = await make_user(session)
        repo = TemplateRepository(session)

        result = await repo.get_by_id(999999, owner.id)

        assert result is None


class TestGetByIdOwnerOnly:
    @pytest.mark.asyncio
    async def test_returns_template_for_owner(self, session):
        owner = await make_user(session)
        repo = TemplateRepository(session)
        created = await repo.create(owner.id, TemplateCreate(title="Мой"))

        result = await repo.get_by_id_owner_only(created.id, owner.id)

        assert result is not None

    @pytest.mark.asyncio
    async def test_returns_none_for_non_owner_even_if_global(self, session):
        """Глобальная видимость не даёт права редактировать — только владелец."""
        owner = await make_user(session)
        stranger = await make_user(session)
        repo = TemplateRepository(session)
        created = await repo.create(owner.id, TemplateCreate(title="Глобальный", visibility="global"))

        result = await repo.get_by_id_owner_only(created.id, stranger.id)

        assert result is None


class TestUpdate:
    @pytest.mark.asyncio
    async def test_updates_title_and_description(self, session):
        owner = await make_user(session)
        repo = TemplateRepository(session)
        created = await repo.create(owner.id, TemplateCreate(title="Старое"))

        updated = await repo.update(created, TemplateUpdate(title="Новое", description="Описание"))

        assert updated.title == "Новое"
        assert updated.description == "Описание"

    @pytest.mark.asyncio
    async def test_replaces_items(self, session):
        owner = await make_user(session)
        repo = TemplateRepository(session)
        created = await repo.create(
            owner.id,
            TemplateCreate(title="Шаблон", items=[TemplateItemCreate(title="Старый пункт")]),
        )

        updated = await repo.update(
            created,
            TemplateUpdate(
                items=[TemplateItemCreate(title="Новый пункт 1"), TemplateItemCreate(title="Новый пункт 2")]
            ),
        )

        titles = {i.title for i in updated.items}
        assert titles == {"Новый пункт 1", "Новый пункт 2"}

    @pytest.mark.asyncio
    async def test_partial_update_keeps_items_when_not_specified(self, session):
        owner = await make_user(session)
        repo = TemplateRepository(session)
        created = await repo.create(
            owner.id,
            TemplateCreate(title="Шаблон", items=[TemplateItemCreate(title="Пункт")]),
        )

        updated = await repo.update(created, TemplateUpdate(title="Новое имя"))

        assert len(updated.items) == 1
        assert updated.items[0].title == "Пункт"

    @pytest.mark.asyncio
    async def test_visibility_change_to_group_sets_group_id(self, session):
        owner = await make_user(session)
        group = await make_group(session, members=[owner])
        repo = TemplateRepository(session)
        created = await repo.create(owner.id, TemplateCreate(title="Шаблон"))

        updated = await repo.update(created, TemplateUpdate(visibility="group", group_id=group.id))

        assert updated.visibility == "group"
        assert updated.group_id == group.id


class TestDelete:
    @pytest.mark.asyncio
    async def test_removes_template(self, session):
        owner = await make_user(session)
        repo = TemplateRepository(session)
        created = await repo.create(owner.id, TemplateCreate(title="К удалению"))
        template_id = created.id

        await repo.delete(created)

        result = await repo.get_by_id(template_id, owner.id)
        assert result is None


class TestApplyExtendedFields:
    """Новые поля шаблона: дедлайн-смещение, теги, чек-лист."""

    @pytest.mark.asyncio
    async def test_deadline_offset_becomes_absolute_deadline(self, session):
        from datetime import datetime, timedelta, timezone

        from src.models.project import ProjectModel

        owner = await make_user(session)
        project = ProjectModel(name="Проект", owner_id=owner.id)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        repo = TemplateRepository(session)
        template = await repo.create(
            owner.id,
            TemplateCreate(
                title="Онбординг",
                items=[TemplateItemCreate(title="Подписать документы", deadline_offset_days=3)],
            ),
        )

        before = datetime.now(timezone.utc)
        tasks = await repo.apply(template, project_id=project.id, user_id=owner.id)
        after = datetime.now(timezone.utc)

        assert tasks[0].deadline is not None
        assert before + timedelta(days=3) <= tasks[0].deadline <= after + timedelta(days=3)

    @pytest.mark.asyncio
    async def test_no_deadline_offset_leaves_deadline_none(self, session):
        from src.models.project import ProjectModel

        owner = await make_user(session)
        project = ProjectModel(name="Проект", owner_id=owner.id)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        repo = TemplateRepository(session)
        template = await repo.create(
            owner.id, TemplateCreate(title="Онбординг", items=[TemplateItemCreate(title="Без дедлайна")])
        )

        tasks = await repo.apply(template, project_id=project.id, user_id=owner.id)

        assert tasks[0].deadline is None

    @pytest.mark.asyncio
    async def test_tags_are_created_and_attached(self, session):
        from src.models.project import ProjectModel

        owner = await make_user(session)
        project = ProjectModel(name="Проект", owner_id=owner.id)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        repo = TemplateRepository(session)
        template = await repo.create(
            owner.id,
            TemplateCreate(
                title="Онбординг",
                items=[TemplateItemCreate(title="Задача", tags=["Срочно", "  клиент  ", ""])],
            ),
        )

        tasks = await repo.apply(template, project_id=project.id, user_id=owner.id)
        await session.refresh(tasks[0], attribute_names=["tags"])

        tag_names = sorted(t.name for t in tasks[0].tags)
        # Пустая строка отфильтрована, пробелы обрезаны
        assert tag_names == ["Срочно", "клиент"]

    @pytest.mark.asyncio
    async def test_reusing_existing_tag_does_not_duplicate(self, session):
        from src.models.project import ProjectModel
        from src.repositories.tag_repository import TagRepository

        owner = await make_user(session)
        project = ProjectModel(name="Проект", owner_id=owner.id)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        existing_tag = await TagRepository(session).get_or_create("Срочно", "#ff0000")

        repo = TemplateRepository(session)
        template = await repo.create(
            owner.id,
            TemplateCreate(title="Онбординг", items=[TemplateItemCreate(title="Задача", tags=["Срочно"])]),
        )
        tasks = await repo.apply(template, project_id=project.id, user_id=owner.id)
        await session.refresh(tasks[0], attribute_names=["tags"])

        assert len(tasks[0].tags) == 1
        assert tasks[0].tags[0].id == existing_tag.id
        assert tasks[0].tags[0].color == "#ff0000"  # цвет существующего тега не перезаписан

    @pytest.mark.asyncio
    async def test_checklist_items_created_in_order(self, session):
        from sqlalchemy import select

        from src.models.checklist import TaskChecklistItemModel
        from src.models.project import ProjectModel

        owner = await make_user(session)
        project = ProjectModel(name="Проект", owner_id=owner.id)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        repo = TemplateRepository(session)
        template = await repo.create(
            owner.id,
            TemplateCreate(
                title="Онбординг",
                items=[TemplateItemCreate(title="Задача", checklist=["Шаг 1", "Шаг 2", ""])],
            ),
        )
        tasks = await repo.apply(template, project_id=project.id, user_id=owner.id)

        result = await session.execute(
            select(TaskChecklistItemModel)
            .where(TaskChecklistItemModel.task_id == tasks[0].id)
            .order_by(TaskChecklistItemModel.order_index)
        )
        items = list(result.scalars().all())

        assert [i.title for i in items] == ["Шаг 1", "Шаг 2"]
        assert all(not i.is_done for i in items)

    @pytest.mark.asyncio
    async def test_description_is_copied_to_task(self, session):
        from src.models.project import ProjectModel

        owner = await make_user(session)
        project = ProjectModel(name="Проект", owner_id=owner.id)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        repo = TemplateRepository(session)
        template = await repo.create(
            owner.id,
            TemplateCreate(
                title="Онбординг",
                items=[TemplateItemCreate(title="Задача", description="Развёрнутое описание шага")],
            ),
        )
        tasks = await repo.apply(template, project_id=project.id, user_id=owner.id)

        assert tasks[0].description == "Развёрнутое описание шага"


class TestApply:
    @pytest.mark.asyncio
    async def test_creates_tasks_from_template_items(self, session):
        from src.models.project import ProjectModel
        from src.models.task import TaskStatus

        owner = await make_user(session)
        project = ProjectModel(name="Проект", owner_id=owner.id)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        repo = TemplateRepository(session)
        template = await repo.create(
            owner.id,
            TemplateCreate(
                title="Онбординг",
                items=[
                    TemplateItemCreate(title="Задача 1", order_index=1),
                    TemplateItemCreate(title="Задача 2", order_index=0),
                ],
            ),
        )

        tasks = await repo.apply(template, project_id=project.id, user_id=owner.id)

        assert len(tasks) == 2
        assert all(t.status == TaskStatus.todo for t in tasks)
        assert all(t.project_id == project.id for t in tasks)
        assert all(t.author_id == owner.id and t.user_id == owner.id for t in tasks)

    @pytest.mark.asyncio
    async def test_applies_items_in_order_index_order(self, session):
        from src.models.project import ProjectModel

        owner = await make_user(session)
        project = ProjectModel(name="Проект", owner_id=owner.id)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        repo = TemplateRepository(session)
        template = await repo.create(
            owner.id,
            TemplateCreate(
                title="Шаблон",
                items=[
                    TemplateItemCreate(title="Второй", order_index=1),
                    TemplateItemCreate(title="Первый", order_index=0),
                ],
            ),
        )

        tasks = await repo.apply(template, project_id=project.id, user_id=owner.id)

        assert [t.title for t in tasks] == ["Первый", "Второй"]

    @pytest.mark.asyncio
    async def test_empty_template_creates_no_tasks(self, session):
        from src.models.project import ProjectModel

        owner = await make_user(session)
        project = ProjectModel(name="Проект", owner_id=owner.id)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        repo = TemplateRepository(session)
        template = await repo.create(owner.id, TemplateCreate(title="Пустой"))

        tasks = await repo.apply(template, project_id=project.id, user_id=owner.id)

        assert tasks == []
