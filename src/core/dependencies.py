import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.core.config import ALGORITHM, SECRET_KEY
from src.core.constants import (
    ACCOUNT_DISABLED,
    FOR_ADMIN_ONLY,
    INVALID_EXPIRED_TOKEN,
    USER_NOT_FOUND,
)
from src.core.exceptions import current_admin, no_access, unauthorized, user_not_found
from src.db import SessionDep
from src.models.enums import PatScope
from src.models.user import UserModel, UserRole
from src.services.pat_service import TOKEN_PREFIX, authenticate_by_pat

security = HTTPBearer()

# Методы, которые что-то меняют. GET/HEAD/OPTIONS сюда не входят — их
# read_only-токен может делать всегда.
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _enforce_pat_scope(request: Request, user: UserModel) -> None:
    """
    Если пользователь аутентифицирован read_only PAT-токеном (см.
    authenticate_by_pat, который выставляет user.pat_scope), запрещает
    любой мутирующий запрос. Проверка на уровне HTTP-метода, а не
    отдельного эндпоинта — так одно место защищает сразу все роутеры,
    включая новые, которые появятся в будущем.
    """
    scope = getattr(user, "pat_scope", None)
    if scope == PatScope.read_only and request.method in _MUTATING_METHODS:
        no_access("Этот токен read-only и не может выполнять изменяющие запросы")


async def get_current_user(
    request: Request,
    session: SessionDep,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> UserModel:
    token = credentials.credentials

    # Персональный API-токен (pat_...) — отдельная ветка аутентификации,
    # независимая от JWT/SECRET_KEY. Проверяется первой, т.к. по префиксу
    # сразу понятно, что это не JWT (JWT никогда не начинается с "pat_").
    if token.startswith(TOKEN_PREFIX):
        user = await authenticate_by_pat(session, token)
        if user is None:
            unauthorized("Токен недействителен, отозван или истёк")
            raise AssertionError("unreachable")  # unauthorized() всегда бросает исключение
        _enforce_pat_scope(request, user)
        return user

    if not SECRET_KEY or not ALGORITHM:
        raise RuntimeError("JWT config missing")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            raise jwt.InvalidTokenError("No sub")
        user_id = int(sub)
    except jwt.ExpiredSignatureError:
        unauthorized("Токен истёк")
        raise
    except jwt.PyJWTError:
        unauthorized(INVALID_EXPIRED_TOKEN)
        raise

    user = await session.get(UserModel, user_id)
    if not user:
        user_not_found(USER_NOT_FOUND)
        raise

    if not user.is_active:
        unauthorized(ACCOUNT_DISABLED)
        raise

    return user


def get_current_admin(
    current_user: UserModel = Depends(get_current_user),
) -> UserModel:
    """Только admin."""
    if current_user.role != UserRole.admin:
        current_admin(FOR_ADMIN_ONLY)
    return current_user


def get_current_manager(
    current_user: UserModel = Depends(get_current_user),
) -> UserModel:
    """admin или manager."""
    if current_user.role not in (UserRole.admin, UserRole.manager):
        current_admin(FOR_ADMIN_ONLY)
    return current_user


def is_admin(user: UserModel) -> bool:
    return user.role == UserRole.admin


def is_manager(user: UserModel) -> bool:
    return user.role in (UserRole.admin, UserRole.manager)


def is_regular_user(user: UserModel) -> bool:
    return user.role == UserRole.user


def decode_access_token(token: str) -> dict:
    if not SECRET_KEY or not ALGORITHM:
        raise RuntimeError("JWT config missing")

    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
