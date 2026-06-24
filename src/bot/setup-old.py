import asyncio
import structlog

logger = structlog.get_logger()

_bot = None
_storage = None
_dp = None
polling_task = None
_bot_username: str | None = None


async def init_bot_username() -> None:
    global _bot_username
    bot = get_bot()
    me = await bot.get_me()
    _bot_username = me.username


def get_bot_username() -> str:
    return _bot_username or ""


def get_bot():
    global _bot
    if _bot is None:
        from aiogram import Bot
        from src.core.config import BOT_TOKEN

        if not BOT_TOKEN:
            raise ValueError("BOT_TOKEN is not set in environment variables")
        _bot = Bot(token=BOT_TOKEN)
    return _bot


def get_storage():
    global _storage
    if _storage is None:
        from aiogram.fsm.storage.memory import MemoryStorage

        _storage = MemoryStorage()
    return _storage


def get_dispatcher():
    global _dp
    if _dp is None:
        from aiogram import Dispatcher

        _dp = Dispatcher(storage=get_storage())
    return _dp


async def start_bot():
    global polling_task

    if polling_task and not polling_task.done():
        await logger.ainfo("bot_already_running")
        return

    try:
        bot_instance = get_bot()
        dp_instance = get_dispatcher()

        from src.bot.handlers.global_navigation import set_main_menu

        await set_main_menu(bot_instance)

        button = await bot_instance.get_chat_menu_button()
        await logger.ainfo("bot_menu_button", button=str(button))

        from src.bot.middlewares.auth import AuthMiddleware

        dp_instance.message.middleware(AuthMiddleware())

        from src.bot.handlers import register_handlers

        register_handlers(dp_instance)

        # 👇 глобальный error handler
        from aiogram.types import ErrorEvent
        from src.core.metrics import bot_errors

        @dp_instance.errors()
        async def error_handler(event: ErrorEvent):
            handler_name = type(event.update).__name__
            bot_errors.labels(handler=handler_name).inc()
            await logger.aerror(
                "bot_error",
                handler=handler_name,
                error=str(event.exception),
            )

        await bot_instance.delete_webhook(drop_pending_updates=True)
        await logger.ainfo("bot_polling_starting")

        polling_task = asyncio.create_task(dp_instance.start_polling(bot_instance))
        await logger.ainfo("bot_polling_started")

        await init_bot_username()

    except Exception as e:
        await logger.aerror("bot_start_failed", error=str(e))
        polling_task = None


async def stop_bot():
    global polling_task, _bot

    await logger.ainfo("bot_stopping")

    if polling_task and not polling_task.done():
        try:
            polling_task.cancel()
            await polling_task
            await logger.ainfo("bot_polling_cancelled")
        except asyncio.CancelledError:
            await logger.ainfo("bot_polling_cancelled")
        except Exception as e:
            await logger.aerror("bot_polling_stop_error", error=str(e))

    if _bot:
        try:
            await _bot.session.close()
            await logger.ainfo("bot_session_closed")
        except Exception as e:
            await logger.aerror("bot_session_close_error", error=str(e))

    polling_task = None
