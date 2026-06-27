from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.setup import get_bot_username


def task_action_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выполнено", callback_data=f"notif_done_{task_id}"),
                # InlineKeyboardButton(
                #     text="⏳ Отложить на 1ч", callback_data=f"notif_snooze_{task_id}"
                # ),
            ],
            [
                InlineKeyboardButton(text="💬 Комментировать", callback_data=f"notif_comment_{task_id}"),
                InlineKeyboardButton(
                    text="📋 Открыть задачу",
                    url=f"https://t.me/{get_bot_username()}?start=task_{task_id}",
                ),
            ],
        ]
    )
