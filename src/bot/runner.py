import asyncio
import signal

import structlog

from src.bot import setup as bot_setup
from src.core.logging import setup_logging
from src.core.sentry import setup_sentry

setup_sentry()
setup_logging()

logger = structlog.get_logger()


async def main() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    await logger.ainfo("bot_service_starting")
    await bot_setup.start_bot()
    if bot_setup.polling_task is None:
        raise RuntimeError("Bot polling did not start")

    try:
        await stop_event.wait()
    finally:
        await bot_setup.stop_bot()
        await logger.ainfo("bot_service_stopped")


if __name__ == "__main__":
    asyncio.run(main())
