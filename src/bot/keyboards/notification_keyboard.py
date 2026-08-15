from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.setup import get_bot_username


def task_action_keyboard(task_id: int) -> InlineKeyboardMarkup:
    second_row = [
        InlineKeyboardButton(text="💬 Комментировать", callback_data=f"notif_comment_{task_id}"),
    ]
    username = get_bot_username()
    if username:
        second_row.append(
            InlineKeyboardButton(
                text="📋 Открыть задачу",
                url=f"https://t.me/{username}?start=task_{task_id}",
            )
        )
    # Если юзернейм бота ещё не инициализирован (см. src/main.py lifespan) —
    # просто не показываем кнопку с битой ссылкой (https://t.me/?start=...)
    # вместо того чтобы вести пользователя в никуда.

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выполнено", callback_data=f"notif_done_{task_id}"),
                # InlineKeyboardButton(
                #     text="⏳ Отложить на 1ч", callback_data=f"notif_snooze_{task_id}"
                # ),
            ],
            second_row,
        ]
    )
