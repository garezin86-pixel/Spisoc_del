# tests/test_task_export.py
import csv
import io
import uuid
from datetime import datetime, timezone

import pytest

from src.models.tag import TagModel
from src.models.task import SpisokModel, TaskStatus
from src.models.user import UserRole
from src.repositories.task_repository import TaskRepository
from src.services.task_export_service import TaskExportService
from tests.conftest import make_user


async def make_task(session, author, **kwargs):
    task = SpisokModel(title=kwargs.pop("title", "Задача"), author_id=author.id, **kwargs)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def make_manager(session):
    user = await make_user(session, username=f"mgr_{uuid.uuid4().hex[:6]}", password="pass123")
    user.role = UserRole.manager
    await session.commit()
    await session.refresh(user)
    return user


def parse_csv(content: str) -> list[dict]:
    # Убираем BOM перед парсингом
    content = content.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(content))
    return list(reader)


class TestExportVisibility:
    @pytest.mark.asyncio
    async def test_regular_user_sees_only_own_tasks(self, session):
        user = await make_user(session)
        stranger = await make_user(session)
        await make_task(session, user, title="Моя задача", user_id=user.id)
        await make_task(session, stranger, title="Чужая задача", user_id=stranger.id)

        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(user)
        rows = parse_csv(csv_content)

        titles = {r["Название"] for r in rows}
        assert titles == {"Моя задача"}

    @pytest.mark.asyncio
    async def test_manager_sees_all_tasks(self, session):
        manager = await make_manager(session)
        user = await make_user(session)
        await make_task(session, user, title="Задача пользователя", user_id=user.id)
        await make_task(session, manager, title="Задача менеджера", user_id=manager.id)

        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(manager)
        rows = parse_csv(csv_content)

        titles = {r["Название"] for r in rows}
        assert titles == {"Задача пользователя", "Задача менеджера"}

    @pytest.mark.asyncio
    async def test_regular_user_author_of_task_assigned_to_others_is_not_visible(self, session):
        """
        Форсированный filter_user_group=user означает "назначено мне" —
        не "созданное мной". Если обычный пользователь создал задачу для
        коллеги, в его собственном экспорте её не будет — это тот же принцип
        видимости, что и в основном списке задач (viewMode="user" по умолчанию).
        """
        user = await make_user(session)
        colleague = await make_user(session)
        await make_task(session, user, title="Для коллеги", user_id=colleague.id)

        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(user)
        rows = parse_csv(csv_content)

        assert rows == []


class TestExportCsvContent:
    @pytest.mark.asyncio
    async def test_has_utf8_bom_for_excel(self, session):
        user = await make_user(session)
        service = TaskExportService(TaskRepository(session))

        csv_content = await service.export_tasks_csv(user)

        assert csv_content.startswith("\ufeff")

    @pytest.mark.asyncio
    async def test_header_row_present(self, session):
        user = await make_user(session)
        service = TaskExportService(TaskRepository(session))

        csv_content = await service.export_tasks_csv(user)
        # rows = parse_csv(csv_content)

        # Пустой список задач всё равно должен содержать заголовок
        reader = csv.reader(io.StringIO(csv_content.lstrip("\ufeff")))
        header = next(reader)
        assert header == [
            "ID",
            "Название",
            "Описание",
            "Статус",
            "Приоритет",
            "Автор",
            "Исполнитель",
            "Группа",
            "Проект",
            "Дедлайн",
            "Создано",
            "Теги",
            "Повторение",
        ]

    @pytest.mark.asyncio
    async def test_status_and_priority_translated_to_russian(self, session):
        user = await make_user(session)
        await make_task(
            session,
            user,
            title="X",
            user_id=user.id,
            status=TaskStatus.in_progress,
            priority="high",
        )

        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(user)
        rows = parse_csv(csv_content)

        assert rows[0]["Статус"] == "В работе"
        assert "Высокий" in rows[0]["Приоритет"]

    @pytest.mark.asyncio
    async def test_author_and_executor_usernames_included(self, session):
        author = await make_user(session)
        executor = await make_user(session)
        # author.role остаётся "user" по умолчанию — экспорт для него отфильтрует
        # по assignee, поэтому назначим задачу на самого автора и отдельно
        # проверим поля author/executor на объекте

        # Экспортируем от лица executor (у него эта задача "назначена мне")
        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(executor)
        rows = parse_csv(csv_content)

        assert rows[0]["Автор"] == author.username
        assert rows[0]["Исполнитель"] == executor.username

    @pytest.mark.asyncio
    async def test_tags_joined_with_comma(self, session):
        user = await make_user(session)
        task = await make_task(session, user, title="X", user_id=user.id)
        tag1 = TagModel(name="важное")
        tag2 = TagModel(name="срочно")
        session.add_all([tag1, tag2])
        await session.commit()
        task.tags.extend([tag1, tag2])
        await session.commit()

        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(user)
        rows = parse_csv(csv_content)

        tag_names = set(rows[0]["Теги"].split(", "))
        assert tag_names == {"важное", "срочно"}

    @pytest.mark.asyncio
    async def test_recurrence_label_translated(self, session):
        user = await make_user(session)
        await make_task(session, user, title="X", user_id=user.id, recurrence_rule="daily")

        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(user)
        rows = parse_csv(csv_content)

        assert rows[0]["Повторение"] == "Ежедневно"

    @pytest.mark.asyncio
    async def test_no_recurrence_is_empty_string(self, session):
        user = await make_user(session)
        await make_task(session, user, title="X", user_id=user.id, recurrence_rule="none")

        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(user)
        rows = parse_csv(csv_content)

        assert rows[0]["Повторение"] == ""

    @pytest.mark.asyncio
    async def test_deadline_formatted_as_date(self, session):
        user = await make_user(session)
        deadline = datetime(2026, 12, 31, 14, 30, tzinfo=timezone.utc)
        await make_task(session, user, title="X", user_id=user.id, deadline=deadline)

        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(user)
        rows = parse_csv(csv_content)

        assert rows[0]["Дедлайн"] == "31.12.2026 14:30"

    @pytest.mark.asyncio
    async def test_no_deadline_is_empty(self, session):
        user = await make_user(session)
        await make_task(session, user, title="X", user_id=user.id, deadline=None)

        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(user)
        rows = parse_csv(csv_content)

        assert rows[0]["Дедлайн"] == ""

    @pytest.mark.asyncio
    async def test_description_newlines_stripped(self, session):
        user = await make_user(session)
        await make_task(
            session,
            user,
            title="X",
            user_id=user.id,
            description="Строка1\nСтрока2\r\nСтрока3",
        )

        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(user)
        rows = parse_csv(csv_content)

        assert "\n" not in rows[0]["Описание"]
        assert "Строка1" in rows[0]["Описание"] and "Строка2" in rows[0]["Описание"]

    @pytest.mark.asyncio
    async def test_empty_result_still_returns_valid_csv(self, session):
        user = await make_user(session)
        service = TaskExportService(TaskRepository(session))

        csv_content = await service.export_tasks_csv(user)
        rows = parse_csv(csv_content)

        assert rows == []


