# tests/test_mentions.py
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.comment import CommentModel
from src.models.notification_log import NotificationLogModel
from src.services.notifications import notify_comment_added
from src.utils.mentions import find_mentioned_usernames
from tests.conftest import make_user
from tests.test_notifications import (
    create_notification_settings,
    create_task_with_users,
    unique_tg_id,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_bot(engine):
    """Мокает get_bot И подменяет session_maker на тестовый (как в test_notifications.py)."""
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


class TestFindMentionedUsernames:
    async def test_single_word_username(self):
        assert find_mentioned_usernames("привет @ivan, как дела?", ["ivan", "maria"]) == ["ivan"]

    async def test_multi_word_username_with_space(self):
        """Username может содержать пробел (см. _validate_username) — простой regex \\w+ здесь бы не сработал."""
        usernames = ["Александр", "Александр Александрович"]
        result = find_mentioned_usernames("Привет @Александр Александрович, спасибо!", usernames)
        assert result == ["Александр Александрович"]

    async def test_prefers_longest_match(self):
        usernames = ["Александр", "Александр Александрович"]
        result = find_mentioned_usernames("@Александр, ты тут?", usernames)
        assert result == ["Александр"]

    async def test_unknown_username_ignored(self):
        assert find_mentioned_usernames("привет @ktonibud", ["ivan"]) == []

    async def test_case_insensitive_match(self):
        assert find_mentioned_usernames("@IVAN привет", ["ivan"]) == ["ivan"]

    async def test_multiple_unique_mentions_in_order(self):
        result = find_mentioned_usernames("@ivan и @maria, гляньте", ["ivan", "maria"])
        assert result == ["ivan", "maria"]

    async def test_duplicate_mention_counted_once(self):
        result = find_mentioned_usernames("@ivan где ты? @ivan ау", ["ivan"])
        assert result == ["ivan"]

    async def test_empty_text_returns_empty(self):
        assert find_mentioned_usernames("", ["ivan"]) == []

    async def test_no_known_usernames_returns_empty(self):
        assert find_mentioned_usernames("@ivan привет", []) == []

    async def test_bare_at_sign_does_not_crash(self):
        assert find_mentioned_usernames("просто @ и текст", ["ivan"]) == []


async def _make_bystander(session, username_prefix="mention"):
    """Пользователь, не автор и не исполнитель — упоминается только по @username."""
    return await make_user(session, username=f"{username_prefix}_{uuid.uuid4().hex[:6]}", password="pass123")


class TestNotifyCommentMentions:
    async def test_mentions_uninvolved_user(self, session, mock_bot):
        task, author, executor = await create_task_with_users(session)
        bystander = await _make_bystander(session)
        bystander.telegram_id = unique_tg_id()
        await session.commit()
        await session.refresh(bystander)
        await create_notification_settings(session, bystander.id)

        commenter = await make_user(session, username=f"comm_{uuid.uuid4().hex[:6]}", password="pass123")
        comment = CommentModel(content=f"глянь @{bystander.username}", task_id=task.id, user_id=commenter.id)
        session.add(comment)
        await session.commit()
        await session.refresh(comment)

        await notify_comment_added(comment.id)

        sent_to = {call.kwargs["chat_id"] for call in mock_bot.send_message.call_args_list}
        assert bystander.telegram_id in sent_to
        texts = {call.kwargs["chat_id"]: call.kwargs["text"] for call in mock_bot.send_message.call_args_list}
        assert "упомянули" in texts[bystander.telegram_id]

    async def test_mentioned_executor_gets_single_mention_message_not_duplicate(self, session, mock_bot):
        """Исполнителя одновременно и уведомляют о комментарии, и упоминают — должно уйти ОДНО сообщение."""
        task, author, executor = await create_task_with_users(session)
        executor.telegram_id = unique_tg_id()
        await session.commit()
        await session.refresh(executor)

        commenter = await make_user(session, username=f"comm_{uuid.uuid4().hex[:6]}", password="pass123")
        comment = CommentModel(content=f"@{executor.username} посмотри плиз", task_id=task.id, user_id=commenter.id)
        session.add(comment)
        await session.commit()
        await session.refresh(comment)

        await notify_comment_added(comment.id)

        calls_to_executor = [
            c for c in mock_bot.send_message.call_args_list if c.kwargs["chat_id"] == executor.telegram_id
        ]
        assert len(calls_to_executor) == 1
        assert "упомянули" in calls_to_executor[0].kwargs["text"]

    async def test_unknown_mention_is_ignored(self, session, mock_bot):
        task, author, executor = await create_task_with_users(session)
        commenter = await make_user(session, username=f"comm_{uuid.uuid4().hex[:6]}", password="pass123")
        comment = CommentModel(content="@nobody_such_user привет", task_id=task.id, user_id=commenter.id)
        session.add(comment)
        await session.commit()
        await session.refresh(comment)

        await notify_comment_added(comment.id)  # не должно упасть

        sent_to = {call.kwargs["chat_id"] for call in mock_bot.send_message.call_args_list}
        # Только обычные получатели (автор/исполнитель), никого лишнего.
        assert sent_to <= {author.telegram_id, executor.telegram_id}

    async def test_self_mention_by_commenter_not_notified_twice(self, session, mock_bot):
        task, author, executor = await create_task_with_users(session)
        commenter = await make_user(session, username=f"comm_{uuid.uuid4().hex[:6]}", password="pass123")
        commenter.telegram_id = unique_tg_id()
        await session.commit()
        await session.refresh(commenter)

        comment = CommentModel(
            content=f"я, @{commenter.username}, посмотрю это сам", task_id=task.id, user_id=commenter.id
        )
        session.add(comment)
        await session.commit()
        await session.refresh(comment)

        await notify_comment_added(comment.id)

        sent_to = {call.kwargs["chat_id"] for call in mock_bot.send_message.call_args_list}
        assert commenter.telegram_id not in sent_to

    async def test_respects_notify_mentioned_disabled(self, session, mock_bot):
        task, author, executor = await create_task_with_users(session)
        bystander = await _make_bystander(session)
        bystander.telegram_id = unique_tg_id()
        await session.commit()
        await session.refresh(bystander)
        await create_notification_settings(session, bystander.id, notify_mentioned=False)

        commenter = await make_user(session, username=f"comm_{uuid.uuid4().hex[:6]}", password="pass123")
        comment = CommentModel(content=f"@{bystander.username} гляньте", task_id=task.id, user_id=commenter.id)
        session.add(comment)
        await session.commit()
        await session.refresh(comment)

        await notify_comment_added(comment.id)

        sent_to = {call.kwargs["chat_id"] for call in mock_bot.send_message.call_args_list}
        assert bystander.telegram_id not in sent_to

    async def test_writes_notification_log_for_mention(self, session, mock_bot):
        task, author, executor = await create_task_with_users(session)
        bystander = await _make_bystander(session)
        bystander.telegram_id = unique_tg_id()
        await session.commit()
        await session.refresh(bystander)
        await create_notification_settings(session, bystander.id)

        commenter = await make_user(session, username=f"comm_{uuid.uuid4().hex[:6]}", password="pass123")
        comment = CommentModel(content=f"@{bystander.username} важно", task_id=task.id, user_id=commenter.id)
        session.add(comment)
        await session.commit()
        await session.refresh(comment)

        await notify_comment_added(comment.id)

        result = await session.execute(
            select(NotificationLogModel).where(
                NotificationLogModel.user_id == bystander.id,
                NotificationLogModel.notification_type == "comment_mentioned",
            )
        )
        logs = result.scalars().all()
        assert len(logs) == 1
        assert logs[0].success is True

    async def test_multi_word_username_mention_end_to_end(self, session, mock_bot):
        task, author, executor = await create_task_with_users(session)
        bystander = await make_user(session, username="Александр Иванович", password="pass123")
        bystander.telegram_id = unique_tg_id()
        await session.commit()
        await session.refresh(bystander)
        await create_notification_settings(session, bystander.id)

        commenter = await make_user(session, username=f"comm_{uuid.uuid4().hex[:6]}", password="pass123")
        comment = CommentModel(
            content="@Александр Иванович, посмотрите пожалуйста", task_id=task.id, user_id=commenter.id
        )
        session.add(comment)
        await session.commit()
        await session.refresh(comment)

        await notify_comment_added(comment.id)

        sent_to = {call.kwargs["chat_id"] for call in mock_bot.send_message.call_args_list}
        assert bystander.telegram_id in sent_to

    async def test_no_mentions_still_notifies_task_participants_as_before(self, session, mock_bot):
        """Убеждаемся, что рефакторинг не сломал старое поведение без упоминаний."""
        task, author, executor = await create_task_with_users(session)
        commenter = await make_user(session, username=f"comm_{uuid.uuid4().hex[:6]}", password="pass123")
        comment = CommentModel(content="просто комментарий без упоминаний", task_id=task.id, user_id=commenter.id)
        session.add(comment)
        await session.commit()
        await session.refresh(comment)

        await notify_comment_added(comment.id)

        sent_to = {call.kwargs["chat_id"] for call in mock_bot.send_message.call_args_list}
        assert author.telegram_id in sent_to
        assert executor.telegram_id in sent_to
        texts = [c.kwargs["text"] for c in mock_bot.send_message.call_args_list]
        assert all("упомянули" not in t for t in texts)
