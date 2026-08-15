from aiogram import Dispatcher

from src.bot.handlers.admin import router as admin_router
from src.bot.handlers.attachments_handler import router as attachments_router
from src.bot.handlers.chat_bridge import router as chat_bridge_router
from src.bot.handlers.commands import router as commands_router
from src.bot.handlers.dm_bridge import router as dm_bridge_router
from src.bot.handlers.notification_actions import router as notification_actions_router
from src.bot.handlers.notification_settings import router as notification_router
from src.bot.handlers.projects import router as projects_router
from src.bot.handlers.registration import router as registration_router
from src.bot.handlers.start import router as start_router
from src.bot.handlers.tasks import router as tasks_router
from src.bot.handlers.trash import router as trash_router
from src.bot.handlers.voice import router as voice_router


def register_handlers(dp: Dispatcher):
    # chat_bridge_router — самым первым: ловит сообщения из привязанной
    # Telegram-группы (мост с общим чатом Spisoc) раньше остальных text-
    # хендлеров, у которых нет фильтра по типу чата и которые иначе могли бы
    # случайно среагировать на обычную переписку в группе (FSM voice/tasks и т.п.)
    dp.include_router(chat_bridge_router)
    # dm_bridge_router — сразу после: ловит ТОЛЬКО reply-сообщения (личные
    # переписки через Telegram), обычный текст его фильтр не матчит и
    # спокойно идёт дальше в voice_router как раньше.
    dp.include_router(dm_bridge_router)
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
    dp.include_router(attachments_router)
    dp.include_router(trash_router)
