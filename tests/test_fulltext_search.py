# tests/test_fulltext_search.py
"""
Тесты полнотекстового поиска в TaskRepository.

Юнит-тесты гоняются на SQLite (см. tests/conftest.py), поэтому реальный
Postgres tsvector-путь здесь не выполняется — только ILIKE fallback.
Корректность SQL для ветки PostgreSQL проверяется отдельно, без реального
выполнения (compile() запроса + проверка наличия to_tsvector/plainto_tsquery
в сгенерированном SQL), через мок диалекта сессии.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.models.task import SpisokModel
from src.repositories.task_repository import TaskRepository
from tests.conftest import make_user


async def make_task(session, author, **kwargs):
    task = SpisokModel(title=kwargs.pop("title", "Задача"), author_id=author.id, **kwargs)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


class TestFulltextSearchSqliteFallback:
    @pytest.mark.asyncio
    async def test_finds_task_by_title_substring(self, session):
        author = await make_user(session)
        await make_task(session, author, title="Подготовить квартальный отчёт")
        await make_task(session, author, title="Купить молоко")
        repo = TaskRepository(session)

        tasks, total = await repo.get_filtered_tasks_with_total(user_id=author.id, offset=0, limit=20, search="отчёт")

        assert total == 1
        assert tasks[0].title == "Подготовить квартальный отчёт"

    @pytest.mark.asyncio
    async def test_finds_task_by_description(self, session):
        author = await make_user(session)
        await make_task(session, author, title="X", description="Важные детали по проекту Аврора")
        await make_task(session, author, title="Y", description="Ничего особенного")
        repo = TaskRepository(session)

        tasks, total = await repo.get_filtered_tasks_with_total(user_id=author.id, offset=0, limit=20, search="Аврора")

        assert total == 1
        assert tasks[0].title == "X"

    @pytest.mark.asyncio
    async def test_case_insensitive(self, session):
        """
        Проверяем на ASCII-тексте: SQLite ILIKE (в отличие от PostgreSQL)
        не сворачивает регистр кириллицы, только ASCII — это ограничение
        тестового fallback-пути, не продакшена (там всегда PostgreSQL).
        """
        author = await make_user(session)
        await make_task(session, author, title="Important task ABC")
        repo = TaskRepository(session)

        tasks, total = await repo.get_filtered_tasks_with_total(
            user_id=author.id, offset=0, limit=20, search="important"
        )

        assert total == 1

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self, session):
        author = await make_user(session)
        await make_task(session, author, title="Что-то")
        repo = TaskRepository(session)

        tasks, total = await repo.get_filtered_tasks_with_total(
            user_id=author.id, offset=0, limit=20, search="несуществующий-текст-xyz"
        )

        assert total == 0
        assert tasks == []

    @pytest.mark.asyncio
    async def test_no_search_returns_all(self, session):
        author = await make_user(session)
        await make_task(session, author, title="Первая")
        await make_task(session, author, title="Вторая")
        repo = TaskRepository(session)

        tasks, total = await repo.get_filtered_tasks_with_total(user_id=author.id, offset=0, limit=20, search=None)

        assert total == 2

    @pytest.mark.asyncio
    async def test_search_combined_with_tag_filter(self, session):
        from src.models.tag import TagModel

        author = await make_user(session)
        tag = TagModel(name="важное")
        session.add(tag)
        await session.commit()

        task1 = await make_task(session, author, title="Отчёт по проекту")
        task1.tags.append(tag)
        await make_task(session, author, title="Отчёт для налоговой")  # без тега
        await session.commit()

        repo = TaskRepository(session)
        tasks, total = await repo.get_filtered_tasks_with_total(
            user_id=author.id, offset=0, limit=20, search="Отчёт", tag_id=tag.id
        )

        assert total == 1
        assert tasks[0].id == task1.id


class TestFulltextSearchPostgresSqlGeneration:
    """
    Не выполняет запрос по-настоящему (нет Postgres в тестовом окружении) —
    проверяет только, что для диалекта postgresql строится ожидаемый SQL
    с to_tsvector/plainto_tsquery, а не ILIKE.
    """

    @pytest.mark.asyncio
    async def test_uses_tsvector_for_postgres_dialect(self, session):
        repo = TaskRepository(session)

        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"
        with patch.object(session, "get_bind", return_value=mock_bind):
            query = repo._build_filtered_tasks_query(user_id=1, search="отчёт")

        compiled = str(query.compile(compile_kwargs={"literal_binds": False}))
        assert "to_tsvector" in compiled
        assert "plainto_tsquery" in compiled
        assert "ILIKE" not in compiled.upper().replace("ILIKE", "ILIKE")  # см. ниже explicit check
        assert "ilike" not in compiled.lower()

    @pytest.mark.asyncio
    async def test_uses_ilike_for_sqlite_dialect(self, session):
        repo = TaskRepository(session)

        mock_bind = MagicMock()
        mock_bind.dialect.name = "sqlite"
        with patch.object(session, "get_bind", return_value=mock_bind):
            query = repo._build_filtered_tasks_query(user_id=1, search="отчёт")

        compiled = str(query.compile(compile_kwargs={"literal_binds": False}))
        assert "to_tsvector" not in compiled
        assert "like" in compiled.lower()

    @pytest.mark.asyncio
    async def test_no_search_skips_fulltext_branch_entirely(self, session):
        repo = TaskRepository(session)

        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"
        with patch.object(session, "get_bind", return_value=mock_bind):
            query = repo._build_filtered_tasks_query(user_id=1, search=None)

        compiled = str(query.compile(compile_kwargs={"literal_binds": False}))
        assert "to_tsvector" not in compiled
