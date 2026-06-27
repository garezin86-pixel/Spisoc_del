from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_user() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📋 Мои задачи"),
                KeyboardButton(text="👤 Я автор"),
            ],
            [
                KeyboardButton(text="✅ Выполненные"),
                KeyboardButton(text="⏳ Невыполненные"),
            ],
            [
                KeyboardButton(text="🔍 Фильтры"),
                KeyboardButton(text="📝 Создать задачу"),
            ],
            [
                KeyboardButton(text="🗑 Корзина"),
                KeyboardButton(text="👥 Моя группа"),
            ],
            [
                KeyboardButton(text="📁 Проекты"),
                KeyboardButton(text="⚙️ Настройки \n уведомлений"),
            ],
        ],
        resize_keyboard=True,
    )


def main_menu_admin() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📋 Мои задачи"),
                KeyboardButton(text="👤 Я автор"),
            ],
            [
                KeyboardButton(text="✅ Выполненные"),
                KeyboardButton(text="⏳ Невыполненные"),
            ],
            [
                KeyboardButton(text="🔍 Фильтры"),
                KeyboardButton(text="📝 Создать задачу"),
            ],
            [KeyboardButton(text="👥 Пользователи"), KeyboardButton(text="👤 Группы")],
            [
                KeyboardButton(text="🗑 Корзина"),
                KeyboardButton(text="📁 Проекты"),
            ],
            [KeyboardButton(text="⚙️ Настройки \n уведомлений")],
        ],
        resize_keyboard=True,
    )


def assign_to_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Пользователю")],
            [KeyboardButton(text="👥 Группе")],
            [KeyboardButton(text="🚫 Без назначения")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


def skip_or_cancel() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭ Пропустить")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


def admin_users_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Список пользователей")],
            [KeyboardButton(text="➕ Добавить пользователя")],
            [KeyboardButton(text="🚫 Заблокировать пользователя")],
            [KeyboardButton(text="🗑 Удалить пользователя")],
            [KeyboardButton(text="🔙 Назад")],
        ],
        resize_keyboard=True,
    )


def admin_groups_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Список групп")],
            [KeyboardButton(text="📋 Список участников групп")],
            [KeyboardButton(text="➕ Создать группу")],
            [KeyboardButton(text="➕ Добавить в группу")],
            [KeyboardButton(text="➖ Удалить из группы")],
            [KeyboardButton(text="🗑 Удалить группу")],
            [KeyboardButton(text="🔙 Назад")],
        ],
        resize_keyboard=True,
    )


def task_filters_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📅 На сегодня"),
                KeyboardButton(text="⚠️ Просроченные"),
            ],
            [
                KeyboardButton(text="🔮 Запланированные"),
                KeyboardButton(text="🚫 Без дедлайна"),
            ],
            [KeyboardButton(text="🔍 По ID"), KeyboardButton(text="🔙 Назад")],
        ],
        resize_keyboard=True,
    )


def task_edit_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✏️ Изменить название")],
            [KeyboardButton(text="📅 Изменить дедлайн")],
            [
                KeyboardButton(text="⬅️ Статус назад"),
                KeyboardButton(text="➡️ Статус вперёд"),
            ],
            [KeyboardButton(text="💬 Комментарии")],
            [KeyboardButton(text="🗑 Удалить задачу")],
            [KeyboardButton(text="🔙 Назад в меню фильтры")],
        ],
        resize_keyboard=True,
    )


def comments_action_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💬 Добавить комментарий")],
            [KeyboardButton(text="🔙 Назад в меню редактирования")],
        ],
        resize_keyboard=True,
    )


def trash_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Меню внутри корзины."""
    rows = [
        [KeyboardButton(text="♻️ Восстановить задачу")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="💣 Удалить навсегда")])
    rows.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def main_menu_manager() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои задачи")],
            [
                KeyboardButton(text="✅ Выполненные"),
                KeyboardButton(text="⏳ Невыполненные"),
            ],
            [
                KeyboardButton(text="🔍 Фильтры"),
                KeyboardButton(text="📝 Создать задачу"),
            ],
            [
                KeyboardButton(text="🗑 Корзина"),
                KeyboardButton(text="👥 Моя группа"),
            ],
            [
                KeyboardButton(text="➕ Добавить в группу"),
                KeyboardButton(text="➖ Удалить из группы"),
            ],
            [
                KeyboardButton(text="📁 Проекты"),
                KeyboardButton(text="⚙️ Настройки \n уведомлений"),
            ],
        ],
        resize_keyboard=True,
    )


def task_edit_manager_keyboard() -> ReplyKeyboardMarkup:
    """Меню редактирования задачи для менеджера — как у admin, плюс переназначение."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✏️ Изменить название")],
            [KeyboardButton(text="📅 Изменить дедлайн")],
            [KeyboardButton(text="🔄 Переназначить задачу")],
            [
                KeyboardButton(text="⬅️ Статус назад"),
                KeyboardButton(text="➡️ Статус вперёд"),
            ],
            [KeyboardButton(text="💬 Комментарии")],
            [KeyboardButton(text="🗑 Удалить задачу")],
            [KeyboardButton(text="🔙 Назад в меню фильтры")],
        ],
        resize_keyboard=True,
    )


# ── Проекты ───────────────────────────────────────────────────────────────────


def projects_menu_keyboard() -> ReplyKeyboardMarkup:
    """Меню проектов для обычного пользователя."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои проекты")],
            [KeyboardButton(text="🔍 Проект по ID")],
            [KeyboardButton(text="🔄 Назначить проект на группу")],
            [KeyboardButton(text="🔙 Назад")],
        ],
        resize_keyboard=True,
    )


def projects_admin_keyboard() -> ReplyKeyboardMarkup:
    """Меню проектов для admin/manager — расширенное."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои проекты")],
            [KeyboardButton(text="🔍 Проект по ID")],
            [
                KeyboardButton(text="➕ Создать проект"),
                KeyboardButton(text="🗑 Удалить проект"),
            ],
            [
                KeyboardButton(text="➕ Добавить участника"),
                KeyboardButton(text="➖ Удалить участника"),
            ],
            [KeyboardButton(text="🔄 Назначить проект на группу")],
            [KeyboardButton(text="🔙 Назад")],
        ],
        resize_keyboard=True,
    )


def get_main_menu_keyboard(user) -> ReplyKeyboardMarkup:
    """Возвращает нужное главное меню в зависимости от роли пользователя."""
    from src.models.user import UserRole

    if user is None:
        return main_menu_user()
    if user.role == UserRole.admin:
        return main_menu_admin()
    if user.role == UserRole.manager:
        return main_menu_manager()
    return main_menu_user()
