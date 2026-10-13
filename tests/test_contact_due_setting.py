# ruff: noqa: F811  (фикстура mock_reminder_bot подставляется по имени аргумента)
# tests/test_contact_due_setting.py
"""Переключатель «Напоминания о клиентах» (notify_contact_due) в настройках уведомлений Telegram-бота.

Кнопка в /settings, сохранение через обработчик, «Включить все / Выключить все» и влияние на рассылку
remind_contact_due.
"""

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.handlers import notification_settings as handlers
from src.models.client import ClientModel
from src.models.notification_settings import NotificationSettingsModel
from src.models.user import UserModel
from src.models.workspace import WorkspaceModel
from src.services.reminders.service import remind_contact_due
from tests.test_reminders_service import mock_reminder_bot  # noqa: F401  (фикстура: бот-мок и тестовая БД)

DEFAULTS = {
    "notify_deadline_24h": True,
    "notify_deadline_1h": True,
    "notify_overdue": True,
    "weekly_report_enabled": True,
    "notify_task_assigned": True,
    "notify_task_updated": True,
    "notify_comment": True,
    "notify_mentioned": True,
    "notify_group_assigned": True,
    "voice_notifications_enabled": False,
}


def _callbacks(keyboard) -> dict[str, str]:
    return {b.callback_data: b.text for row in keyboard.inline_keyboard for b in row}


# ── кнопка ───────────────────────────────────────────────────────────────────
def test_keyboard_has_contact_due_button_with_state():
    on = _callbacks(handlers.get_notification_keyboard({**DEFAULTS, "notify_contact_due": True}))
    off = _callbacks(handlers.get_notification_keyboard({**DEFAULTS, "notify_contact_due": False}))
    assert on["toggle_contact_due"] == "✅ Напоминания о клиентах"
    assert off["toggle_contact_due"] == "❌ Напоминания о клиентах"
    # остальные кнопки на месте
    assert {"toggle_weekly", "toggle_overdue", "enable_all", "disable_all", "close_settings"} <= set(on)


