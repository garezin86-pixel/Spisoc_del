# src/services/instance_setup_service.py
"""Первый запуск self-hosted-установки: компания, её администратор и воронка продаж.

Публичная регистрация компаний (ALLOW_COMPANY_REGISTRATION) для этого не годится: на свежей установке её нужно
держать выключенной, а оставить включённой «до первого входа» значит дать первому встречному создать компанию.
Поэтому первая компания создаётся из консоли (scripts/init_instance.py) — тем, у кого есть доступ к серверу.

Повторный запуск ничего не меняет: если в БД уже есть хоть один пользователь, установка считается настроенной.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

import structlog
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import hash_password
from src.db.tenant_scope import SKIP_WORKSPACE_SCOPE, set_session_workspace
from src.models.user import UserModel
from src.models.workspace import WorkspaceModel
from src.repositories.deal_repository import DealRepository
from src.repositories.users_repository import UserRepository
from src.repositories.workspace_repository import WorkspaceRepository
from src.schemas.deal import StageCreate, StageKind
from src.schemas.workspace import RegisterRequest
from src.services.deal_service import DEFAULT_PIPELINE_NAME, DEFAULT_STAGES
from src.services.login_service import generate_unique_login
from src.services.workspace_service import WorkspaceService, build_company_slug_base

logger = structlog.get_logger()

MIN_ADMIN_PASSWORD = 8
MAX_OPEN_STAGES = 20
WON_STAGE = "Успех"
LOST_STAGE = "Отказ"


class SetupError(Exception):
    """Данные для настройки не подходят (в тексте — что исправить)."""


class AlreadyInitialized(SetupError):
    """В базе уже есть пользователи — повторная настройка не нужна и опасна."""


@dataclass
class SetupResult:
    workspace_id: int
    admin_id: int
    company_name: str
    login: str  # по нему входят: может отличаться от введённого имени
    password: str
    password_generated: bool
    stages: list[str]


def generate_password(length: int = 16) -> str:
    """Случайный пароль без похожих символов (0/O, 1/l/I) — его читают с экрана и вводят руками."""
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in value) and any(c.isupper() for c in value) and any(c.isdigit() for c in value):
            return value


def parse_stages(raw: str | list[str] | None) -> list[tuple[str, StageKind]]:
    """«Лид, Переговоры; КП» → стадии воронки. Пусто — стандартный набор. «Успех» и «Отказ» добавляются всегда.

    Стадии, названные пользователем, — «в работе»; закрывающие стадии (выиграна / проиграна) заводим сами и ставим
    в конец, иначе сделку нечем закрыть.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()) or raw == []:
        return list(DEFAULT_STAGES)
    items = re.split(r"[,;\n]", raw) if isinstance(raw, str) else list(raw)
    names: list[str] = []
    seen: set[str] = {WON_STAGE.lower(), LOST_STAGE.lower()}
    for item in items:
        try:
            name = StageCreate(name=item.strip()).name if item.strip() else ""
        except ValidationError as exc:
            raise SetupError(f"Стадия «{item.strip()[:30]}…» не подходит: {exc.errors()[0]['msg']}") from exc
        if name and name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
    if not names:
        raise SetupError("Не указано ни одной стадии «в работе»")
    if len(names) > MAX_OPEN_STAGES:
        raise SetupError(f"Слишком много стадий: {len(names)}, максимум {MAX_OPEN_STAGES}")
    return [*[(n, StageKind.open) for n in names], (WON_STAGE, StageKind.won), (LOST_STAGE, StageKind.lost)]


async def is_initialized(session: AsyncSession) -> bool:
    """Есть ли в базе хоть один пользователь (в любой компании)."""
    count = await session.scalar(
        select(func.count()).select_from(UserModel).execution_options(**{SKIP_WORKSPACE_SCOPE: True})
    )
    return bool(count)


async def setup_instance(
    session: AsyncSession,
    *,
    company_name: str,
    admin_username: str,
    admin_password: str | None = None,
    stages: str | list[str] | None = None,
    pipeline_name: str = DEFAULT_PIPELINE_NAME,
) -> SetupResult:
    """Создаёт компанию, администратора и воронку одной операцией. Без пароля — генерирует его."""
    if await is_initialized(session):
        raise AlreadyInitialized("В базе уже есть пользователи — установка настроена")

    generated = not admin_password
    password = admin_password or generate_password()
    if len(password) < MIN_ADMIN_PASSWORD:
        raise SetupError(f"Пароль администратора — не короче {MIN_ADMIN_PASSWORD} символов")
    try:
        request = RegisterRequest(
            username=admin_username, password=password, company_name=company_name, invite_token=None
        )
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first["loc"]) or "данные"
        raise SetupError(f"{field}: {str(first['msg']).removeprefix('Value error, ')}") from exc
    stage_spec = parse_stages(stages)

    user_repo = UserRepository(session)
    workspace_service = WorkspaceService(WorkspaceRepository(session), user_repo)
    login = await generate_unique_login(request.username, user_repo)
    slug = await workspace_service._free_slug(build_company_slug_base(request.company_name or ""))

    workspace = WorkspaceModel(name=request.company_name, slug=slug)
    admin = UserModel(
        username=request.username,
        login=login,
        password_hash=hash_password(password),
        role="admin",
        # Сгенерированный пароль видели в консоли — пусть администратор заменит его своим при первом входе.
        must_change_password=generated,
    )
    admin = await WorkspaceRepository(session).create_company(workspace, admin)

    # Дальше — данные компании: привязываем сессию к ней, чтобы воронка получила её workspace_id.
    set_session_workspace(session, admin.workspace_id)
    deals = DealRepository(session)
    deals.set_audit_user(admin.id)
    await deals.create_pipeline_with_stages(pipeline_name, [(name, kind, None) for name, kind in stage_spec])
    await logger.ainfo("instance_initialized", workspace_id=admin.workspace_id, user_id=admin.id)

    return SetupResult(
        workspace_id=admin.workspace_id,
        admin_id=admin.id,
        company_name=request.company_name or "",
        login=login,
        password=password,
        password_generated=generated,
        stages=[name for name, _ in stage_spec],
    )
