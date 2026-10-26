"""Первый запуск: создаёт компанию, администратора и воронку продаж.

Запуск (после `docker compose up -d` — миграции применяются при старте приложения):

    docker compose run --rm app python -m scripts.init_instance
    # production:
    docker compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml \\
        run --rm app python -m scripts.init_instance

Без параметров спрашивает всё в диалоге. Без диалога (скрипты, CI) значения берутся из аргументов и переменных:

    --company / INIT_COMPANY_NAME     название компании
    --admin   / INIT_ADMIN_USERNAME   имя администратора (из него строится логин для входа)
    INIT_ADMIN_PASSWORD               пароль (не короче 8 символов); не задан — будет сгенерирован и показан один раз
    --stages  / INIT_STAGES           стадии воронки через запятую, «Успех» и «Отказ» добавятся сами

Повторный запуск безопасен: если в базе уже есть пользователи, скрипт ничего не меняет и завершается с кодом 0.
Коды выхода: 0 — готово (или уже настроено), 1 — неверные данные, 2 — база недоступна или не мигрирована.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError

from src.db import get_session_maker
from src.services.deal_service import DEFAULT_STAGES
from src.services.instance_setup_service import AlreadyInitialized, SetupError, setup_instance


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def _collect(args: argparse.Namespace) -> tuple[str, str, str | None, str | None]:
    company = args.company or os.getenv("INIT_COMPANY_NAME", "").strip()
    admin = args.admin or os.getenv("INIT_ADMIN_USERNAME", "").strip()
    password = os.getenv("INIT_ADMIN_PASSWORD") or None
    stages = args.stages if args.stages is not None else os.getenv("INIT_STAGES")
    interactive = sys.stdin.isatty()

    if not company and interactive:
        company = _ask("Название компании")
    if not admin and interactive:
        admin = _ask("Имя администратора", "admin")
    if password is None and interactive:
        password = getpass.getpass("Пароль администратора (Enter — сгенерировать): ") or None
        if password and getpass.getpass("Повторите пароль: ") != password:
            raise SetupError("Пароли не совпадают")
    if stages is None and interactive:
        default = ", ".join(name for name, kind in DEFAULT_STAGES if kind.value == "open")
        stages = _ask("Стадии воронки через запятую (Успех и Отказ добавятся сами)", default)
    if not company or not admin:
        raise SetupError(
            "Не заданы компания и имя администратора: запустите в терминале (с диалогом) "
            "или передайте --company и --admin"
        )
    return company, admin, password, stages


async def run(args: argparse.Namespace) -> int:
    try:
        company, admin, password, stages = _collect(args)
        async with get_session_maker()() as session:
            result = await setup_instance(
                session, company_name=company, admin_username=admin, admin_password=password, stages=stages
            )
    except AlreadyInitialized:
        print("Установка уже настроена: в базе есть пользователи, ничего не изменено.")
        return 0
    except SetupError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    except (OperationalError, ProgrammingError, DBAPIError, OSError) as exc:
        print(
            "База недоступна или ещё не подготовлена. Сначала запустите `docker compose up -d` и дождитесь запуска "
            f"приложения (оно применяет миграции).\nПодробности: {exc.__class__.__name__}: {str(exc)[:200]}",
            file=sys.stderr,
        )
        return 2

    print("\nГотово. Компания и администратор созданы.")
    print(f"  Компания:        {result.company_name}")
    print(f"  Логин для входа: {result.login}")
    if result.password_generated:
        print(f"  Пароль:          {result.password}   <- сохраните сейчас, повторно он не покажется")
        print("                   (при первом входе система попросит заменить его)")
    else:
        print("  Пароль:          тот, что вы задали")
    print(f"  Воронка «Продажи»: {' → '.join(result.stages)}")
    print("\nОткройте приложение в браузере и войдите. Сотрудников приглашайте из админ-панели ссылкой-приглашением.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Первый запуск Spisok Del: компания, администратор, воронка.")
    parser.add_argument("--company", help="название компании")
    parser.add_argument("--admin", help="имя администратора")
    parser.add_argument("--stages", help="стадии воронки через запятую (по умолчанию стандартные)")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
