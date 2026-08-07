import pytest

from src.models.enums import RecurrenceRule
from src.models.task import SpisokModel, TaskStatus
from src.repositories.audit_repository import AuditRepository
from src.services.activity_service import ActivityService
from tests.conftest import make_user


async def make_task(session, author, **kwargs):
    task = SpisokModel(title=kwargs.pop("title", "Задача"), author_id=author.id, **kwargs)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


class TestActivityFeed:
    @pytest.mark.asyncio
    async def test_feed_includes_task_create_and_update(self, session):
        author = await make_user(session)
        session.info["audit_user_id"] = author.id

        task = await make_task(session, author, title="Купить молоко", status=TaskStatus.todo)

        task.status = TaskStatus.done
        await session.commit()

        service = ActivityService(AuditRepository(session), session)
        feed, total = await service.get_feed(offset=0, limit=50)

        assert total == 2
        actions = [item["action"] for item in feed]
        assert "create" in actions
        assert "update" in actions
        for item in feed:
            assert item["task_id"] == task.id
            assert item["task_title"] == "Купить молоко"
            assert item["username"] == author.username

        update_item = next(item for item in feed if item["action"] == "update")
        status_change = next(c for c in update_item["changes"] if c["field"] == "status")
        assert status_change["old"] == "Новые"
        assert status_change["new"] == "Готово"

    @pytest.mark.asyncio
    async def test_feed_includes_comments_with_task_title(self, session):
        from src.models.comment import CommentModel

        author = await make_user(session)
        session.info["audit_user_id"] = author.id
        task = await make_task(session, author, title="Позвонить клиенту", status=TaskStatus.todo)

        comment = CommentModel(content="Уже позвонил, ждём ответа", task_id=task.id, user_id=author.id)
        session.add(comment)
        await session.commit()

        service = ActivityService(AuditRepository(session), session)
        feed, total = await service.get_feed(offset=0, limit=50)

        comment_item = next(item for item in feed if item["entity_type"] == "comments")
        assert comment_item["task_title"] == "Позвонить клиенту"
        assert comment_item["comment_preview"] == "Уже позвонил, ждём ответа"

    @pytest.mark.asyncio
    async def test_feed_pagination_and_total(self, session):
        author = await make_user(session)
        session.info["audit_user_id"] = author.id
        for i in range(5):
            await make_task(session, author, title=f"Задача {i}", status=TaskStatus.todo)

        service = ActivityService(AuditRepository(session), session)
        feed, total = await service.get_feed(offset=0, limit=2)

        assert total == 5
        assert len(feed) == 2

    @pytest.mark.asyncio
    async def test_no_recurrence_field_noise(self, session):
        """recurrence_rule field should still be labeled if it changes (sanity check for _FIELD_LABELS)."""
        author = await make_user(session)
        session.info["audit_user_id"] = author.id
        task = await make_task(session, author, recurrence_rule=RecurrenceRule.none, status=TaskStatus.todo)

        task.recurrence_rule = RecurrenceRule.daily
        await session.commit()

        service = ActivityService(AuditRepository(session), session)
        feed, _ = await service.get_feed(offset=0, limit=50)
        update_item = next(item for item in feed if item["action"] == "update")
        rec_change = next(c for c in update_item["changes"] if c["field"] == "recurrence_rule")
        assert rec_change["label"] == "повторение"
