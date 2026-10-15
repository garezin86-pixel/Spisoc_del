# ruff: noqa: F811  (фикстура mock_reminder_bot подставляется по имени аргумента)
# tests/test_event_reminder_setting.py
"""Переключатель «Напоминания о встречах» (notify_event_reminder) в настройках уведомлений Telegram-бота."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.handlers import notification_settings as handlers
from src.models.notification_settings import NotificationSettingsModel
from src.models.user import UserModel
from src.models.workspace import WorkspaceModel
from tests.test_reminders_service import mock_reminder_bot  # noqa: F401  (фикстура: бот-мок и тестовая БД)

BASE = {
    "notify_deadline_24h": True,
    "notify_deadline_1h": True,
    "notify_overdue": True,
    "weekly_report_enabled": True,
    "notify_task_assigned": True,
    "notify_task_updated": True,
    "notify_comment": True,
    "notify_mentioned": True,
    "notify_group_assigned": True,
    "notify_contact_due": True,
    "voice_notifications_enabled": False,
}


def _callbacks(keyboard) -> dict[str, str]:
    return {b.callback_data: b.text for row in keyboard.inline_keyboard for b in row}


def test_keyboard_has_event_reminder_button_with_state():
    on = _callbacks(handlers.get_notification_keyboard({**BASE, "notify_event_reminder": True}))
    off = _callbacks(handlers.get_notification_keyboard({**BASE, "notify_event_reminder": False}))
    assert on["toggle_event_reminder"] == "✅ Напоминания о встречах"
    assert off["toggle_event_reminder"] == "❌ Напоминания о встречах"
    # словарь без ключа (старый код) — «включено», как и в БД по умолчанию
    assert _callbacks(handlers.get_notification_keyboard(BASE))["toggle_event_reminder"].startswith("✅")
    assert {"toggle_contact_due", "enable_all", "disable_all", "close_settings"} <= set(on)


@pytest.fixture
async def user_ctx(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        w = WorkspaceModel(name="W", slug=f"w-{uuid.uuid4().hex[:6]}")
        s.add(w)
        await s.commit()
        await s.refresh(w)
        user = UserModel(
            username="u",
            login=f"l_{uuid.uuid4().hex[:8]}",
            password_hash="x",
            role="manager",
            workspace_id=w.id,
            telegram_id=555001,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
    return maker, user


def _callback(user, data):
    cb = MagicMock()
    cb.data = data
    cb.from_user.id = user.telegram_id
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.answer = AsyncMock()
    return cb


async def _stored(maker, user_id):
    async with maker() as s:
        return (
            await s.execute(select(NotificationSettingsModel).where(NotificationSettingsModel.user_id == user_id))
        ).scalar_one()


async def test_toggle_saves_and_back(user_ctx, mock_reminder_bot):
    maker, user = user_ctx
    with patch.object(handlers, "get_session_maker", return_value=maker):
        await handlers.notification_toggle_callback(_callback(user, "toggle_event_reminder"))
        assert (await _stored(maker, user.id)).notify_event_reminder is False  # дефолт «включено» → выключили
        await handlers.notification_toggle_callback(_callback(user, "toggle_event_reminder"))
        assert (await _stored(maker, user.id)).notify_event_reminder is True


async def test_enable_and_disable_all_cover_the_setting(user_ctx):
    from src.db.unit_of_work import UnitOfWork

    maker, user = user_ctx
    async with UnitOfWork(maker) as uow:
        await uow.notification_settings.disable_all_notifications(user.id)
        await uow.commit()
    assert (await _stored(maker, user.id)).notify_event_reminder is False
    async with UnitOfWork(maker) as uow:
        await uow.notification_settings.enable_all_notifications(user.id)
        await uow.commit()
    assert (await _stored(maker, user.id)).notify_event_reminder is True
