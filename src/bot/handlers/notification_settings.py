import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)

router = Router(name="notification_settings")


def get_notification_keyboard(settings: dict) -> InlineKeyboardMarkup:
    """Создает клавиатуру с текущими настройками уведомлений"""
    keyboard = [
        [
            InlineKeyboardButton(
                text=f"{'✅' if settings['notify_deadline_24h'] else '❌'} Напоминание за 24ч",
                callback_data="toggle_deadline_24h",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{'✅' if settings['notify_deadline_1h'] else '❌'} Напоминание за 1ч",
                callback_data="toggle_deadline_1h",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{'✅' if settings['notify_overdue'] else '❌'} Просрочка",
                callback_data="toggle_overdue",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{'✅' if settings['weekly_report_enabled'] else '❌'} Еженедельная сводка",
                callback_data="toggle_weekly",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{'✅' if settings['notify_task_assigned'] else '❌'} Назначение задачи",
                callback_data="toggle_task_assigned",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{'✅' if settings['notify_task_updated'] else '❌'} Обновление задачи",
                callback_data="toggle_task_updated",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{'✅' if settings['notify_comment'] else '❌'} Комментарии",
                callback_data="toggle_comment",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{'✅' if settings['notify_group_assigned'] else '❌'} Назначение в группу",
                callback_data="toggle_group_assigned",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{'🔊' if settings['voice_notifications_enabled'] else '🔇'} Голосовые уведомления (просрочка)",
                callback_data="toggle_voice_notifications",
            )
        ],
        [
            InlineKeyboardButton(text="🔘 Все включить", callback_data="enable_all"),
            InlineKeyboardButton(text="⚫ Все выключить", callback_data="disable_all"),
        ],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_settings")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# @router.message(F.text == "⚙️ Настройки уведомлений")
@router.message(F.text.in_({"⚙️ Настройки уведомлений", "⚙️ Настройки \n уведомлений"}))
async def settings_button(message: Message):
    await settings_command(message)  # переиспользуем существующий хендлер


async def _get_settings_dict(uow, user_id: int) -> dict:
    """Получить настройки пользователя в виде словаря (с дефолтами если нет записи)"""
    settings_obj = await uow.notification_settings.get_by_user(user_id)
    if settings_obj:
        return {
            "notify_deadline_24h": settings_obj.notify_deadline_24h,
            "notify_deadline_1h": settings_obj.notify_deadline_1h,
            "notify_overdue": settings_obj.notify_overdue,
            "weekly_report_enabled": settings_obj.weekly_report_enabled,
            "notify_task_assigned": settings_obj.notify_task_assigned,
            "notify_task_updated": settings_obj.notify_task_updated,
            "notify_comment": settings_obj.notify_comment,
            "notify_group_assigned": settings_obj.notify_group_assigned,
            "voice_notifications_enabled": settings_obj.voice_notifications_enabled,
        }
    return {
        "notify_deadline_24h": True,
        "notify_deadline_1h": True,
        "notify_overdue": True,
        "weekly_report_enabled": True,
        "notify_task_assigned": True,
        "notify_task_updated": True,
        "notify_comment": True,
        "notify_group_assigned": True,
        # ВАЖНО: голосовые — opt-in, дефолт False (в отличие от остальных
        # текстовых уведомлений выше, которые по умолчанию включены).
        # Синтез речи стоит денег за каждый вызов Groq API — не должен
        # включаться неявно для всех, кто ни разу не открывал /settings.
        "voice_notifications_enabled": False,
    }


@router.message(Command("settings"))
async def settings_command(message: Message):
    if not message.from_user:
        return

    try:
        session_maker = get_session_maker()
        async with UnitOfWork(session_maker) as uow:
            user = await uow.users.get_by_telegram_id(message.from_user.id)
            if not user:
                await message.answer("❌ Пользователь не найден. Начните с /start")
                return

            settings = await _get_settings_dict(uow, user.id)

        text = (
            "⚙️ <b>Настройки уведомлений</b>\n\n"
            "Нажмите на кнопку, чтобы включить/выключить тип уведомлений:\n\n"
            "✅ - включено\n"
            "❌ - выключено"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=get_notification_keyboard(settings))
    except Exception as e:
        logger.exception("settings_command error")
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("notifications_on"))
async def notifications_on_command(message: Message):
    """Включить все уведомления"""
    if not message.from_user:
        return

    session_maker = get_session_maker()
    async with UnitOfWork(session_maker) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ Пользователь не найден")
            return

        await uow.notification_settings.enable_all_notifications(user.id)
        await uow.commit()

    await message.answer("✅ Все уведомления включены!\n\nВы можете настроить их по отдельности командой /settings")


