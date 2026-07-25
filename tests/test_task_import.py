# tests/test_task_import.py
"""
Тесты TaskService.import_tasks (уровень сервиса, реальная БД через session)
и POST /tasks/import (уровень HTTP, через auth_client).

Парсинг файла (CSV/Excel, кодировки, форматы) уже покрыт в
test_task_import_parser.py — здесь проверяется то, что происходит ПОСЛЕ
парсинга: создание задач в БД, права, project_id, ответ API.
"""

import io

import pytest
from openpyxl import Workbook

from src.models.task import SpisokModel, TaskStatus
from src.repositories.groups_repository import GroupRepository
from src.repositories.tag_repository import TagRepository
from src.repositories.task_repository import TaskRepository
from src.repositories.users_repository import UserRepository
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


def xlsx_bytes(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


class TestImportTasksService:
    @pytest.mark.asyncio
    async def test_creates_tasks_in_db(self, session):
        user = await make_user(session)
        service = build_service(session)
        content = "Название,Приоритет\nЗадача 1,high\nЗадача 2,low\n".encode("utf-8-sig")

        summary = await service.import_tasks(filename="tasks.csv", content=content, current_user=user)

        assert summary.created == 2
        from sqlalchemy import select

        result = await session.execute(select(SpisokModel).where(SpisokModel.author_id == user.id))
        titles = {t.title for t in result.scalars().all()}
        assert titles == {"Задача 1", "Задача 2"}

    @pytest.mark.asyncio
    async def test_imported_tasks_have_correct_author_and_defaults(self, session):
        user = await make_user(session)
        service = build_service(session)
        content = "Название\nЗадача\n".encode("utf-8-sig")

        await service.import_tasks(filename="tasks.csv", content=content, current_user=user)

        from sqlalchemy import select

        result = await session.execute(select(SpisokModel).where(SpisokModel.title == "Задача"))
        task = result.scalar_one()
        assert task.author_id == user.id
        assert task.status == TaskStatus.todo
        assert task.priority.value == "medium"

    @pytest.mark.asyncio
    async def test_project_id_applied_to_all_created_tasks(self, session):
        from src.models.project import ProjectModel

        manager = await make_user(session)
        project = ProjectModel(name="Проект импорта", owner_id=manager.id)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        service = build_service(session)
        content = "Название\nЗадача 1\nЗадача 2\n".encode("utf-8-sig")

        await service.import_tasks(filename="tasks.csv", content=content, current_user=manager, project_id=project.id)

        from sqlalchemy import select

        result = await session.execute(select(SpisokModel).where(SpisokModel.project_id == project.id))
        assert len(result.scalars().all()) == 2

    @pytest.mark.asyncio
    async def test_summary_reports_errors_for_skipped_rows(self, session):
        user = await make_user(session)
        service = build_service(session)
        content = "Название\nЗадача 1\n\nЗадача 2\n".encode("utf-8-sig")

        summary = await service.import_tasks(filename="tasks.csv", content=content, current_user=user)

        assert summary.created == 2
        assert len(summary.errors) == 1

    @pytest.mark.asyncio
    async def test_summary_reports_warnings_for_bad_priority(self, session):
        user = await make_user(session)
        service = build_service(session)
        content = "Название,Приоритет\nЗадача,невалидный\n".encode("utf-8-sig")

        summary = await service.import_tasks(filename="tasks.csv", content=content, current_user=user)

        assert summary.created == 1
        assert len(summary.warnings) == 1

    @pytest.mark.asyncio
    async def test_past_deadline_is_allowed(self, session):
        """В отличие от add_task (создание одной задачи через форму), импорт
        не отклоняет дедлайны в прошлом — типичный сценарий переноса
        исторических данных из другого трекера."""
        user = await make_user(session)
        service = build_service(session)
        content = "Название,Дедлайн\nСтарая задача,01.01.2020\n".encode("utf-8-sig")

        summary = await service.import_tasks(filename="tasks.csv", content=content, current_user=user)

        assert summary.created == 1
        assert len(summary.errors) == 0

    @pytest.mark.asyncio
    async def test_invalid_file_format_raises_400(self, session):
        from fastapi import HTTPException

        user = await make_user(session)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.import_tasks(filename="tasks.txt", content=b"whatever", current_user=user)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_title_column_raises_400(self, session):
        from fastapi import HTTPException

        user = await make_user(session)
        service = build_service(session)
        content = "Дедлайн,Приоритет\n01.01.2030,high\n".encode("utf-8-sig")

        with pytest.raises(HTTPException) as exc:
            await service.import_tasks(filename="tasks.csv", content=content, current_user=user)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_xlsx_import_via_service(self, session):
        user = await make_user(session)
        service = build_service(session)
        content = xlsx_bytes(
            [
                ["Название", "Приоритет"],
                ["Задача из Excel", "critical"],
            ]
        )

        summary = await service.import_tasks(filename="tasks.xlsx", content=content, current_user=user)

        assert summary.created == 1
        from sqlalchemy import select

        result = await session.execute(select(SpisokModel).where(SpisokModel.title == "Задача из Excel"))
        task = result.scalar_one()
        assert task.priority.value == "critical"


class TestImportTasksEndpoint:
    @pytest.mark.asyncio
    async def test_import_csv_via_endpoint(self, auth_client):
        client, user = auth_client
        content = "Название,Приоритет\nЗадача через API,high\n".encode("utf-8-sig")

        resp = await client.post(
            "/tasks/import",
            files={"file": ("tasks.csv", content, "text/csv")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 1
        assert data["errors"] == []

        list_resp = await client.get("/tasks/filter?filter_user_group=author")
        titles = {t["title"] for t in list_resp.json()["items"]}
        assert "Задача через API" in titles

    @pytest.mark.asyncio
    async def test_import_without_auth_returns_401_or_403(self, client):
        content = "Название\nЗадача\n".encode("utf-8-sig")
        resp = await client.post("/tasks/import", files={"file": ("tasks.csv", content, "text/csv")})
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_import_bad_format_returns_400(self, auth_client):
        client, _ = auth_client
        resp = await client.post(
            "/tasks/import",
            files={"file": ("tasks.txt", b"garbage", "text/plain")},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_import_with_project_id_query_param(self, auth_client, engine):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from src.models.project import ProjectModel

        client, user = auth_client
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            project = ProjectModel(name="Проект для импорта", owner_id=user.id)
            sess.add(project)
            await sess.commit()
            await sess.refresh(project)

        content = "Название\nЗадача в проекте\n".encode("utf-8-sig")
        resp = await client.post(
            f"/tasks/import?project_id={project.id}",
            files={"file": ("tasks.csv", content, "text/csv")},
        )
        assert resp.status_code == 200
        assert resp.json()["created"] == 1
