from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import Request
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.config import ADMIN_ALLOWED_IPS  # список IP из .env
from src.core.security import verify_password
from src.repositories.users_repository import UserRepository

logger = structlog.get_logger()

MAX_ADMIN_LOGIN_ATTEMPTS = 5
ADMIN_LOGIN_WINDOW = timedelta(minutes=1)
_failed_admin_logins: dict[str, deque[datetime]] = defaultdict(deque)


def _check_ip_allowed(ip: str) -> bool:
    """Если список пуст — пропускаем всех (не настроено). Иначе — только из списка."""
    if not ADMIN_ALLOWED_IPS:
        return True
    return ip in ADMIN_ALLOWED_IPS


def _admin_login_attempts(ip: str) -> deque[datetime]:
    now = datetime.now(timezone.utc)
    dq = _failed_admin_logins[ip]
    while dq and dq[0] + ADMIN_LOGIN_WINDOW <= now:
        dq.popleft()
    return dq


class AdminAuth(AuthenticationBackend):
    def __init__(self, secret_key: str, session_maker: async_sessionmaker):
        super().__init__(secret_key)
        self._session_maker = session_maker

    async def login(self, request: Request) -> bool:
        client = request.client
        ip = client.host if client else "unknown"

        # ── IP-фильтр ────────────────────────────────────────────────
        if not _check_ip_allowed(ip):
            await logger.awarning(
                "admin_login_failed",
                username=None,
                ip=ip,
                reason="ip_not_allowed",
            )
            return False

        # ── Брутфорс-защита ──────────────────────────────────────────
        attempts = _admin_login_attempts(ip)
        if len(attempts) >= MAX_ADMIN_LOGIN_ATTEMPTS:
            await logger.awarning(
                "admin_login_failed",
                username=None,
                ip=ip,
                reason="too_many_attempts",
            )
            return False

        form = await request.form()
        username = form.get("username")
        password = form.get("password")

        if not isinstance(username, str) or not isinstance(password, str):
            attempts.append(datetime.now(timezone.utc))
            await logger.awarning(
                "admin_login_failed",
                username=username if isinstance(username, str) else None,
                ip=ip,
                reason="invalid_form",
            )
            return False

        async with self._session_maker() as session:
            repo = UserRepository(session)
            user = await repo.get_admin_by_username(username)

        if not user or not verify_password(password, user.password_hash):
            attempts.append(datetime.now(timezone.utc))
            await logger.awarning(
                "admin_login_failed",
                username=username,
                ip=ip,
                reason="invalid_credentials",
            )
            return False

        attempts.clear()
        request.session.update(
            {
                "admin_id": user.id,
                "admin_username": user.username,
            }
        )
        await logger.ainfo(
            "admin_login",
            username=user.username,
            admin_id=user.id,
            ip=ip,
        )
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        client = request.client
        ip = client.host if client else "unknown"
        if not _check_ip_allowed(ip):
            return False
        return "admin_id" in request.session
