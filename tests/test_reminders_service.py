# tests/test_reminders_service.py
"""
Тесты для src/services/reminders/service.py — планировщик напоминаний бота.

Это единственный канал, которым бот реально достаёт до пользователя
(дедлайны, просрочки, еженедельный отчёт), поэтому здесь проверяется:
- кому отправляется уведомление и кому нет (окно времени, настройки, telegram_id);
- дедупликация повторной отправки (check_already_sent);
- что каждая отправка (успешная и нет) попадает в notification_log;
- содержимое отправляемого текста.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.notification_log import NotificationLogModel
from src.models.notification_settings import NotificationSettingsModel
from src.models.task import SpisokModel, TaskStatus
from src.services.reminders.service import (
    notify_group_assigned,
    notify_overdue,
    remind_deadline_1h,
    remind_deadline_24h,
    send_weekly_report,
)
from tests.conftest import make_user


def unique_tg_id() -> int:
    return int(uuid.uuid4().int % 10**9)


@pytest.fixture
def mock_reminder_bot(engine):
    """Мокает get_bot и подменяет session_maker сервиса на тестовый (in-memory sqlite)."""
    test_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    with (
        patch("src.services.reminders.service.get_bot") as mock_get_bot,
        patch(
            "src.services.reminders.service.get_session_maker",
            return_value=test_session_maker,
        ),
    ):
        bot = AsyncMock()
        bot.send_message = AsyncMock()
        mock_get_bot.return_value = bot
        yield bot


async def make_task_with_deadline(session, user, deadline, status=TaskStatus.todo, title="Тестовая задача"):
    task = SpisokModel(
        title=title,
        user_id=user.id,
        author_id=user.id,
        deadline=deadline,
        status=status,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def make_settings(session, user_id: int, **overrides):
    settings = NotificationSettingsModel(
        user_id=user_id,
        notify_deadline_24h=overrides.get("notify_deadline_24h", True),
        notify_deadline_1h=overrides.get("notify_deadline_1h", True),
        notify_overdue=overrides.get("notify_overdue", True),
        weekly_report_enabled=overrides.get("weekly_report_enabled", True),
        notify_group_assigned=overrides.get("notify_group_assigned", True),
        voice_notifications_enabled=overrides.get("voice_notifications_enabled", False),
    )
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    return settings


async def make_active_user(session, telegram_id=None, **kwargs):
    user = await make_user(session, **kwargs)
    user.telegram_id = telegram_id if telegram_id is not None else unique_tg_id()
    user.is_active = True
    await session.commit()
    await session.refresh(user)
    return user


async def get_logs_for_user(session, user_id, notification_type=None):
    query = select(NotificationLogModel).where(NotificationLogModel.user_id == user_id)
    if notification_type:
        query = query.where(NotificationLogModel.notification_type == notification_type)
    result = await session.execute(query)
    return result.scalars().all()


class TestRemindDeadline24h:
    @pytest.mark.asyncio
    async def test_sends_when_deadline_in_window(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id)
        deadline = datetime.now(timezone.utc) + timedelta(hours=24)
        await make_task_with_deadline(session, user, deadline, title="Сдать отчёт")

        await remind_deadline_24h()

        mock_reminder_bot.send_message.assert_called_once()
        assert mock_reminder_bot.send_message.call_args.kwargs["chat_id"] == user.telegram_id
        assert "Сдать отчёт" in mock_reminder_bot.send_message.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_not_sent_outside_window(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id)
        # Дедлайн через 3 дня — далеко за пределами окна ±10 минут вокруг +24ч
        deadline = datetime.now(timezone.utc) + timedelta(days=3)
        await make_task_with_deadline(session, user, deadline)

        await remind_deadline_24h()

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_sent_when_setting_disabled(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id, notify_deadline_24h=False)
        deadline = datetime.now(timezone.utc) + timedelta(hours=24)
        await make_task_with_deadline(session, user, deadline)

        await remind_deadline_24h()

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_sent_without_telegram_id(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        user.telegram_id = None
        await session.commit()
        await make_settings(session, user.id)
        deadline = datetime.now(timezone.utc) + timedelta(hours=24)
        await make_task_with_deadline(session, user, deadline)

        await remind_deadline_24h()

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_sent_for_done_task(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id)
        deadline = datetime.now(timezone.utc) + timedelta(hours=24)
        await make_task_with_deadline(session, user, deadline, status=TaskStatus.done)

        await remind_deadline_24h()

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_does_not_resend(self, session, mock_reminder_bot):
        """Если напоминание уже было отправлено — второй прогон джобы не шлёт повторно."""
        user = await make_active_user(session)
        await make_settings(session, user.id)
        deadline = datetime.now(timezone.utc) + timedelta(hours=24)
        await make_task_with_deadline(session, user, deadline)

        await remind_deadline_24h()
        assert mock_reminder_bot.send_message.call_count == 1

        mock_reminder_bot.send_message.reset_mock()
        await remind_deadline_24h()
        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_success_log_entry(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id)
        deadline = datetime.now(timezone.utc) + timedelta(hours=24)
        await make_task_with_deadline(session, user, deadline)

        await remind_deadline_24h()

        logs = await get_logs_for_user(session, user.id, "deadline_24h")
        assert len(logs) == 1
        assert logs[0].success is True

    @pytest.mark.asyncio
    async def test_logs_failure_when_bot_raises(self, session, mock_reminder_bot):
        """Если Telegram API падает — уведомление логируется как неуспешное, а не теряется молча."""
        user = await make_active_user(session)
        await make_settings(session, user.id)
        deadline = datetime.now(timezone.utc) + timedelta(hours=24)
        await make_task_with_deadline(session, user, deadline)

        mock_reminder_bot.send_message.side_effect = Exception("Bad Request: chat not found")

        await remind_deadline_24h()

        logs = await get_logs_for_user(session, user.id, "deadline_24h")
        assert len(logs) == 1
        assert logs[0].success is False
        assert "chat not found" in logs[0].error

    @pytest.mark.asyncio
    async def test_no_settings_defaults_to_enabled(self, session, mock_reminder_bot):
        """Если у пользователя вообще нет строки в notification_settings — уведомление
        всё равно отправляется (opt-out, не opt-in)."""
        user = await make_active_user(session)
        deadline = datetime.now(timezone.utc) + timedelta(hours=24)
        await make_task_with_deadline(session, user, deadline)

        await remind_deadline_24h()

        mock_reminder_bot.send_message.assert_called_once()


class TestRemindDeadline1h:
    @pytest.mark.asyncio
    async def test_sends_when_deadline_in_window(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id)
        deadline = datetime.now(timezone.utc) + timedelta(hours=1)
        await make_task_with_deadline(session, user, deadline, title="Срочная задача")

        await remind_deadline_1h()

        mock_reminder_bot.send_message.assert_called_once()
        assert "Срочная задача" in mock_reminder_bot.send_message.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_not_sent_when_setting_disabled(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id, notify_deadline_1h=False)
        deadline = datetime.now(timezone.utc) + timedelta(hours=1)
        await make_task_with_deadline(session, user, deadline)

        await remind_deadline_1h()

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_independent_dedup_from_24h(self, session, mock_reminder_bot):
        """24h и 1h напоминания для одной задачи — разные notification_type, не блокируют друг друга."""
        user = await make_active_user(session)
        await make_settings(session, user.id)
        deadline = datetime.now(timezone.utc) + timedelta(hours=24)
        await make_task_with_deadline(session, user, deadline)

        await remind_deadline_24h()
        assert mock_reminder_bot.send_message.call_count == 1

        # Тот же дедлайн технически не попадёт в окно "1h", но проверяем что
        # предыдущий вызов remind_deadline_24h не помешал бы записи под другим типом
        logs_24h = await get_logs_for_user(session, user.id, "deadline_24h")
        logs_1h = await get_logs_for_user(session, user.id, "deadline_1h")
        assert len(logs_24h) == 1
        assert len(logs_1h) == 0


class TestNotifyOverdue:
    @pytest.mark.asyncio
    async def test_sends_for_overdue_task(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id)
        deadline = datetime.now(timezone.utc) - timedelta(hours=2)
        await make_task_with_deadline(session, user, deadline, title="Просрочка")

        await notify_overdue()

        mock_reminder_bot.send_message.assert_called_once()
        assert "Просрочка" in mock_reminder_bot.send_message.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_not_sent_for_future_deadline(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id)
        deadline = datetime.now(timezone.utc) + timedelta(hours=2)
        await make_task_with_deadline(session, user, deadline)

        await notify_overdue()

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_sent_for_done_task(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id)
        deadline = datetime.now(timezone.utc) - timedelta(hours=2)
        await make_task_with_deadline(session, user, deadline, status=TaskStatus.done)

        await notify_overdue()

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_sent_when_setting_disabled(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id, notify_overdue=False)
        deadline = datetime.now(timezone.utc) - timedelta(hours=2)
        await make_task_with_deadline(session, user, deadline)

        await notify_overdue()

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_within_24h(self, session, mock_reminder_bot):
        """Просроченная задача не спамит уведомлением на каждый прогон джобы (раз в 24ч максимум)."""
        user = await make_active_user(session)
        await make_settings(session, user.id)
        deadline = datetime.now(timezone.utc) - timedelta(hours=2)
        await make_task_with_deadline(session, user, deadline)

        await notify_overdue()
        assert mock_reminder_bot.send_message.call_count == 1

        mock_reminder_bot.send_message.reset_mock()
        await notify_overdue()
        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_sent_without_telegram_id(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        user.telegram_id = None
        await session.commit()
        await make_settings(session, user.id)
        deadline = datetime.now(timezone.utc) - timedelta(hours=2)
        await make_task_with_deadline(session, user, deadline)

        await notify_overdue()

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_voice_notification_not_sent_by_default(self, session, mock_reminder_bot):
        """Голосовые уведомления — opt-in, по умолчанию выключены."""
        user = await make_active_user(session)
        await make_settings(session, user.id)  # voice_notifications_enabled не указан -> False
        deadline = datetime.now(timezone.utc) - timedelta(hours=2)
        await make_task_with_deadline(session, user, deadline)

        await notify_overdue()

        mock_reminder_bot.send_voice.assert_not_called()

    @pytest.mark.asyncio
    async def test_voice_notification_sent_when_enabled(self, session, mock_reminder_bot):
        with patch("src.services.voice_ai.synthesize_speech", new_callable=AsyncMock) as mock_tts:
            mock_tts.return_value = b"fake-ogg-audio-bytes"

            user = await make_active_user(session)
            await make_settings(session, user.id, voice_notifications_enabled=True)
            deadline = datetime.now(timezone.utc) - timedelta(hours=2)
            await make_task_with_deadline(session, user, deadline, title="Задача 1")

            await notify_overdue()

        mock_reminder_bot.send_voice.assert_called_once()
        assert mock_reminder_bot.send_voice.call_args.kwargs["chat_id"] == user.telegram_id

    @pytest.mark.asyncio
    async def test_voice_notification_aggregates_count_across_tasks(self, session, mock_reminder_bot):
        """Одно голосовое на пользователя со сводным числом, а не по одному на задачу."""
        with patch("src.services.voice_ai.synthesize_speech", new_callable=AsyncMock) as mock_tts:
            mock_tts.return_value = b"fake-ogg-audio-bytes"

            user = await make_active_user(session)
            await make_settings(session, user.id, voice_notifications_enabled=True)
            deadline = datetime.now(timezone.utc) - timedelta(hours=2)
            await make_task_with_deadline(session, user, deadline, title="Задача 1")
            await make_task_with_deadline(session, user, deadline, title="Задача 2")
            await make_task_with_deadline(session, user, deadline, title="Задача 3")

            await notify_overdue()

        assert mock_reminder_bot.send_voice.call_count == 1
        # Текст, переданный в TTS, должен упоминать все 3 задачи агрегированно
        tts_input_text = (
            mock_tts.call_args.args[0] if mock_tts.call_args.args else mock_tts.call_args.kwargs.get("text")
        )
        assert "3" in tts_input_text

    @pytest.mark.asyncio
    async def test_voice_pluralization_singular(self, session, mock_reminder_bot):
        with patch("src.services.voice_ai.synthesize_speech", new_callable=AsyncMock) as mock_tts:
            mock_tts.return_value = b"audio"
            user = await make_active_user(session)
            await make_settings(session, user.id, voice_notifications_enabled=True)
            deadline = datetime.now(timezone.utc) - timedelta(hours=2)
            await make_task_with_deadline(session, user, deadline)

            await notify_overdue()

        phrase = mock_tts.call_args.args[0] if mock_tts.call_args.args else mock_tts.call_args.kwargs.get("text")
        assert "1 просроченная задача" in phrase

    @pytest.mark.asyncio
    async def test_voice_pluralization_few(self, session, mock_reminder_bot):
        with patch("src.services.voice_ai.synthesize_speech", new_callable=AsyncMock) as mock_tts:
            mock_tts.return_value = b"audio"
            user = await make_active_user(session)
            await make_settings(session, user.id, voice_notifications_enabled=True)
            deadline = datetime.now(timezone.utc) - timedelta(hours=2)
            for i in range(3):
                await make_task_with_deadline(session, user, deadline, title=f"T{i}")

            await notify_overdue()

        phrase = mock_tts.call_args.args[0] if mock_tts.call_args.args else mock_tts.call_args.kwargs.get("text")
        assert "3 просроченные задачи" in phrase

    @pytest.mark.asyncio
    async def test_voice_pluralization_many(self, session, mock_reminder_bot):
        with patch("src.services.voice_ai.synthesize_speech", new_callable=AsyncMock) as mock_tts:
            mock_tts.return_value = b"audio"
            user = await make_active_user(session)
            await make_settings(session, user.id, voice_notifications_enabled=True)
            deadline = datetime.now(timezone.utc) - timedelta(hours=2)
            for i in range(5):
                await make_task_with_deadline(session, user, deadline, title=f"T{i}")

            await notify_overdue()

        phrase = mock_tts.call_args.args[0] if mock_tts.call_args.args else mock_tts.call_args.kwargs.get("text")
        assert "5 просроченных задач" in phrase

    @pytest.mark.asyncio
    async def test_tts_failure_does_not_affect_text_notification(self, session, mock_reminder_bot):
        """
        Если синтез речи упал (сбой Groq API) — текстовое уведомление всё
        равно должно было успешно отправиться до этого; голосовое — best-effort.
        """
        with patch("src.services.voice_ai.synthesize_speech", new_callable=AsyncMock) as mock_tts:
            mock_tts.side_effect = Exception("Groq TTS API error")

            user = await make_active_user(session)
            await make_settings(session, user.id, voice_notifications_enabled=True)
            deadline = datetime.now(timezone.utc) - timedelta(hours=2)
            await make_task_with_deadline(session, user, deadline, title="Задача")

            await notify_overdue()  # не должно бросить исключение наружу

        mock_reminder_bot.send_message.assert_called_once()
        mock_reminder_bot.send_voice.assert_not_called()

    # @pytest.mark.asyncio
    # async def test_voice_not_sent_when_all_tasks_already_notified(self, session, mock_reminder_bot):
    #     """Если все задачи уже были уведомлены в прошлый прогон (дедуп) — новый голосовой агрегат не шлётся."""
    #     with patch("src.services.voice_ai.synthesize_speech", new_callable=AsyncMock) as mock_tts:
    #         mock_tts.return_value = b"audio"

    #         user = await make_active_user(session)
    #         await make_settings(session, user.id, voice_notifications_enabled=True)
    #         deadline = datetime.now(timezone.utc) - timedelta(hours=2)
    #         await make_task_with_deadline(session, user, deadline)

    #         await notify_overdue()  # первый прогон — текст + голос
    #         mock_reminder_bot.send_voice.reset_mock()

    #         await notify_overdue()  # второй прогон — дедуп по тексту, голос не должен слаться повторно

    #     mock_reminder_bot.send_voice.assert_not_called()

    @pytest.mark.asyncio
    async def test_voice_sent_every_run_when_overdue_tasks_exist(
        self,
        session,
        mock_reminder_bot,
    ):
        """Голосовая сводка отправляется на каждом прогоне,
        пока у пользователя есть просроченные задачи."""

        with patch(
            "src.services.voice_ai.synthesize_speech",
            new_callable=AsyncMock,
        ) as mock_tts:
            mock_tts.return_value = b"audio"

            user = await make_active_user(session)
            await make_settings(
                session,
                user.id,
                voice_notifications_enabled=True,
            )

            deadline = datetime.now(timezone.utc) - timedelta(hours=2)
            await make_task_with_deadline(session, user, deadline)

            # Первый прогон
            await notify_overdue()
            mock_reminder_bot.send_voice.assert_called_once()

            mock_reminder_bot.send_voice.reset_mock()

            # Второй прогон
            await notify_overdue()

            # Голосовая сводка должна отправиться снова,
            # хотя текстовое уведомление уже подавлено дедупликацией.
            mock_reminder_bot.send_voice.assert_called_once()


class TestSendWeeklyReport:
    @pytest.mark.asyncio
    async def test_sends_to_user_with_weekly_enabled(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id, weekly_report_enabled=True)
        await make_task_with_deadline(session, user, datetime.now(timezone.utc) + timedelta(days=2))

        await send_weekly_report()

        mock_reminder_bot.send_message.assert_called_once()
        assert mock_reminder_bot.send_message.call_args.kwargs["chat_id"] == user.telegram_id

    @pytest.mark.asyncio
    async def test_not_sent_when_disabled(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id, weekly_report_enabled=False)
        await make_task_with_deadline(session, user, datetime.now(timezone.utc) + timedelta(days=2))

        await send_weekly_report()

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_sent_to_inactive_user(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id, weekly_report_enabled=True)
        user.is_active = False
        await session.commit()

        await send_weekly_report()

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_sent_without_telegram_id(self, session, mock_reminder_bot):
        """get_users_with_weekly_report уже фильтрует по telegram_id, но проверяем и явную ветку в самом сервисе."""
        user = await make_active_user(session)
        await make_settings(session, user.id, weekly_report_enabled=True)
        user.telegram_id = None
        await session.commit()

        await send_weekly_report()

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_report_lists_overdue_and_upcoming_counts(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id, weekly_report_enabled=True)
        now = datetime.now(timezone.utc)
        await make_task_with_deadline(session, user, now - timedelta(hours=5), title="Просрочена")
        await make_task_with_deadline(session, user, now + timedelta(days=3), title="Скоро")

        await send_weekly_report()

        text = mock_reminder_bot.send_message.call_args.kwargs["text"]
        assert "Просрочено: 1" in text
        assert "На этой неделе: 1" in text

    @pytest.mark.asyncio
    async def test_no_tasks_sends_positive_message(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id, weekly_report_enabled=True)

        await send_weekly_report()

        mock_reminder_bot.send_message.assert_called_once()
        text = mock_reminder_bot.send_message.call_args.kwargs["text"]
        assert "Нет задач" in text


class TestNotifyGroupAssigned:
    @pytest.mark.asyncio
    async def test_sends_notification(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id)

        await notify_group_assigned(user.id, group_id=1, group_name="Разработка")

        mock_reminder_bot.send_message.assert_called_once()
        assert "Разработка" in mock_reminder_bot.send_message.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_not_sent_without_telegram_id(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        user.telegram_id = None
        await session.commit()

        await notify_group_assigned(user.id, group_id=1, group_name="Разработка")

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_sent_when_setting_disabled(self, session, mock_reminder_bot):
        user = await make_active_user(session)
        await make_settings(session, user.id, notify_group_assigned=False)

        await notify_group_assigned(user.id, group_id=1, group_name="Разработка")

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_sent_for_nonexistent_user(self, session, mock_reminder_bot):
        await notify_group_assigned(user_id=999999, group_id=1, group_name="Х")

        mock_reminder_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_within_one_hour(self, session, mock_reminder_bot):
        """Повторное назначение в ту же группу в течение часа не шлёт дубль уведомления."""
        user = await make_active_user(session)
        await make_settings(session, user.id)

        await notify_group_assigned(user.id, group_id=1, group_name="Разработка")
        assert mock_reminder_bot.send_message.call_count == 1

        mock_reminder_bot.send_message.reset_mock()
        await notify_group_assigned(user.id, group_id=1, group_name="Разработка")
        mock_reminder_bot.send_message.assert_not_called()
