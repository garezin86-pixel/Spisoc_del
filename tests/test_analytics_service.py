# tests/test_analytics_service.py
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.models.project import ProjectModel
from src.models.task import SpisokModel
from src.repositories.task_repository import TaskRepository
from src.services.analytics_service import AnalyticsService
from tests.conftest import make_user


async def make_task_with_completion(session, author, deadline, completed_at, **kwargs):
    task = SpisokModel(
        title=kwargs.pop("title", "Задача"),
        author_id=author.id,
        deadline=deadline,
        completed_at=completed_at,
        **kwargs,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


class TestExecutorCompletionStats:
    @pytest.mark.asyncio
    async def test_on_time_completion_counted_correctly(self, session):
        author = await make_user(session)
        executor = await make_user(session, username=f"exec_{uuid.uuid4().hex[:6]}", password="pass123")
        deadline = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        completed = deadline - timedelta(hours=1)  # завершено ДО дедлайна
        await make_task_with_completion(session, author, deadline, completed, user_id=executor.id)

        service = AnalyticsService(TaskRepository(session))
        result = await service.get_dashboard()

        stats = result["executor_completion"]
        assert len(stats) == 1
        assert stats[0]["username"] == executor.username
        assert stats[0]["on_time"] == 1
        assert stats[0]["late"] == 0
        assert stats[0]["on_time_rate"] == 100.0

    @pytest.mark.asyncio
    async def test_late_completion_counted_correctly(self, session):
        author = await make_user(session)
        executor = await make_user(session, username=f"exec_{uuid.uuid4().hex[:6]}", password="pass123")
        deadline = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        completed = deadline + timedelta(hours=2)  # завершено ПОСЛЕ дедлайна
        await make_task_with_completion(session, author, deadline, completed, user_id=executor.id)

        service = AnalyticsService(TaskRepository(session))
        result = await service.get_dashboard()

        stats = result["executor_completion"]
        assert stats[0]["on_time"] == 0
        assert stats[0]["late"] == 1
        assert stats[0]["on_time_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_exact_deadline_match_counts_as_on_time(self, session):
        """completed_at == deadline (ровно вовремя) — считается "в срок", не "с опозданием"."""
        author = await make_user(session)
        executor = await make_user(session, username=f"exec_{uuid.uuid4().hex[:6]}", password="pass123")
        deadline = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        await make_task_with_completion(session, author, deadline, deadline, user_id=executor.id)

        service = AnalyticsService(TaskRepository(session))
        result = await service.get_dashboard()

        assert result["executor_completion"][0]["on_time"] == 1

    @pytest.mark.asyncio
    async def test_mixed_on_time_and_late_computes_correct_rate(self, session):
        author = await make_user(session)
        executor = await make_user(session, username=f"exec_{uuid.uuid4().hex[:6]}", password="pass123")
        deadline = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

        # 3 в срок, 1 с опозданием -> 75%
        for _ in range(3):
            await make_task_with_completion(
                session, author, deadline, deadline - timedelta(hours=1), user_id=executor.id
            )
        await make_task_with_completion(session, author, deadline, deadline + timedelta(hours=1), user_id=executor.id)

        service = AnalyticsService(TaskRepository(session))
        result = await service.get_dashboard()

        stats = result["executor_completion"][0]
        assert stats["total_completed"] == 4
        assert stats["on_time"] == 3
        assert stats["late"] == 1
        assert stats["on_time_rate"] == 75.0

    @pytest.mark.asyncio
    async def test_multiple_executors_separated(self, session):
        author = await make_user(session)
        exec1 = await make_user(session, username=f"e1_{uuid.uuid4().hex[:6]}", password="pass123")
        exec2 = await make_user(session, username=f"e2_{uuid.uuid4().hex[:6]}", password="pass123")
        deadline = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

        await make_task_with_completion(session, author, deadline, deadline - timedelta(hours=1), user_id=exec1.id)
        await make_task_with_completion(session, author, deadline, deadline + timedelta(hours=1), user_id=exec2.id)

        service = AnalyticsService(TaskRepository(session))
        result = await service.get_dashboard()

        by_username = {s["username"]: s for s in result["executor_completion"]}
        assert by_username[exec1.username]["on_time_rate"] == 100.0
        assert by_username[exec2.username]["on_time_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_task_without_executor_excluded(self, session):
        author = await make_user(session)
        deadline = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        await make_task_with_completion(session, author, deadline, deadline, user_id=None)

        service = AnalyticsService(TaskRepository(session))
        result = await service.get_dashboard()

        assert result["executor_completion"] == []

    @pytest.mark.asyncio
    async def test_incomplete_tasks_excluded_from_stats(self, session):
        """Задачи без completed_at (не завершённые) или без deadline не участвуют в расчёте."""
        author = await make_user(session)
        executor = await make_user(session, username=f"exec_{uuid.uuid4().hex[:6]}", password="pass123")

        # Не завершена
        task1 = SpisokModel(title="X", author_id=author.id, user_id=executor.id, deadline=datetime.now(timezone.utc))
        # Завершена, но без дедлайна
        task2 = SpisokModel(
            title="Y", author_id=author.id, user_id=executor.id, completed_at=datetime.now(timezone.utc)
        )
        session.add_all([task1, task2])
        await session.commit()

        service = AnalyticsService(TaskRepository(session))
        result = await service.get_dashboard()

        assert result["executor_completion"] == []

    @pytest.mark.asyncio
    async def test_results_sorted_by_on_time_rate_descending(self, session):
        author = await make_user(session)
        exec_bad = await make_user(session, username=f"bad_{uuid.uuid4().hex[:6]}", password="pass123")
        exec_good = await make_user(session, username=f"good_{uuid.uuid4().hex[:6]}", password="pass123")
        deadline = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

        await make_task_with_completion(session, author, deadline, deadline + timedelta(hours=5), user_id=exec_bad.id)
        await make_task_with_completion(session, author, deadline, deadline - timedelta(hours=5), user_id=exec_good.id)

        service = AnalyticsService(TaskRepository(session))
        result = await service.get_dashboard()

        usernames_in_order = [s["username"] for s in result["executor_completion"]]
        assert usernames_in_order == [exec_good.username, exec_bad.username]


class TestProjectOverdueStats:
    @pytest.mark.asyncio
    async def test_average_overdue_computed_correctly(self, session):
        author = await make_user(session)
        project = ProjectModel(name="Проект", owner_id=author.id)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        deadline = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        # Просрочка на 2 дня и на 4 дня -> средняя 3 дня
        await make_task_with_completion(session, author, deadline, deadline + timedelta(days=2), project_id=project.id)
        await make_task_with_completion(session, author, deadline, deadline + timedelta(days=4), project_id=project.id)

        service = AnalyticsService(TaskRepository(session))
        result = await service.get_dashboard()

        stats = result["project_overdue"][0]
        assert stats["project_name"] == "Проект"
        assert stats["completed_late"] == 2
        assert stats["avg_overdue_days"] == 3.0

    @pytest.mark.asyncio
    async def test_on_time_tasks_do_not_count_as_late(self, session):
        author = await make_user(session)
        project = ProjectModel(name="Проект", owner_id=author.id)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        deadline = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        await make_task_with_completion(session, author, deadline, deadline - timedelta(hours=1), project_id=project.id)

        service = AnalyticsService(TaskRepository(session))
        result = await service.get_dashboard()

        stats = result["project_overdue"][0]
        assert stats["completed_late"] == 0
        assert stats["avg_overdue_days"] == 0.0
        assert stats["total_completed"] == 1

    @pytest.mark.asyncio
    async def test_task_without_project_excluded(self, session):
        author = await make_user(session)
        deadline = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        await make_task_with_completion(session, author, deadline, deadline + timedelta(days=1), project_id=None)

        service = AnalyticsService(TaskRepository(session))
        result = await service.get_dashboard()

        assert result["project_overdue"] == []

    @pytest.mark.asyncio
    async def test_multiple_projects_separated(self, session):
        author = await make_user(session)
        project1 = ProjectModel(name="Проблемный", owner_id=author.id)
        project2 = ProjectModel(name="Хороший", owner_id=author.id)
        session.add_all([project1, project2])
        await session.commit()
        await session.refresh(project1)
        await session.refresh(project2)

        deadline = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        await make_task_with_completion(
            session, author, deadline, deadline + timedelta(days=10), project_id=project1.id
        )
        await make_task_with_completion(
            session, author, deadline, deadline - timedelta(hours=1), project_id=project2.id
        )

        service = AnalyticsService(TaskRepository(session))
        result = await service.get_dashboard()

        by_name = {s["project_name"]: s for s in result["project_overdue"]}
        assert by_name["Проблемный"]["avg_overdue_days"] == 10.0
        assert by_name["Хороший"]["avg_overdue_days"] == 0.0

    @pytest.mark.asyncio
    async def test_sorted_by_avg_overdue_descending(self, session):
        author = await make_user(session)
        project_worse = ProjectModel(name="Хуже", owner_id=author.id)
        project_better = ProjectModel(name="Лучше", owner_id=author.id)
        session.add_all([project_worse, project_better])
        await session.commit()
        await session.refresh(project_worse)
        await session.refresh(project_better)

        deadline = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        await make_task_with_completion(
            session, author, deadline, deadline + timedelta(days=1), project_id=project_better.id
        )
        await make_task_with_completion(
            session, author, deadline, deadline + timedelta(days=20), project_id=project_worse.id
        )

        service = AnalyticsService(TaskRepository(session))
        result = await service.get_dashboard()

        names_in_order = [s["project_name"] for s in result["project_overdue"]]
        assert names_in_order == ["Хуже", "Лучше"]


class TestEmptyDashboard:
    @pytest.mark.asyncio
    async def test_no_tasks_returns_empty_lists(self, session):
        service = AnalyticsService(TaskRepository(session))
        result = await service.get_dashboard()

        assert result == {"executor_completion": [], "project_overdue": []}
