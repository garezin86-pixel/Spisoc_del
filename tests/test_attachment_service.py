# tests/test_attachment_service.py
"""
Тесты для src/services/attachment_service.py.

Особое внимание — правильности get_download_url: этот метод определяет,
попадёт ли пользователь на приватный файл в обход прав доступа (важно
после исправления дыры с публичной раздачей вложений через StaticFiles).
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from src.models.attachment_model import AttachmentModel
from src.models.task import SpisokModel
from src.repositories.attachment_repository import AttachmentRepository
from src.repositories.groups_repository import GroupRepository
from src.repositories.task_repository import TaskRepository
from src.services.attachment_service import AttachmentService
from tests.conftest import make_user


async def make_task(session, author_id, user_id=None, title="Задача"):
    task = SpisokModel(title=title, author_id=author_id, user_id=user_id)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def make_attachment(session, task_id, uploaded_by, **kwargs):
    # AttachmentModel.id объявлен как BigInteger — SQLite не считает такую
    # колонку алиасом ROWID и не проставляет автоинкремент сам (в отличие
    # от Postgres, где это работает через BIGSERIAL). Проставляем id вручную,
    # чтобы тесты на in-memory sqlite не падали с NOT NULL constraint failed.
    result = await session.execute(select(func.max(AttachmentModel.id)))
    max_id = result.scalar() or 0

    att = AttachmentModel(
        id=max_id + 1,
        task_id=task_id,
        uploaded_by=uploaded_by,
        filename=kwargs.get("filename", "file.pdf"),
        mime_type=kwargs.get("mime_type", "application/pdf"),
        file_size=kwargs.get("file_size", 1024),
        storage_key=kwargs.get("storage_key"),
        storage_url=kwargs.get("storage_url"),
        telegram_file_id=kwargs.get("telegram_file_id"),
    )
    session.add(att)
    await session.commit()
    await session.refresh(att)
    return att


def build_service(session):
    return AttachmentService(
        task_repo=TaskRepository(session),
        attachment_repo=AttachmentRepository(session),
        session=session,
        group_repo=GroupRepository(session),
    )


class TestCheckAccess:
    @pytest.mark.asyncio
    async def test_raises_for_nonexistent_task(self, session):
        user = await make_user(session, username=f"u_{uuid.uuid4().hex[:6]}")
        service = build_service(session)

        with pytest.raises(HTTPException):
            await service._check_access(999999, user)

    @pytest.mark.asyncio
    async def test_raises_for_user_without_access(self, session):
        author = await make_user(session, username=f"a_{uuid.uuid4().hex[:6]}")
        stranger = await make_user(session, username=f"s_{uuid.uuid4().hex[:6]}")
        task = await make_task(session, author_id=author.id)
        service = build_service(session)

        with pytest.raises(HTTPException):
            await service._check_access(task.id, stranger)

    @pytest.mark.asyncio
    async def test_allows_author(self, session):
        author = await make_user(session, username=f"a_{uuid.uuid4().hex[:6]}")
        task = await make_task(session, author_id=author.id)
        service = build_service(session)

        result = await service._check_access(task.id, author)
        assert result.id == task.id


class TestListForTask:
    @pytest.mark.asyncio
    async def test_returns_attachments_in_order(self, session):
        author = await make_user(session, username=f"a_{uuid.uuid4().hex[:6]}")
        task = await make_task(session, author_id=author.id)
        await make_attachment(session, task.id, author.id, filename="a.pdf")
        await make_attachment(session, task.id, author.id, filename="b.pdf")
        service = build_service(session)

        items = await service.list_for_task(task.id, author)

        assert len(items) == 2
        assert [i.filename for i in items] == ["a.pdf", "b.pdf"]

    @pytest.mark.asyncio
    async def test_denies_stranger(self, session):
        author = await make_user(session, username=f"a_{uuid.uuid4().hex[:6]}")
        stranger = await make_user(session, username=f"s_{uuid.uuid4().hex[:6]}")
        task = await make_task(session, author_id=author.id)
        service = build_service(session)

        with pytest.raises(HTTPException):
            await service.list_for_task(task.id, stranger)


class TestGetDownloadUrl:
    @pytest.mark.asyncio
    async def test_prefers_public_storage_url(self, session):
        """Если storage_url заполнен (R2, публичный бакет) — отдаём его как есть."""
        author = await make_user(session, username=f"a_{uuid.uuid4().hex[:6]}")
        task = await make_task(session, author_id=author.id)
        att = await make_attachment(
            session,
            task.id,
            author.id,
            storage_key="42/file.pdf",
            storage_url="https://r2.example.com/42/file.pdf",
        )
        service = build_service(session)

        url = await service.get_download_url(att.id, author)

        assert url == "https://r2.example.com/42/file.pdf"

    @pytest.mark.asyncio
    async def test_falls_back_to_presigned_when_no_public_url(self, session):
        """storage_key есть, storage_url пуст (приватный R2 бакет) → presigned URL."""
        author = await make_user(session, username=f"a_{uuid.uuid4().hex[:6]}")
        task = await make_task(session, author_id=author.id)
        att = await make_attachment(session, task.id, author.id, storage_key="42/file.pdf", storage_url=None)
        service = build_service(session)

        with patch("src.services.attachment_service.storage") as mock_storage:
            mock_storage.is_configured = True
            mock_storage.get_presigned_url = AsyncMock(return_value="https://r2.example.com/presigned")

            url = await service.get_download_url(att.id, author)

        assert url == "https://r2.example.com/presigned"
        mock_storage.get_presigned_url.assert_called_once_with("42/file.pdf")

    @pytest.mark.asyncio
    async def test_returns_empty_for_local_storage(self, session):
        """Local storage (текущий backend): storage_url всегда None → метод возвращает "" (
        веб использует /download напрямую, не через этот метод)."""
        author = await make_user(session, username=f"a_{uuid.uuid4().hex[:6]}")
        task = await make_task(session, author_id=author.id)
        att = await make_attachment(session, task.id, author.id, storage_key="42/file.pdf", storage_url=None)
        service = build_service(session)

        with patch("src.services.attachment_service.storage") as mock_storage:
            mock_storage.is_configured = True
            mock_storage.get_presigned_url = AsyncMock(return_value="")  # local storage: presigned не поддержан

            url = await service.get_download_url(att.id, author)

        assert url == ""

    @pytest.mark.asyncio
    async def test_denies_access_for_stranger(self, session):
        author = await make_user(session, username=f"a_{uuid.uuid4().hex[:6]}")
        stranger = await make_user(session, username=f"s_{uuid.uuid4().hex[:6]}")
        task = await make_task(session, author_id=author.id)
        att = await make_attachment(session, task.id, author.id, storage_url="https://r2.example.com/f.pdf")
        service = build_service(session)

        with pytest.raises(HTTPException):
            await service.get_download_url(att.id, stranger)

    @pytest.mark.asyncio
    async def test_raises_for_nonexistent_attachment(self, session):
        author = await make_user(session, username=f"a_{uuid.uuid4().hex[:6]}")
        service = build_service(session)

        with pytest.raises(HTTPException):
            await service.get_download_url(999999, author)


class TestDeleteAttachment:
    @pytest.mark.asyncio
    async def test_deletes_record_and_r2_object(self, session):
        author = await make_user(session, username=f"a_{uuid.uuid4().hex[:6]}")
        task = await make_task(session, author_id=author.id)
        att = await make_attachment(session, task.id, author.id, storage_key="42/file.pdf")
        service = build_service(session)

        with patch("src.services.attachment_service.storage") as mock_storage:
            mock_storage.is_configured = True
            mock_storage.delete = AsyncMock()

            await service.delete(att.id, author)

            mock_storage.delete.assert_called_once_with("42/file.pdf")

        result = await AttachmentRepository(session).get_by_id(att.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_succeeds_even_if_r2_delete_fails(self, session):
        """Ошибка чистки R2 не должна мешать удалению записи из БД (иначе "битые" вложения нельзя удалить)."""
        author = await make_user(session, username=f"a_{uuid.uuid4().hex[:6]}")
        task = await make_task(session, author_id=author.id)
        att = await make_attachment(session, task.id, author.id, storage_key="42/file.pdf")
        service = build_service(session)

        with patch("src.services.attachment_service.storage") as mock_storage:
            mock_storage.is_configured = True
            mock_storage.delete = AsyncMock(side_effect=Exception("R2 unavailable"))

            await service.delete(att.id, author)

        result = await AttachmentRepository(session).get_by_id(att.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_denies_stranger(self, session):
        author = await make_user(session, username=f"a_{uuid.uuid4().hex[:6]}")
        stranger = await make_user(session, username=f"s_{uuid.uuid4().hex[:6]}")
        task = await make_task(session, author_id=author.id)
        att = await make_attachment(session, task.id, author.id)
        service = build_service(session)

        with pytest.raises(HTTPException):
            await service.delete(att.id, stranger)

        result = await AttachmentRepository(session).get_by_id(att.id)
        assert result is not None

    @pytest.mark.asyncio
    async def test_delete_raises_for_nonexistent_attachment(self, session):
        author = await make_user(session, username=f"a_{uuid.uuid4().hex[:6]}")
        service = build_service(session)

        with pytest.raises(HTTPException):
            await service.delete(999999, author)

    @pytest.mark.asyncio
    async def test_delete_skips_storage_call_without_storage_key(self, session):
        """Вложение только из бота (telegram_file_id, без storage_key) — R2 не трогаем."""
        author = await make_user(session, username=f"a_{uuid.uuid4().hex[:6]}")
        task = await make_task(session, author_id=author.id)
        att = await make_attachment(session, task.id, author.id, storage_key=None, telegram_file_id="ABC123")
        service = build_service(session)

        with patch("src.services.attachment_service.storage") as mock_storage:
            mock_storage.delete = AsyncMock()
            await service.delete(att.id, author)
            mock_storage.delete.assert_not_called()
