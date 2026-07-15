# tests/test_notifications_extra.py
"""
Дополнительные тесты для src/services/notifications.py.

tests/test_notifications.py уже покрывает "одиночного" получателя (task.user).
Здесь закрываются ветки, которых там не было:
- уведомление всей группе (task.group) для notify_task_assigned и notify_task_updated;
- дедупликация групповых уведомлений;
- логирование неуспешной отправки (бот бросает исключение);
- отсутствие получателей (нет ни user, ни group / пустая группа).
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.group import GroupModel
from src.models.notification_log import NotificationLogModel
from src.models.notification_settings import NotificationSettingsModel as NotificationSettings
from src.models.task import SpisokModel, TaskStatus
from src.services.notifications import (
    notify_comment_added,
    notify_task_assigned,
    notify_task_updated,
)
from tests.conftest import make_user


def unique_tg_id() -> int:
    return int(uuid.uuid4().int % 10**9)


@pytest.fixture
def mock_bot(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    test_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    with (
        patch("src.services.notifications.get_bot") as mock_get_bot,
        patch("src.services.notifications.get_session_maker", return_value=test_session_maker),
    ):
        bot = AsyncMock()
        bot.send_message = AsyncMock()
        mock_get_bot.return_value = bot
        yield bot


async def make_group_with_members(session, member_count=2, author=None):
    group = GroupModel(name=f"group_{uuid.uuid4().hex[:6]}")
    session.add(group)
    await session.commit()
    await session.refresh(group)

    members = []
    for i in range(member_count):
        user = await make_user(session, username=f"member_{uuid.uuid4().hex[:6]}", password="pass123")
        user.telegram_id = unique_tg_id()
        group.users.append(user)
        members.append(user)

    if author:
        group.users.append(author)

    await session.commit()
    for m in members:
        await session.refresh(m)
    await session.refresh(group)
    return group, members


async def make_settings(session, user_id: int, **overrides):
    settings = NotificationSettings(
        user_id=user_id,
        notify_task_assigned=overrides.get("notify_task_assigned", True),
        notify_task_updated=overrides.get("notify_task_updated", True),
    )
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    return settings


async def get_logs(session, notification_type=None):
    query = select(NotificationLogModel)
    if notification_type:
        query = query.where(NotificationLogModel.notification_type == notification_type)
    result = await session.execute(query)
    return result.scalars().all()


class TestNotifyTaskAssignedGroup:
    @pytest.mark.asyncio
    async def test_sends_to_all_group_members(self, session, mock_bot):
        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        group, members = await make_group_with_members(session, member_count=2)

        task = SpisokModel(title="Групповая задача", author_id=author.id, group_id=group.id, status=TaskStatus.todo)
        session.add(task)
        await session.commit()
        await session.refresh(task)

        await notify_task_assigned(task.id)

        assert mock_bot.send_message.call_count == 2
        sent_to = {c.kwargs["chat_id"] for c in mock_bot.send_message.call_args_list}
        assert sent_to == {members[0].telegram_id, members[1].telegram_id}

    @pytest.mark.asyncio
    async def test_excludes_author_from_group(self, session, mock_bot):
        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        author.telegram_id = unique_tg_id()
        await session.commit()
        group, members = await make_group_with_members(session, member_count=1, author=author)

        task = SpisokModel(title="Групповая задача", author_id=author.id, group_id=group.id, status=TaskStatus.todo)
        session.add(task)
        await session.commit()
        await session.refresh(task)

        await notify_task_assigned(task.id)

        sent_to = {c.kwargs["chat_id"] for c in mock_bot.send_message.call_args_list}
        assert author.telegram_id not in sent_to
        assert members[0].telegram_id in sent_to

    @pytest.mark.asyncio
    async def test_respects_disabled_settings_per_member(self, session, mock_bot):
        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        group, members = await make_group_with_members(session, member_count=2)
        await make_settings(session, members[0].id, notify_task_assigned=False)

        task = SpisokModel(title="Групповая задача", author_id=author.id, group_id=group.id, status=TaskStatus.todo)
        session.add(task)
        await session.commit()
        await session.refresh(task)

        await notify_task_assigned(task.id)

        sent_to = {c.kwargs["chat_id"] for c in mock_bot.send_message.call_args_list}
        assert members[0].telegram_id not in sent_to
        assert members[1].telegram_id in sent_to

    @pytest.mark.asyncio
    async def test_no_members_no_send(self, session, mock_bot):
        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        group, _ = await make_group_with_members(session, member_count=0)

        task = SpisokModel(title="Пустая группа", author_id=author.id, group_id=group.id, status=TaskStatus.todo)
        session.add(task)
        await session.commit()
        await session.refresh(task)

        await notify_task_assigned(task.id)

        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_within_1h_for_group(self, session, mock_bot):
        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        group, members = await make_group_with_members(session, member_count=1)

        task = SpisokModel(title="Групповая задача", author_id=author.id, group_id=group.id, status=TaskStatus.todo)
        session.add(task)
        await session.commit()
        await session.refresh(task)

        await notify_task_assigned(task.id)
        assert mock_bot.send_message.call_count == 1

        mock_bot.send_message.reset_mock()
        await notify_task_assigned(task.id)
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_logs_failure_for_individual_recipient(self, session, mock_bot):
        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        author.telegram_id = unique_tg_id()
        await session.commit()

        mock_bot.send_message.side_effect = Exception("Forbidden: bot blocked by user")

        task = SpisokModel(title="Задача", author_id=author.id, user_id=None, status=TaskStatus.todo)
        # Прямое назначение пользователю, не группе:
        user = await make_user(session, username=f"exec_{uuid.uuid4().hex[:6]}", password="pass123")
        user.telegram_id = unique_tg_id()
        task.user_id = user.id
        session.add(task)
        await session.commit()
        await session.refresh(task)

        await notify_task_assigned(task.id)

        logs = await get_logs(session, "task_assigned")
        assert len(logs) == 1
        assert logs[0].success is False
        assert "bot blocked by user" in logs[0].error

    @pytest.mark.asyncio
    async def test_includes_description_for_single_recipient(self, session, mock_bot):
        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        user = await make_user(session, username=f"exec_{uuid.uuid4().hex[:6]}", password="pass123")
        user.telegram_id = unique_tg_id()
        await session.commit()

        task = SpisokModel(
            title="Задача",
            description="Важные детали задачи",
            author_id=author.id,
            user_id=user.id,
            status=TaskStatus.todo,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

        await notify_task_assigned(task.id)

        text = mock_bot.send_message.call_args.kwargs["text"]
        assert "Важные детали задачи" in text

    @pytest.mark.asyncio
    async def test_group_send_failure_is_logged_and_does_not_stop_other_members(self, session, mock_bot):
        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        group, members = await make_group_with_members(session, member_count=2)

        task = SpisokModel(
            title="Групповая",
            description="Описание группового задания",
            author_id=author.id,
            group_id=group.id,
            status=TaskStatus.todo,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

        mock_bot.send_message.side_effect = Exception("Timed out")

        await notify_task_assigned(task.id)

        logs = await get_logs(session, "group_task_assigned")
        assert len(logs) == 2
        assert all(log.success is False for log in logs)
        assert all("Timed out" in log.error for log in logs)


class TestNotifyTaskUpdatedGroup:
    @pytest.mark.asyncio
    async def test_sends_to_group_members_on_change(self, session, mock_bot):
        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        group, members = await make_group_with_members(session, member_count=2)

        task = SpisokModel(title="Групповая", author_id=author.id, group_id=group.id, status=TaskStatus.todo)
        session.add(task)
        await session.commit()
        await session.refresh(task)

        await notify_task_updated(task.id, changed_fields={"title": "Новое название"})

        assert mock_bot.send_message.call_count == 2

    @pytest.mark.asyncio
    async def test_no_recipients_when_no_user_and_no_group(self, session, mock_bot):
        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        task = SpisokModel(title="Ничья задача", author_id=author.id, status=TaskStatus.todo)
        session.add(task)
        await session.commit()
        await session.refresh(task)

        await notify_task_updated(task.id, changed_fields={"title": "X"})

        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_task_id_is_noop(self, session, mock_bot):
        await notify_task_updated(None, changed_fields={"title": "X"})
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_nonexistent_task_is_noop(self, session, mock_bot):
        await notify_task_updated(999999, changed_fields={"title": "X"})
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_logs_failure_when_bot_raises(self, session, mock_bot):
        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        user = await make_user(session, username=f"exec_{uuid.uuid4().hex[:6]}", password="pass123")
        user.telegram_id = unique_tg_id()
        await session.commit()

        task = SpisokModel(title="Задача", author_id=author.id, user_id=user.id, status=TaskStatus.todo)
        session.add(task)
        await session.commit()
        await session.refresh(task)

        mock_bot.send_message.side_effect = Exception("Bad Request: chat not found")

        await notify_task_updated(task.id, changed_fields={"title": "X"})

        logs = await get_logs(session, "task_updated")
        assert len(logs) == 1
        assert logs[0].success is False
        assert "chat not found" in logs[0].error

    @pytest.mark.asyncio
    async def test_status_label_mapping(self, session, mock_bot):
        """Все ключи статуса переводятся на русский, а не отдаются как raw enum value."""
        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        user = await make_user(session, username=f"exec_{uuid.uuid4().hex[:6]}", password="pass123")
        user.telegram_id = unique_tg_id()
        await session.commit()

        task = SpisokModel(title="Задача", author_id=author.id, user_id=user.id, status=TaskStatus.todo)
        session.add(task)
        await session.commit()
        await session.refresh(task)

        await notify_task_updated(task.id, changed_fields={"status": "in_progress"})

        text = mock_bot.send_message.call_args.kwargs["text"]
        assert "В работе" in text


class TestNotifyCommentAddedExtra:
    @pytest.mark.asyncio
    async def test_logs_error_but_does_not_raise_when_bot_fails(self, session, mock_bot):
        """Ошибка отправки одному получателю не должна ронять всю функцию."""
        from src.models.comment import CommentModel

        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        author.telegram_id = unique_tg_id()
        user = await make_user(session, username=f"exec_{uuid.uuid4().hex[:6]}", password="pass123")
        commenter = await make_user(session, username=f"comm_{uuid.uuid4().hex[:6]}", password="pass123")
        await session.commit()

        task = SpisokModel(title="Задача", author_id=author.id, user_id=user.id, status=TaskStatus.todo)
        session.add(task)
        await session.commit()
        await session.refresh(task)

        comment = CommentModel(content="Тест", task_id=task.id, user_id=commenter.id)
        session.add(comment)
        await session.commit()
        await session.refresh(comment)

        mock_bot.send_message.side_effect = Exception("Timed out")

        # Не должно кидать исключение наружу
        await notify_comment_added(comment.id)

    @pytest.mark.asyncio
    async def test_nonexistent_comment_is_noop(self, session, mock_bot):
        await notify_comment_added(comment_id=999999)
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_recipients_when_nobody_has_telegram_id(self, session, mock_bot):
        from src.models.comment import CommentModel

        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        user = await make_user(session, username=f"exec_{uuid.uuid4().hex[:6]}", password="pass123")
        commenter = await make_user(session, username=f"comm_{uuid.uuid4().hex[:6]}", password="pass123")
        await session.commit()

        task = SpisokModel(title="Задача", author_id=author.id, user_id=user.id, status=TaskStatus.todo)
        session.add(task)
        await session.commit()
        await session.refresh(task)

        comment = CommentModel(content="Тест", task_id=task.id, user_id=commenter.id)
        session.add(comment)
        await session.commit()
        await session.refresh(comment)

        await notify_comment_added(comment.id)

        mock_bot.send_message.assert_not_called()


class TestNotifyTaskAssignedPush:
    @pytest.mark.asyncio
    async def test_push_sent_regardless_of_telegram_id(self, session, mock_bot):
        """
        До рефакторинга вся ветка (включая push) требовала task.user.telegram_id —
        пользователь, подписанный ТОЛЬКО на веб-push (без Telegram), не получал
        вообще ничего. Теперь push отправляется независимо от Telegram.
        """
        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        user_without_telegram = await make_user(
            session, username=f"pushonly_{uuid.uuid4().hex[:6]}", password="pass123"
        )
        assert user_without_telegram.telegram_id is None

        task = SpisokModel(
            title="Задача для push-пользователя",
            author_id=author.id,
            user_id=user_without_telegram.id,
            status=TaskStatus.todo,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

        with patch("src.services.push_service.send_push_to_user", new_callable=AsyncMock) as mock_push:
            await notify_task_assigned(task.id)

        mock_push.assert_called_once()
        assert mock_push.call_args.args[1] == user_without_telegram.id

    @pytest.mark.asyncio
    async def test_telegram_and_push_both_attempted_when_telegram_id_present(self, session, mock_bot):
        author = await make_user(session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123")
        user = await make_user(session, username=f"user_{uuid.uuid4().hex[:6]}", password="pass123")
        user.telegram_id = unique_tg_id()
        await session.commit()

        task = SpisokModel(title="X", author_id=author.id, user_id=user.id, status=TaskStatus.todo)
        session.add(task)
        await session.commit()
        await session.refresh(task)

        with patch("src.services.push_service.send_push_to_user", new_callable=AsyncMock) as mock_push:
            await notify_task_assigned(task.id)

        mock_bot.send_message.assert_called_once()
        mock_push.assert_called_once()