# ── сохранение ───────────────────────────────────────────────────────────────
@pytest.fixture
async def user_ctx(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        w = WorkspaceModel(name="W", slug=f"w-{uuid.uuid4().hex[:6]}")
        s.add(w)
        await s.commit()
        user = UserModel(
            username=f"u_{uuid.uuid4().hex[:6]}",
            login=f"l_{uuid.uuid4().hex[:8]}",
            password_hash="x",
            role="manager",
            workspace_id=w.id,
            telegram_id=int(uuid.uuid4().int % 10**9),
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
    with patch.object(handlers, "get_session_maker", return_value=maker):
        yield maker, w, user


def _callback(user, data):
    cb = MagicMock()
    cb.data = data
    cb.from_user.id = user.telegram_id
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    return cb


async def _stored(maker, user_id):
    async with maker() as s:
        return (
            await s.execute(select(NotificationSettingsModel).where(NotificationSettingsModel.user_id == user_id))
        ).scalar_one_or_none()


async def test_default_is_enabled_without_settings_row(user_ctx):
    maker, _, user = user_ctx
    assert await _stored(maker, user.id) is None
    from src.db.unit_of_work import UnitOfWork

    async with UnitOfWork(maker) as uow:
        assert (await handlers._get_settings_dict(uow, user.id))["notify_contact_due"] is True


async def test_toggle_flips_and_saves(user_ctx):
    maker, _, user = user_ctx
    cb = _callback(user, "toggle_contact_due")
    await handlers.notification_toggle_callback(cb)  # без записи настроек значение «включено» → станет выключено
    assert (await _stored(maker, user.id)).notify_contact_due is False
    cb.message.edit_text.assert_awaited_once()
    shown = cb.message.edit_text.await_args
    assert "напоминания о клиентах" in shown.args[0] and "Выключено" in shown.args[0]
    assert _callbacks(shown.kwargs["reply_markup"])["toggle_contact_due"].startswith("❌")

    await handlers.notification_toggle_callback(_callback(user, "toggle_contact_due"))
    assert (await _stored(maker, user.id)).notify_contact_due is True  # и обратно


async def test_toggle_does_not_touch_other_settings(user_ctx):
    maker, _, user = user_ctx
    await handlers.notification_toggle_callback(_callback(user, "toggle_contact_due"))
    row = await _stored(maker, user.id)
    assert row.notify_deadline_24h is True and row.notify_comment is True and row.notify_overdue is True
    assert row.weekly_report_enabled is False  # opt-in: нажатие другой кнопки его не включает и не меняет


async def test_disable_all_and_enable_all_cover_contact_due(user_ctx):
    maker, _, user = user_ctx
    await handlers.disable_all_callback(_callback(user, "disable_all"))
    assert (
        await _stored(maker, user.id)
    ).notify_contact_due is False  # «выключить всё» выключает и напоминания о клиентах
    await handlers.enable_all_callback(_callback(user, "enable_all"))
    assert (await _stored(maker, user.id)).notify_contact_due is True


# ── влияние на рассылку ──────────────────────────────────────────────────────
async def test_reminder_respects_the_toggle(user_ctx, mock_reminder_bot):
    maker, w, user = user_ctx
    async with maker() as s:
        s.add(ClientModel(name="Ромашка", workspace_id=w.id, owner_id=user.id, next_contact_at=date.today()))
        await s.commit()

    await handlers.notification_toggle_callback(_callback(user, "toggle_contact_due"))  # выключили
    await remind_contact_due()
    assert mock_reminder_bot.send_message.await_count == 0

    await handlers.notification_toggle_callback(_callback(user, "toggle_contact_due"))  # включили обратно
    await remind_contact_due()
    assert mock_reminder_bot.send_message.await_count == 1  # клиент не потерян: напомнили после включения


async def test_disable_all_stops_client_reminders(user_ctx, mock_reminder_bot):
    maker, w, user = user_ctx
    async with maker() as s:
        s.add(ClientModel(name="Ромашка", workspace_id=w.id, owner_id=user.id, next_contact_at=date.today()))
        await s.commit()
    await handlers.disable_all_callback(_callback(user, "disable_all"))
    await remind_contact_due()
    assert mock_reminder_bot.send_message.await_count == 0


# ── что показывает экран до первого нажатия, должно совпадать с тем, что реально действует ──
async def test_screen_defaults_match_stored_defaults(user_ctx):
    """Любое расхождение дефолтов экрана и модели (как было с еженедельной сводкой) ловится этим тестом."""
    from src.db.unit_of_work import UnitOfWork

    maker, _, user = user_ctx
    async with UnitOfWork(maker) as uow:
        before = await handlers._get_settings_dict(uow, user.id)  # записи ещё нет — дефолты экрана
        await uow.notification_settings.create_or_update(user.id)  # запись с дефолтами модели
        await uow.commit()
    async with UnitOfWork(maker) as uow:
        after = await handlers._get_settings_dict(uow, user.id)
    assert before == after


async def test_weekly_report_shown_off_and_first_press_turns_it_on(user_ctx):
    maker, _, user = user_ctx
    from src.db.unit_of_work import UnitOfWork

    async with UnitOfWork(maker) as uow:
        shown = await handlers._get_settings_dict(uow, user.id)
    assert shown["weekly_report_enabled"] is False
    assert _callbacks(handlers.get_notification_keyboard(shown))["toggle_weekly"].startswith("❌")

    cb = _callback(user, "toggle_weekly")
    await handlers.notification_toggle_callback(cb)
    assert (
        await _stored(maker, user.id)
    ).weekly_report_enabled is True  # раньше сохранялось False при «включено» на экране
    assert "Включено" in cb.message.edit_text.await_args.args[0]
    assert _callbacks(cb.message.edit_text.await_args.kwargs["reply_markup"])["toggle_weekly"].startswith("✅")


async def test_voice_notifications_first_press_turns_them_on(user_ctx):
    """Голосовые — тоже opt-in (дефолт выключено): первое нажатие должно включить, а не «выключить ещё раз»."""
    maker, _, user = user_ctx
    cb = _callback(user, "toggle_voice_notifications")
    await handlers.notification_toggle_callback(cb)
    assert (await _stored(maker, user.id)).voice_notifications_enabled is True
    assert "Включено" in cb.message.edit_text.await_args.args[0]


async def test_every_toggle_flips_the_shown_state_on_first_press(user_ctx):
    """Для каждой кнопки: что показывал экран до нажатия, то и меняется на противоположное."""
    from src.db.unit_of_work import UnitOfWork

    maker, _, user = user_ctx
    toggles = {
        "toggle_deadline_24h": "notify_deadline_24h",
        "toggle_deadline_1h": "notify_deadline_1h",
        "toggle_overdue": "notify_overdue",
        "toggle_weekly": "weekly_report_enabled",
        "toggle_task_assigned": "notify_task_assigned",
        "toggle_task_updated": "notify_task_updated",
        "toggle_comment": "notify_comment",
        "toggle_mentioned": "notify_mentioned",
        "toggle_group_assigned": "notify_group_assigned",
        "toggle_contact_due": "notify_contact_due",
        "toggle_voice_notifications": "voice_notifications_enabled",
    }
    # список кнопок в тесте совпадает с клавиатурой: новая кнопка без проверки не пройдёт незамеченной
    in_keyboard = {
        c
        for c in _callbacks(handlers.get_notification_keyboard({**DEFAULTS, "notify_contact_due": True}))
        if c.startswith("toggle_")
    }
    assert in_keyboard == set(toggles)
    for data, field in toggles.items():
        async with UnitOfWork(maker) as uow:
            before = (await handlers._get_settings_dict(uow, user.id))[field]
        await handlers.notification_toggle_callback(_callback(user, data))
        async with UnitOfWork(maker) as uow:
            after = (await handlers._get_settings_dict(uow, user.id))[field]
        assert after is (not before), f"{data}: было {before}, стало {after}"
