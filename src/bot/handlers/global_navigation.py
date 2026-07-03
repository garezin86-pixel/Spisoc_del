from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, MenuButtonCommands, Message

from src.bot.keyboards.main import main_menu_admin, main_menu_user
from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork

router = Router()


async def set_main_menu(bot):
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="my", description="📋 Мои задачи"),
        BotCommand(command="today", description="📅 На сегодня"),
        BotCommand(command="overdue", description="⚠️ Просроченные"),
        BotCommand(command="stats", description="📊 Моя статистика"),
        BotCommand(command="done", description="✅ Закрыть задачу: /done 42"),
        BotCommand(command="undone", description="⏪ Снять отметку: /undone 42"),
        BotCommand(command="task", description="🔍 Показать задачу: /task 42"),
        BotCommand(command="del", description="🗑 В корзину: /del 42"),
        BotCommand(command="new", description="➕ Создать задачу: /new Название | дедлайн"),
        BotCommand(command="find", description="🔎 Найти задачу: /find текст"),
        BotCommand(command="voice", description="🎤 Голосовые команды — шпаргалка"),
        BotCommand(command="group", description="👥 Задачи группы: /group 3"),
        BotCommand(command="attach", description="📎 Прикрепить файл: /attach 42"),
        BotCommand(command="attachments", description="📎 Список вложений: /attachments 42"),
        BotCommand(command="getfile", description="📤 Получить файл: /getfile 7"),
        BotCommand(command="help", description="❓ Шпаргалка по командам"),
    ]

    await bot.set_my_commands(commands)

    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return
        keyboard = main_menu_admin() if user.role == "admin" else main_menu_user()
    await message.answer("🔙 Вернулись в главное меню.", reply_markup=keyboard)
