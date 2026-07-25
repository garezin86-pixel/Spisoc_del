# tests/test_task_recurrence.py
from datetime import datetime, timedelta, timezone

import pytest

from src.models.enums import RecurrenceRule
from src.models.task import SpisokModel, TaskStatus
from src.repositories.groups_repository import GroupRepository
from src.repositories.tag_repository import TagRepository
from src.repositories.task_repository import TaskRepository
from src.schemas.task import SpisokUpdate
from src.services.task_service import TaskService
from tests.conftest import make_user


def build_service(session):
    from src.repositories.users_repository import UserRepository

    return TaskService(
        task_repo=TaskRepository(session),
        user_repo=UserRepository(session),
        group_repo=GroupRepository(session),
        tag_repo=TagRepository(session),
        session=session,
    )


async def make_task(session, author, **kwargs):
    task = SpisokModel(title=kwargs.pop("title", "Задача"), author_id=author.id, **kwargs)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


class TestSpawnOnStatusUpdate:
    @pytest.mark.asyncio
    async def test_daily_recurrence_spawns_next_task_on_done(self, session):
        author = await make_user(session)
        deadline = datetime.now(timezone.utc)
        task = await make_task(
            session,
            author,
            title="Ежедневный созвон",
            recurrence_rule=RecurrenceRule.daily,
            deadline=deadline,
            status=TaskStatus.todo,
        )
        service = build_service(session)

        await service.update_task_status(task.id, TaskStatus.done, author)

        repo = TaskRepository(session)
        all_tasks = await repo.get_filtered_tasks_with_total(user_id=author.id, offset=0, limit=50)
        titles_and_status = [(t.title, t.status) for t in all_tasks[0]]
        assert ("Ежедневный созвон", TaskStatus.todo) in titles_and_status
        assert ("Ежедневный созвон", TaskStatus.done) in titles_and_status

    @pytest.mark.asyncio
    async def test_new_task_deadline_advanced_by_one_day(self, session):
        author = await make_user(session)
        deadline = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        task = await make_task(
            session, author, recurrence_rule=RecurrenceRule.daily, deadline=deadline, status=TaskStatus.todo
        )
        service = build_service(session)

        await service.update_task_status(task.id, TaskStatus.done, author)

        repo = TaskRepository(session)
        tasks, _ = await repo.get_filtered_tasks_with_total(user_id=author.id, offset=0, limit=50)
        new_task = next(t for t in tasks if t.status == TaskStatus.todo)
        # SQLite не хранит tzinfo при обратном чтении (в отличие от Postgres,
        # где колонка DateTime(timezone=True) реально сохраняет зону) —
        # сравниваем как naive datetime, это чисто тестовый артефакт SQLite.
        expected = (deadline + timedelta(days=1)).replace(tzinfo=None)
        assert new_task.deadline.replace(tzinfo=None) == expected

    @pytest.mark.asyncio
    async def test_weekly_recurrence_advances_by_seven_days(self, session):
        author = await make_user(session)
        deadline = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        task = await make_task(
            session, author, recurrence_rule=RecurrenceRule.weekly, deadline=deadline, status=TaskStatus.todo
        )
        service = build_service(session)

        await service.update_task_status(task.id, TaskStatus.done, author)

        repo = TaskRepository(session)
        tasks, _ = await repo.get_filtered_tasks_with_total(user_id=author.id, offset=0, limit=50)
        new_task = next(t for t in tasks if t.status == TaskStatus.todo)
        expected = (deadline + timedelta(weeks=1)).replace(tzinfo=None)
        assert new_task.deadline.replace(tzinfo=None) == expected

    @pytest.mark.asyncio
    async def test_monthly_recurrence_advances_by_one_month(self, session):
        author = await make_user(session)
        deadline = datetime(2026, 1, 31, 12, 0, tzinfo=timezone.utc)
        task = await make_task(
            session, author, recurrence_rule=RecurrenceRule.monthly, deadline=deadline, status=TaskStatus.todo
        )
        service = build_service(session)

        await service.update_task_status(task.id, TaskStatus.done, author)

        repo = TaskRepository(session)
        tasks, _ = await repo.get_filtered_tasks_with_total(user_id=author.id, offset=0, limit=50)
        new_task = next(t for t in tasks if t.status == TaskStatus.todo)
        # 31 января + 1 месяц = 28 февраля (relativedelta корректно обрабатывает конец месяца)
        assert new_task.deadline.month == 2
        assert new_task.deadline.day == 28

    @pytest.mark.asyncio
    async def test_no_recurrence_does_not_spawn(self, session):
        author = await make_user(session)
        task = await make_task(session, author, recurrence_rule=RecurrenceRule.none, status=TaskStatus.todo)
        service = build_service(session)

        await service.update_task_status(task.id, TaskStatus.done, author)

        repo = TaskRepository(session)
        tasks, total = await repo.get_filtered_tasks_with_total(user_id=author.id, offset=0, limit=50)
        assert total == 1

    @pytest.mark.asyncio
    async def test_does_not_spawn_if_already_done(self, session):
        """Повторный вызов update_task_status(done) для уже done-задачи не должен плодить дубликаты."""
        author = await make_user(session)
        task = await make_task(session, author, recurrence_rule=RecurrenceRule.daily, status=TaskStatus.done)
        service = build_service(session)

        await service.update_task_status(task.id, TaskStatus.done, author)

        repo = TaskRepository(session)
        _, total = await repo.get_filtered_tasks_with_total(user_id=author.id, offset=0, limit=50)
        assert total == 1

    @pytest.mark.asyncio
    async def test_reopening_does_not_spawn(self, session):
        """Переоткрытие (done -> todo) не должно порождать новое повторение — только переход В done."""
        author = await make_user(session)
        task = await make_task(session, author, recurrence_rule=RecurrenceRule.daily, status=TaskStatus.done)
        service = build_service(session)

        await service.update_task_status(task.id, TaskStatus.todo, author)

        repo = TaskRepository(session)
        _, total = await repo.get_filtered_tasks_with_total(user_id=author.id, offset=0, limit=50)
        assert total == 1

    @pytest.mark.asyncio
    async def test_new_task_preserves_assignment_and_project(self, session):
        author = await make_user(session)
        executor = await make_user(session)
        from src.models.project import ProjectModel

        project = ProjectModel(name="Проект", owner_id=author.id)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        task = await make_task(
            session,
            author,
            recurrence_rule=RecurrenceRule.daily,
            deadline=datetime.now(timezone.utc),
            status=TaskStatus.todo,
            user_id=executor.id,
            project_id=project.id,
        )
        service = build_service(session)

        await service.update_task_status(task.id, TaskStatus.done, author)

        repo = TaskRepository(session)
        tasks, _ = await repo.get_filtered_tasks_with_total(user_id=author.id, offset=0, limit=50)
        new_task = next(t for t in tasks if t.status == TaskStatus.todo)
        assert new_task.user_id == executor.id
        assert new_task.project_id == project.id
        assert new_task.recurrence_rule == RecurrenceRule.daily

    @pytest.mark.asyncio
    async def test_recurrence_without_deadline_spawns_without_deadline(self, session):
        """Если у исходной задачи не было дедлайна, новое повторение тоже без дедлайна (не навязываем срок)."""
        author = await make_user(session)
        task = await make_task(
            session, author, recurrence_rule=RecurrenceRule.daily, deadline=None, status=TaskStatus.todo
        )
        service = build_service(session)

        await service.update_task_status(task.id, TaskStatus.done, author)

        repo = TaskRepository(session)
        tasks, _ = await repo.get_filtered_tasks_with_total(user_id=author.id, offset=0, limit=50)
        new_task = next(t for t in tasks if t.status == TaskStatus.todo)
        assert new_task.deadline is None