class TestExportFilters:
    @pytest.mark.asyncio
    async def test_filters_by_project(self, session):
        from src.models.project import ProjectModel

        manager = await make_manager(session)
        project1 = ProjectModel(name="Проект 1", owner_id=manager.id)
        project2 = ProjectModel(name="Проект 2", owner_id=manager.id)
        session.add_all([project1, project2])
        await session.commit()
        await session.refresh(project1)
        await session.refresh(project2)

        await make_task(session, manager, title="В проекте 1", project_id=project1.id)
        await make_task(session, manager, title="В проекте 2", project_id=project2.id)

        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(manager, project_id=project1.id)
        rows = parse_csv(csv_content)

        assert len(rows) == 1
        assert rows[0]["Название"] == "В проекте 1"

    @pytest.mark.asyncio
    async def test_filters_by_deadline_range(self, session):
        manager = await make_manager(session)
        await make_task(
            session,
            manager,
            title="Рано",
            deadline=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        await make_task(
            session,
            manager,
            title="В диапазоне",
            deadline=datetime(2026, 6, 15, tzinfo=timezone.utc),
        )
        await make_task(
            session,
            manager,
            title="Поздно",
            deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
        )

        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(
            manager,
            deadline_from=datetime(2026, 3, 1, tzinfo=timezone.utc),
            deadline_to=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        rows = parse_csv(csv_content)

        assert len(rows) == 1
        assert rows[0]["Название"] == "В диапазоне"

    @pytest.mark.asyncio
    async def test_filters_by_status(self, session):
        manager = await make_manager(session)
        await make_task(session, manager, title="Готова", status=TaskStatus.done)
        await make_task(session, manager, title="В процессе", status=TaskStatus.in_progress)

        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(manager, status=TaskStatus.done)
        rows = parse_csv(csv_content)

        assert len(rows) == 1
        assert rows[0]["Название"] == "Готова"

    @pytest.mark.asyncio
    async def test_filters_by_tag(self, session):
        manager = await make_manager(session)
        tag = TagModel(name="важное")
        session.add(tag)
        await session.commit()
        task_with_tag = await make_task(session, manager, title="С тегом")
        await make_task(session, manager, title="Без тега")
        task_with_tag.tags.append(tag)
        await session.commit()

        service = TaskExportService(TaskRepository(session))
        csv_content = await service.export_tasks_csv(manager, tag_id=tag.id)
        rows = parse_csv(csv_content)

        assert len(rows) == 1
        assert rows[0]["Название"] == "С тегом"
