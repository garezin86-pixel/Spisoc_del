from src.models.user import UserModel
from src.repositories.users_repository import UserRepository
from src.db import get_session_maker
from src.bot.keyboards.main import (
    main_menu_admin,
    main_menu_user,
    task_edit_keyboard,
    main_menu_manager,  # добавить импорт
    task_edit_manager_keyboard,  # добавить импорт
)


async def get_user_by_telegram_id(telegram_id: int) -> UserModel | None:
    async with get_session_maker()() as session:
        repo = UserRepository(session)
        return await repo.get_by_telegram_id(telegram_id)


def get_menu_for_user(user: UserModel):
    """Возвращает клавиатуру в зависимости от роли"""
    return main_menu_admin() if user.role == "admin" else main_menu_user()


def get_main_menu(user):
    if user.role == "admin":
        return main_menu_admin()
    if user.role == "manager":
        return main_menu_manager()
    return main_menu_user()


def get_task_edit_keyboard(user):
    if user.role in ("admin", "manager"):
        return task_edit_manager_keyboard()
    return task_edit_keyboard()
