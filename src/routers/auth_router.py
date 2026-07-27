from fastapi import APIRouter, Depends, Request

from src.core.dependencies import get_current_user
from src.core.limiter import limiter

# Redis берём из FastAPICache (он уже инициализирован в lifespan)
from src.core.redis import get_redis
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.two_factor_repository import TwoFactorRepository
from src.repositories.users_repository import UserRepository
from src.schemas.token import RefreshRequest, TokenSchema, TwoFactorLoginRequest
from src.schemas.user import UserLogin
from src.services.auth_service import AuthService
from src.services.two_factor_service import TwoFactorService

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/login",
    response_model=TokenSchema,
    summary="Авторизация",
    description="Возвращает пару access + refresh токенов.",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "access_token": "eyJhbGci...",
                        "refresh_token": "eyJhbGci...",
                        "token_type": "bearer",
                    }
                }
            }
        },
        401: {"description": "Неверный логин или пароль"},
        429: {"description": "Слишком много попыток"},
    },
)
@limiter.limit("5/minute")
async def login(request: Request, user: UserLogin, session: SessionDep):
    redis = get_redis()
    return await AuthService(UserRepository(session), redis).login(user)


@router.post(
    "/login/2fa",
    response_model=TokenSchema,
    summary="Второй шаг входа (TOTP-код)",
    description=(
        "Вызывается после /auth/login, если тот вернул mfa_required=true. "
        "Принимает mfa_token из предыдущего ответа и 6-значный код из приложения-аутентификатора "
        "(или один из recovery-кодов). mfa_token живёт 5 минут."
    ),
    responses={
        401: {"description": "Неверный код, либо mfa_token истёк/невалиден"},
        429: {"description": "Слишком много попыток"},
    },
)
@limiter.limit("5/minute")
async def login_2fa(request: Request, data: TwoFactorLoginRequest, session: SessionDep):
    redis = get_redis()
    two_factor_service = TwoFactorService(TwoFactorRepository(session))
    return await AuthService(UserRepository(session), redis).login_with_2fa(
        data.mfa_token, data.code, two_factor_service
    )


@router.post(
    "/refresh",
    response_model=TokenSchema,
    summary="Обновить токены",
    description="""
Принимает refresh token, возвращает новую пару access + refresh.

Старый refresh token после этого инвалидируется (token rotation).
Если токен уже был использован — это признак кражи, сессия блокируется.
""",
    responses={
        200: {"description": "Новая пара токенов"},
        401: {"description": "Токен истёк, отозван или невалидный"},
    },
)
async def refresh(data: RefreshRequest, session: SessionDep):
    redis = get_redis()
    return await AuthService(UserRepository(session), redis).refresh(data.refresh_token)


@router.post(
    "/logout",
    status_code=204,
    summary="Выход",
    description="Отзывает refresh token. Access token истечёт сам через 15-30 мин.",
)
async def logout(
    data: RefreshRequest,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    redis = get_redis()
    await AuthService(UserRepository(session), redis).logout(data.refresh_token)
