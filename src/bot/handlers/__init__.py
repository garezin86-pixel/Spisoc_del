from aiogram import Dispatcher

from src.bot.handlers.admin import router as admin_router
from src.bot.handlers.commands import router as commands_router
from src.bot.handlers.notification_actions import router as notification_actions_router
from src.bot.handlers.notification_settings import router as notification_router
from src.bot.handlers.projects import router as projects_router
from src.bot.handlers.registration import router as registration_router
from src.bot.handlers.start import router as start_router
from src.bot.handlers.tasks import router as tasks_router
from src.bot.handlers.trash import router as trash_router
from src.bot.handlers.voice import router as voice_router


def register_handlers(dp: Dispatcher):
    # commands_router первым — чтобы /done, /task и т.д. не перехватывались
    # хендлерами с Message(content_types=...) из tasks_router
    dp.include_router(voice_router)  # голосовые — первым, до text-хендлеров
    dp.include_router(commands_router)
    dp.include_router(projects_router)
    dp.include_router(start_router)
    dp.include_router(notification_router)
    dp.include_router(notification_actions_router)
    dp.include_router(tasks_router)
    dp.include_router(admin_router)
    dp.include_router(registration_router)
    dp.include_router(trash_router)
