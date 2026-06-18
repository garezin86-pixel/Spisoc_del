# tests/test_notifications.py
"""
3.3 Моки для Telegram-бота.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.task import SpisokModel, TaskStatus
from src.models.comment import CommentModel
from src.models.notification_settings import (
    NotificationSettingsModel as NotificationSettings,
)
from src.services.notifications import (
    notify_task_assigned,
    notify_task_updated,
    notify_comment_added,
)
from src.utils.reminders import notify_overdue, remind_deadline_1h, remind_deadline_24h
from tests.conftest import make_user


def unique_tg_id() -> int:
    """Уникальный telegram_id для каждого теста."""
    return int(uuid.uuid4().int % 10**9)


@pytest.fixture
def mock_bot(engine):  # ← добавили engine
    """Мокает get_bot И подменяет session_maker на тестовый"""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    test_session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    with (
        patch("src.services.notifications.get_bot") as mock_get_bot,
        patch(
            "src.services.notifications.get_session_maker",
            return_value=test_session_maker,
        ),
    ):
        bot = AsyncMock()
        bot.send_message = AsyncMock()
        mock_get_bot.return_value = bot
        yield bot


@pytest.fixture
def mock_reminders_bot(engine):  # ← добавили engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    test_session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    with (
        patch("src.services.reminders.service.get_bot") as mock_get_bot,
        patch(
            "src.services.reminders.service.get_session_maker",
            return_value=test_session_maker,
        ),
        patch(
            "src.services.notifications.get_session_maker",
            return_value=test_session_maker,
        ),
    ):
        bot = AsyncMock()
        bot.send_message = AsyncMock()
        mock_get_bot.return_value = bot
        yield bot


async def create_notification_settings(session, user_id: int, **kwargs):
    """Создать настройки уведомлений для пользователя"""
    settings = NotificationSettings(
        user_id=user_id,
        notify_deadline_24h=kwargs.get("notify_deadline_24h", True),
        notify_deadline_1h=kwargs.get("notify_deadline_1h", True),
        notify_overdue=kwargs.get("notify_overdue", True),
        weekly_report_enabled=kwargs.get("weekly_report_enabled", True),
        notify_task_assigned=kwargs.get("notify_task_assigned", True),
        notify_task_updated=kwargs.get("notify_task_updated", True),
        notify_comment=kwargs.get("notify_comment", True),
    )
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    return settings


async def create_task_with_users(session, same_user=False):
    tg_author = unique_tg_id()
    tg_user = unique_tg_id() if not same_user else tg_author

    author = await make_user(
        session, username=f"author_{uuid.uuid4().hex[:6]}", password="pass123"
    )
    author.telegram_id = tg_author
    await session.commit()
    await session.refresh(author)

    # Создаём настройки для автора
    await create_notification_settings(session, author.id)

    if same_user:
        user = author
    else:
        user = await make_user(
            session, username=f"executor_{uuid.uuid4().hex[:6]}", password="pass123"
        )
        user.telegram_id = tg_user
        await session.commit()
        await session.refresh(user)
        # Создаём настройки для исполнителя
        await create_notification_settings(session, user.id)

    task = SpisokModel(
        title="Тестовая задача",
        author_id=author.id,
        user_id=user.id,
        status=TaskStatus.todo,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task, author, user


async def create_comment(session, task, commenter_tg=None):
    commenter = await make_user(
        session, username=f"comm_{uuid.uuid4().hex[:6]}", password="pass123"
    )
    if commenter_tg is not None:
        commenter.telegram_id = commenter_tg
        await session.commit()
        await session.refresh(commenter)

    # Создаём настройки для комментатора
    await create_notification_settings(session, commenter.id)

    comment = CommentModel(content="Тест", task_id=task.id, user_id=commenter.id)
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    return comment, commenter


class TestNotifyTaskAssigned:
    @pytest.mark.asyncio
    async def test_sends_to_executor(self, session, mock_bot):
        task, author, user = await create_task_with_users(session)
        user.telegram_id = 123456789
        await session.commit()
        await session.refresh(user)

        await notify_task_assigned(task.id)

        # Проверяем, что бот был вызван
        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        assert call_args.kwargs["chat_id"] == user.telegram_id

    @pytest.mark.asyncio
    async def test_not_sent_when_author_is_executor(self, session, mock_bot):
        task, author, _ = await create_task_with_users(session, same_user=True)
        author.telegram_id = 123456789
        await session.commit()
        await session.refresh(author)

        await notify_task_assigned(task.id)

        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_sent_without_telegram_id(self, session, mock_bot):
        task, author, user = await create_task_with_users(session)
        user.telegram_id = None
        await session.commit()

        await notify_task_assigned(task.id)

        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_sent_for_nonexistent_task(self, session, mock_bot):
        await notify_task_assigned(task_id=999999)
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_contains_task_title(self, session, mock_bot):
        task, _, _ = await create_task_with_users(session)
        task.title = "Важная задача"
        await session.commit()
        await session.refresh(task)

        await notify_task_assigned(task.id)

        assert mock_bot.send_message.called
        text = mock_bot.send_message.call_args.kwargs["text"]
        assert "Важная задача" in text


class TestNotifyTaskUpdated:
    @pytest.mark.asyncio
    async def test_sends_on_title_change(self, session, mock_bot):
        task, _, user = await create_task_with_users(session)

        await notify_task_updated(task.id, changed_fields={"title": "Новое"})

        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_sends_to_executor_not_editor(self, session, mock_bot):
        task, author, user = await create_task_with_users(session)
        author.telegram_id = 111111111
        user.telegram_id = 222222222
        await session.commit()
        await session.refresh(author)
        await session.refresh(user)

        await notify_task_updated(
            task.id,
            changed_fields={"title": "X"},
            editor_telegram_id=author.telegram_id,
        )

        assert mock_bot.send_message.called
        assert mock_bot.send_message.call_args.kwargs["chat_id"] == user.telegram_id

    @pytest.mark.asyncio
    async def test_not_sent_when_editor_is_executor(self, session, mock_bot):
        task, _, user = await create_task_with_users(session, same_user=True)

        await notify_task_updated(
            task.id, changed_fields={"title": "X"}, editor_telegram_id=user.telegram_id
        )

        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_sent_when_no_changes(self, session, mock_bot):
        task, _, _ = await create_task_with_users(session)

        await notify_task_updated(task.id, changed_fields={})

        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_contains_status(self, session, mock_bot):
        task, _, _ = await create_task_with_users(session)

        await notify_task_updated(
            task.id,
            changed_fields={"status": TaskStatus.done},
        )

        assert mock_bot.send_message.called

        text = mock_bot.send_message.call_args.kwargs["text"]
        assert "Выполнено" in text


class TestNotifyCommentAdded:
    @pytest.mark.asyncio
    async def test_sends_to_author(self, session, mock_bot):
        task, author, user = await create_task_with_users(session)
        author.telegram_id = 123456789
        user.telegram_id = 987654321
        await session.commit()
        await session.refresh(author)
        await session.refresh(user)

        comment, commenter = await create_comment(session, task, commenter_tg=555555555)

        await notify_comment_added(comment.id)

        # Проверяем, что автор получил уведомление
        assert mock_bot.send_message.called
        sent_to = {
            call.kwargs["chat_id"] for call in mock_bot.send_message.call_args_list
        }
        assert author.telegram_id in sent_to

    @pytest.mark.asyncio
    async def test_sends_to_executor(self, session, mock_bot):
        task, author, user = await create_task_with_users(session)
        user.telegram_id = 987654321
        await session.commit()
        await session.refresh(user)

        comment, _ = await create_comment(session, task, commenter_tg=unique_tg_id())

        await notify_comment_added(comment.id)

        assert mock_bot.send_message.called
        sent_to = {
            call.kwargs["chat_id"] for call in mock_bot.send_message.call_args_list
        }
        assert user.telegram_id in sent_to

    @pytest.mark.asyncio
    async def test_not_sent_to_commenter(self, session, mock_bot):
        """Автор комментария не получает уведомление."""
        task, author, user = await create_task_with_users(session)

        # Комментирует сам автор задачи
        comment = CommentModel(content="Тест", task_id=task.id, user_id=author.id)
        session.add(comment)
        await session.commit()
        await session.refresh(comment)

        await notify_comment_added(comment.id)

        sent_to = {
            call.kwargs["chat_id"] for call in mock_bot.send_message.call_args_list
        }
        assert author.telegram_id not in sent_to

    @pytest.mark.asyncio
    async def test_message_contains_content(self, session, mock_bot):
        task, _, _ = await create_task_with_users(session)
        comment, _ = await create_comment(session, task, commenter_tg=unique_tg_id())
        comment.content = "Особый текст"
        await session.commit()
        await session.refresh(comment)

        await notify_comment_added(comment.id)

        assert mock_bot.send_message.called
        texts = [call.kwargs["text"] for call in mock_bot.send_message.call_args_list]
        assert any("Особый текст" in text for text in texts)

    @pytest.mark.asyncio
    async def test_not_sent_for_nonexistent_comment(self, session, mock_bot):
        await notify_comment_added(comment_id=999999)
        mock_bot.send_message.assert_not_called()


# Отдельная функция для тестового запуска уведомлений
@pytest.mark.asyncio
async def test_notifications(mock_reminders_bot):
    """Тестовый запуск уведомлений"""
    print("Testing reminders...")

    # Тест 24h напоминаний
    await remind_deadline_24h()

    # Тест 1h напоминаний
    await remind_deadline_1h()

    # Тест просроченных
    await notify_overdue()

    print("Done!")