@router.message(Command("notifications_off"))
async def notifications_off_command(message: Message):
    """Выключить все уведомления"""
    if not message.from_user:
        return

    session_maker = get_session_maker()
    async with UnitOfWork(session_maker) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ Пользователь не найден")
            return

        await uow.notification_settings.disable_all_notifications(user.id)
        await uow.commit()

    await message.answer(
        "❌ Все уведомления выключены!\n\n"
        "Вы можете включить их командой /notifications_on\n"
        "или настроить по отдельности командой /settings"
    )


@router.callback_query(F.data.startswith("toggle_"))
async def notification_toggle_callback(callback: CallbackQuery):
    """Обработчик переключения настроек"""
    await callback.answer()

    if not callback.from_user or not callback.message:
        return

    mapping = {
        "toggle_deadline_24h": ("notify_deadline_24h", "напоминание за 24 часа"),
        "toggle_deadline_1h": ("notify_deadline_1h", "напоминание за 1 час"),
        "toggle_overdue": ("notify_overdue", "уведомление о просрочке"),
        "toggle_weekly": ("weekly_report_enabled", "еженедельная сводка"),
        "toggle_task_assigned": (
            "notify_task_assigned",
            "уведомление о назначении задачи",
        ),
        "toggle_task_updated": (
            "notify_task_updated",
            "уведомление об обновлении задачи",
        ),
        "toggle_comment": ("notify_comment", "уведомление о комментариях"),
        "toggle_group_assigned": (
            "notify_group_assigned",
            "уведомление о назначении в группу",
        ),
        "toggle_voice_notifications": (
            "voice_notifications_enabled",
            "голосовые уведомления о просрочке",
        ),
    }

    if callback.data not in mapping:
        return

    field, label = mapping[callback.data]

    session_maker = get_session_maker()
    async with UnitOfWork(session_maker) as uow:
        user = await uow.users.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.message.answer("❌ Пользователь не найден")
            return

        settings_obj = await uow.notification_settings.get_by_user(user.id)
        current_value = getattr(settings_obj, field) if settings_obj else True
        new_value = not current_value

        await uow.notification_settings.create_or_update(user.id, **{field: new_value})
        await uow.commit()

        settings = await _get_settings_dict(uow, user.id)

    status = "✅ Включено" if new_value else "❌ Выключено"
    if not callback.from_user or not isinstance(callback.message, Message):
        return

    await callback.message.edit_text(
        f"{status}: {label}\n\n⚙️ <b>Настройки уведомлений</b>\n\n✅ - включено  |  ❌ - выключено",
        parse_mode="HTML",
        reply_markup=get_notification_keyboard(settings),
    )


@router.callback_query(F.data == "enable_all")
async def enable_all_callback(callback: CallbackQuery):
    """Включить все уведомления"""
    await callback.answer()

    if not callback.from_user or not callback.message:
        return

    session_maker = get_session_maker()
    async with UnitOfWork(session_maker) as uow:
        user = await uow.users.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.message.answer("❌ Пользователь не найден")
            return

        await uow.notification_settings.enable_all_notifications(user.id)
        await uow.commit()

        settings = await _get_settings_dict(uow, user.id)
    if not callback.from_user or not isinstance(callback.message, Message):
        return

    await callback.message.edit_text(
        "✅ Все уведомления включены\n\n⚙️ <b>Настройки уведомлений</b>\n\n✅ - включено  |  ❌ - выключено",
        parse_mode="HTML",
        reply_markup=get_notification_keyboard(settings),
    )


@router.callback_query(F.data == "disable_all")
async def disable_all_callback(callback: CallbackQuery):
    """Выключить все уведомления"""
    await callback.answer()

    if not callback.from_user or not callback.message:
        return

    session_maker = get_session_maker()
    async with UnitOfWork(session_maker) as uow:
        user = await uow.users.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.message.answer("❌ Пользователь не найден")
            return

        await uow.notification_settings.disable_all_notifications(user.id)
        await uow.commit()

        settings = await _get_settings_dict(uow, user.id)

    if not callback.from_user or not isinstance(callback.message, Message):
        return

    await callback.message.edit_text(
        "❌ Все уведомления выключены\n\n⚙️ <b>Настройки уведомлений</b>\n\n✅ - включено  |  ❌ - выключено",
        parse_mode="HTML",
        reply_markup=get_notification_keyboard(settings),
    )


@router.callback_query(F.data == "close_settings")
async def close_settings_callback(callback: CallbackQuery):
    """Закрыть настройки"""
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.delete()
