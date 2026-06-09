from aiogram import Router
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from src.bot.keyboards.main import main_menu_admin, main_menu_user
from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from aiogram.types import MenuButtonCommands, BotCommand
from aiogram.filters import CommandStart

router = Router()


async def set_main_menu(bot):
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
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
