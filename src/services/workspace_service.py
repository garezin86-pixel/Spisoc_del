# src/services/workspace_service.py
"""Компании (workspace): регистрация, приглашения, вход в компанию по токену."""

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import structlog
from sqlalchemy.exc import IntegrityError

from src.core.config import ALLOW_COMPANY_REGISTRATION
from src.core.constants import USER_ALREADY_EXISTS
from src.core.exceptions import current_admin, incorrect_request, no_access, not_found, user_already_exists
from src.core.security import hash_password
from src.db.tenant_scope import set_session_workspace
from src.models.user import UserModel
from src.models.workspace import WorkspaceModel
from src.models.workspace_invite import WorkspaceInviteModel
from src.repositories.users_repository import UserRepository
from src.repositories.workspace_repository import WorkspaceRepository
from src.schemas.workspace import RegisterRequest
from src.services.login_service import generate_unique_login
from src.utils.login_generator import _transliterate_word, generate_temp_password

logger = structlog.get_logger()

INVITE_TTL = timedelta(days=7)
INVALID_INVITE = "Приглашение недействительно или истекло"

_MAX_SLUG_LEN = 48


class TelegramJoinResult(NamedTuple):
    user: UserModel
    login: str
    temp_password: str


def build_company_slug_base(company_name: str) -> str:
    """«ООО Ромашка» → «ooo-romashka». Пустой результат → «company»."""
    words = (_transliterate_word(w) for w in company_name.split())
    return "-".join(w for w in words if w)[:_MAX_SLUG_LEN].strip("-") or "company"


def _telegram_username(display_name: str, telegram_id: int) -> str:
    name = re.sub(r"\s+", " ", display_name or "").strip()[:45]
    return name if len(name) >= 3 else f"user{telegram_id}"


