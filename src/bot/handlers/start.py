from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from src.bot.keyboards.main import (
    main_menu_admin as main_menu_admin_keyboard,
)
from src.bot.keyboards.main import (
    main_menu_user as main_menu_user_keyboard,
)
from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.repositories.tag_repository import TagRepository
from src.utils.datetime_utils import to_local

router = Router()


@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, command: CommandObject, state: FSMContext):
    """Обработка deep links: t.me/бот?start=task_5"""
    param = command.args  # например "task_5"

    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)

        if not user:
            await message.answer(
                "👋 Добро пожаловать!\nУ вас нет доступа. Подайте заявку на регистрацию.",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="📝 Подать заявку")]],
                    resize_keyboard=True,
                ),
            )

            return

        if not user.is_active:
            await message.answer("⛔ Ваш аккаунт заблокирован.\nОбратитесь к администратору.")
            return

        # Обработка deep link task_<id>
        if param and param.startswith("task_"):
            try:
                task_id = int(param.split("_", 1)[1])
            except (ValueError, IndexError):
                await message.answer("❌ Некорректная ссылка.")
                return

            from src.repositories.groups_repository import GroupRepository
            from src.repositories.task_repository import TaskRepository
            from src.repositories.users_repository import UserRepository
            from src.services.task_service import TaskService

            task_service = TaskService(
                task_repo=TaskRepository(uow.session),
                user_repo=UserRepository(uow.session),
                group_repo=GroupRepository(uow.session),
                tag_repo=TagRepository(uow.session),
                session=uow.session,
            )

            try:
                task = await task_service.get_task(task_id, user)
            except Exception:
                await message.answer("❌ Задача не найдена или у вас нет доступа.")
                return

            _STATUS_LABELS = {
                "done": "✅ Выполнена",
                "in_progress": "⚙️ В работе",
                "review": "👁 На проверке",
                "todo": "📋 Новая",
                "backlog": "📥 В очереди",
            }
            status = _STATUS_LABELS.get(task.status.value if task.status else "todo", "⏳")
            author = task.author.username if task.author else "Неизвестный"

            from src.bot.handlers.tasks import EditTask
            from src.bot.keyboards.main import task_edit_keyboard

            await message.answer(
                f"📋 <b>Задача #{task.id}</b>\n\n"
                f"<b>{task.title}</b>\n"
                f"📝 {task.description or 'Нет описания'}\n"
                f"📊 {status}\n"
                f"📅 Дедлайн: {to_local(task.deadline)}\n"
                f"👤 Автор: {author}",
                parse_mode="HTML",
                reply_markup=task_edit_keyboard(),
            )
            await state.update_data(task_id=task_id)
            await state.set_state(EditTask.edit_type)
            return

        # Неизвестный deep link — просто показываем меню
        keyboard = main_menu_admin_keyboard() if user.role == "admin" else main_menu_user_keyboard()
        await message.answer(
            f"👋 Добро пожаловать, {user.username}!",
            reply_markup=keyboard,
        )


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обычный /start без параметров."""
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)

        if not user:
            await message.answer(
                "👋 Добро пожаловать!\nУ вас нет доступа. Подайте заявку на регистрацию.",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="📝 Подать заявку")]],
                    resize_keyboard=True,
                ),
            )
            return

        if not user.is_active:
            await message.answer("⛔ Ваш аккаунт заблокирован.\nОбратитесь к администратору.")
            return

        keyboard = main_menu_admin_keyboard() if user.role == "admin" else main_menu_user_keyboard()
        await message.answer(
            f"👋 Добро пожаловать, {user.username}!",
            reply_markup=keyboard,
        )