class TestSpawnViaUpdateTask:
    @pytest.mark.asyncio
    async def test_update_task_to_done_also_spawns_recurrence(self, session):
        """update_task (PATCH /tasks/{id}) — второй путь смены статуса на done — тоже должен спавнить."""
        author = await make_user(session)
        task = await make_task(
            session,
            author,
            recurrence_rule=RecurrenceRule.daily,
            deadline=datetime.now(timezone.utc),
            status=TaskStatus.todo,
        )
        service = build_service(session)

        await service.update_task(task.id, SpisokUpdate(status=TaskStatus.done), author)

        repo = TaskRepository(session)
        tasks, total = await repo.get_filtered_tasks_with_total(user_id=author.id, offset=0, limit=50)
        assert total == 2
        assert any(t.status == TaskStatus.todo for t in tasks)


class TestCompletedAtTracking:
    @pytest.mark.asyncio
    async def test_completed_at_set_on_transition_to_done_via_status_endpoint(self, session):
        author = await make_user(session)
        task = await make_task(session, author, status=TaskStatus.todo)
        service = build_service(session)
        assert task.completed_at is None

        updated = await service.update_task_status(task.id, TaskStatus.done, author)

        assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_completed_at_cleared_on_reopen(self, session):
        author = await make_user(session)
        task = await make_task(session, author, status=TaskStatus.todo)
        service = build_service(session)
        await service.update_task_status(task.id, TaskStatus.done, author)

        reopened = await service.update_task_status(task.id, TaskStatus.todo, author)

        assert reopened.completed_at is None

    @pytest.mark.asyncio
    async def test_completed_at_set_via_update_task(self, session):
        author = await make_user(session)
        task = await make_task(session, author, status=TaskStatus.todo)
        service = build_service(session)

        updated = await service.update_task(task.id, SpisokUpdate(status=TaskStatus.done), author)

        assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_completed_at_not_touched_when_editing_other_fields(self, session):
        """Правка title/description после завершения НЕ должна менять completed_at."""
        author = await make_user(session)
        fixed_completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        task = await make_task(session, author, status=TaskStatus.done, completed_at=fixed_completed_at)
        service = build_service(session)

        updated = await service.update_task(task.id, SpisokUpdate(title="Новое название"), author)

        assert updated.completed_at.replace(tzinfo=None) == fixed_completed_at.replace(tzinfo=None)

    @pytest.mark.asyncio
    async def test_no_op_status_update_does_not_change_completed_at(self, session):
        """Повторная установка того же статуса done не должна перезаписывать completed_at новым временем."""
        author = await make_user(session)
        fixed_completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        task = await make_task(session, author, status=TaskStatus.done, completed_at=fixed_completed_at)
        service = build_service(session)

        updated = await service.update_task_status(task.id, TaskStatus.done, author)

        assert updated.completed_at.replace(tzinfo=None) == fixed_completed_at.replace(tzinfo=None)


class TestNextDeadlineCalculation:
    def test_none_deadline_stays_none(self):
        result = TaskService._next_deadline(None, RecurrenceRule.daily)
        assert result is None

    def test_none_rule_returns_none(self):
        deadline = datetime.now(timezone.utc)
        result = TaskService._next_deadline(deadline, RecurrenceRule.none)
        assert result is None

    def test_daily_adds_one_day(self):
        deadline = datetime(2026, 3, 1, tzinfo=timezone.utc)
        result = TaskService._next_deadline(deadline, RecurrenceRule.daily)
        assert result == datetime(2026, 3, 2, tzinfo=timezone.utc)

    def test_weekly_adds_seven_days(self):
        deadline = datetime(2026, 3, 1, tzinfo=timezone.utc)
        result = TaskService._next_deadline(deadline, RecurrenceRule.weekly)
        assert result == datetime(2026, 3, 8, tzinfo=timezone.utc)