class WorkspaceService:
    def __init__(self, repo: WorkspaceRepository, user_repo: UserRepository):
        self.repo = repo
        self.user_repo = user_repo

    # ── Приглашения (только админ СВОЕЙ компании) ────────────────────────────
    @staticmethod
    def _require_admin(user: UserModel) -> None:
        if user.role != "admin":
            current_admin()

    async def create_invite(self, current_user: UserModel) -> WorkspaceInviteModel:
        self._require_admin(current_user)
        invite = WorkspaceInviteModel(
            token=secrets.token_urlsafe(24),
            workspace_id=current_user.workspace_id,
            created_by_id=current_user.id,
            expires_at=datetime.now(timezone.utc) + INVITE_TTL,
        )
        invite = await self.repo.create_invite(invite)
        await logger.ainfo("workspace_invite_created", invite_id=invite.id, workspace_id=invite.workspace_id)
        return invite

    async def list_invites(self, current_user: UserModel, *, only_active: bool = True) -> list[WorkspaceInviteModel]:
        self._require_admin(current_user)
        return await self.repo.list_invites(only_active=only_active)

    async def revoke_invite(self, current_user: UserModel, invite_id: int) -> WorkspaceInviteModel:
        self._require_admin(current_user)
        # Сессия уже привязана к компании админа: чужое приглашение по id не находится.
        invite = await self.repo.get_invite(invite_id)
        if invite is None or invite.workspace_id != current_user.workspace_id:
            not_found("Invite not found")
        if invite.revoked_at is None:
            invite.revoked_at = datetime.now(timezone.utc)
            invite = await self.repo.save_invite(invite)
            await logger.ainfo("workspace_invite_revoked", invite_id=invite.id, workspace_id=invite.workspace_id)
        return invite

    # ── Регистрация в вебе ───────────────────────────────────────────────────
    async def register_company(self, data: RegisterRequest) -> UserModel:
        """Новая компания + её первый пользователь с role="admin".

        is_platform_admin здесь НЕ выставляется никогда — это поле меняют
        только вручную в БД (доступ в SQLAdmin ко всем компаниям).
        """
        assert data.company_name
        if not ALLOW_COMPANY_REGISTRATION:
            no_access("Создание новых компаний отключено")

        # login уникален глобально → подбираем ДО любой привязки сессии к workspace.
        login = await generate_unique_login(data.username, self.user_repo)
        base = build_company_slug_base(data.company_name)

        for attempt in range(2):
            slug = await self._free_slug(base) if attempt == 0 else f"{base[:40]}-{secrets.token_hex(3)}"
            workspace = WorkspaceModel(name=data.company_name, slug=slug)
            admin = UserModel(
                username=data.username,
                login=login,
                password_hash=hash_password(data.password),
                role="admin",
            )
            try:
                created = await self.repo.create_company(workspace, admin)
            except IntegrityError:
                # Гонка: параллельная регистрация заняла slug (или login).
                await self.repo.session.rollback()
                if attempt == 1:
                    user_already_exists(USER_ALREADY_EXISTS)
                continue
            await logger.ainfo("company_registered", workspace_id=created.workspace_id, user_id=created.id)
            return created
        raise AssertionError("unreachable")  # pragma: no cover

    async def _free_slug(self, base: str) -> str:
        if not await self.repo.slug_exists(base):
            return base
        for n in range(2, 1000):
            candidate = f"{base[: _MAX_SLUG_LEN - len(str(n)) - 1]}-{n}"
            if not await self.repo.slug_exists(candidate):
                return candidate
        return f"{base[:40]}-{secrets.token_hex(3)}"

    async def join_by_invite(self, data: RegisterRequest) -> UserModel:
        """Присоединение к существующей компании по токену, role="user"."""
        assert data.invite_token
        invite = await self.repo.get_active_invite_by_token(data.invite_token)
        if invite is None:
            incorrect_request(INVALID_INVITE)

        login = await generate_unique_login(data.username, self.user_repo)  # глобально, до привязки
        set_session_workspace(self.repo.session.sync_session, invite.workspace_id)
        # С этого момента сессия видит только эту компанию: username проверяется
        # внутри неё (одинаковые имена в РАЗНЫХ компаниях допустимы).
        if await self.user_repo.get_by_username(data.username):
            user_already_exists(USER_ALREADY_EXISTS)

        user = UserModel(
            username=data.username,
            login=login,
            password_hash=hash_password(data.password),
            role="user",
            workspace_id=invite.workspace_id,
        )
        try:
            created = await self.user_repo.create(user)
        except IntegrityError:
            await self.repo.session.rollback()
            user_already_exists(USER_ALREADY_EXISTS)
        await logger.ainfo("user_joined_by_invite", user_id=created.id, workspace_id=created.workspace_id)
        return created

    # ── Вход по приглашению из Telegram-бота ─────────────────────────────────
    async def join_by_invite_telegram(
        self, token: str, telegram_id: int, display_name: str
    ) -> TelegramJoinResult | None:
        """Мгновенное присоединение без ручного одобрения (старый flow «ФИО →
        одобрение через SUPER_ADMIN_TG_ID» убран). None — приглашение
        недействительно. Вызывающий обязан заранее убедиться, что этот
        telegram_id ещё не привязан к пользователю (он глобально уникален).
        """
        invite = await self.repo.get_active_invite_by_token(token)
        if invite is None:
            return None

        base_name = _telegram_username(display_name, telegram_id)
        login = await generate_unique_login(base_name, self.user_repo)  # глобально, до привязки
        set_session_workspace(self.repo.session.sync_session, invite.workspace_id)

        username, n = base_name, 2
        while await self.user_repo.get_by_username(username):
            username = f"{base_name[: 50 - len(str(n)) - 1]} {n}"
            n += 1

        temp_password = generate_temp_password()
        user = UserModel(
            username=username,
            login=login,
            password_hash=hash_password(temp_password),
            role="user",
            is_active=True,
            telegram_id=telegram_id,
            must_change_password=True,
            workspace_id=invite.workspace_id,
        )
        created = await self.user_repo.create(user)
        await logger.ainfo(
            "user_joined_by_invite", user_id=created.id, workspace_id=created.workspace_id, via="telegram"
        )
        return TelegramJoinResult(created, login, temp_password)
