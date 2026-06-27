import logging
import os

import structlog


def setup_logging() -> None:
    env = os.getenv("ENV", "production")
    level = logging.DEBUG if env == "dev" else logging.INFO

    logging.basicConfig(
        format="%(message)s",
        level=level,
    )

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
    ]

    if env == "dev":
        processors.append(structlog.dev.ConsoleRenderer())  # красивый вывод в dev
    else:
        processors.append(structlog.processors.JSONRenderer())  # JSON в prod

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
