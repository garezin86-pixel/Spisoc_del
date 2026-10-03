# src/services/login_service.py
"""Генерация уникального login из ФИО — общая для всех мест, где заводится
пользователь: Telegram-бот (src/bot/handlers/start.py (вход по приглашению)), веб-
регистрация и создание пользователя из админки (src/services/auth_service.py,
src/services/user_service.py).

Раньше эта логика (дедупликация суффиксом при коллизии) жила только в
обработчике бота. Веб-регистрация и создание из админки login вообще не
задавали — из-за этого AuthService.login был вынужден держать fallback на
username при входе (см. миграцию login-backfill и её описание). Вынесено
сюда, чтобы у всех трёх мест было ровно одно поведение, а не три похожие,
но отдельно сопровождаемые копии.
"""

import secrets

import structlog

from src.repositories.abstract.base_user_repository import AbstractUserRepository
from src.utils.login_generator import build_login_base

logger = structlog.get_logger()

# Как и в исходной версии в боте: ограничение на число попыток — защита от
# бесконечного цикла, если get_by_login вдруг всегда возвращает что-то
# "истинное" (баг в моке теста уже один раз приводил ровно к этому —
# см. tests/test_bot.py).
_MAX_ATTEMPTS = 1000


async def generate_unique_login(fio: str, user_repo: AbstractUserRepository) -> str:
    """Строит login из ФИО (см. build_login_base) и подбирает свободный
    вариант, добавляя числовой суффикс при коллизии: ivanov.i, ivanov.i2, ...

    login уникален ГЛОБАЛЬНО (across all workspaces, не в рамках одной
    компании) — в отличие от username, который теперь уникален только в
    рамках workspace. Так решили осознанно: один человек не может завести
    два логина с одинаковым именем в разных компаниях, что проще для входа
    и для @упоминаний бота.
    """
    base_login = build_login_base(fio)
    login = base_login
    suffix = 2
    for _ in range(_MAX_ATTEMPTS):
        if not await user_repo.get_by_login(login):
            return login
        login = f"{base_login}{suffix}"
        suffix += 1

    await logger.aerror("login_generation_exhausted", base_login=base_login)
    return f"{base_login}{secrets.token_hex(3)}"
