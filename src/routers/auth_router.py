from fastapi import APIRouter, Depends, Request

from src.core.dependencies import get_current_user
from src.core.limiter import limiter

# Redis берём из FastAPICache (он уже инициализирован в lifespan)
from src.core.redis import get_redis
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.two_factor_repository import TwoFactorRepository
from src.repositories.users_repository import UserRepository
from src.repositories.workspace_repository import WorkspaceRepository
from src.schemas.token import RefreshRequest, TokenSchema, TwoFactorLoginRequest
from src.schemas.user import UserLogin
from src.schemas.workspace import (
    InvitePreview,
    RegisterRequest,
    RegistrationOptions,
    RegistrationResult,
)
from src.services.auth_service import AuthService
from src.services.two_factor_service import TwoFactorService
from src.services.workspace_service import (
    WorkspaceService,
    company_registration_enabled,
)

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


@router.get(
    "/registration-options",
    response_model=RegistrationOptions,
    summary="Доступные варианты регистрации",
    description="Публичный. Нужен экрану регистрации, чтобы скрыть «Новая компания», когда она отключена.",
)
async def registration_options():
    return RegistrationOptions(company_registration_enabled=company_registration_enabled())


@router.get(
    "/invite/{token}",
    response_model=InvitePreview,
    summary="Проверить приглашение",
    description="Публичный. Возвращает название компании, если приглашение действует; иначе 400.",
    responses={
        400: {"description": "Приглашение недействительно или истекло"},
        429: {"description": "Слишком много запросов"},
    },
)
@limiter.limit("30/minute")
async def preview_invite(request: Request, token: str, session: SessionDep):
    service = WorkspaceService(WorkspaceRepository(session), UserRepository(session))
    return InvitePreview(company_name=await service.preview_invite(token))


@router.post(
    "/register",
    response_model=RegistrationResult,
    status_code=201,
    summary="Регистрация: новая компания или вход по приглашению",
    description=(
        "Ровно одно из полей: `company_name` — создаёт новую компанию, пользователь становится её "
        "администратором (доступно только если включён ALLOW_COMPANY_REGISTRATION); `invite_token` — "
        "присоединение к существующей компании с ролью user. Роль в запросе не принимается. "
        "В ответ сразу выдаются токены и `login` — по нему нужно входить в дальнейшем (он отличается от username)."
    ),
    responses={
        400: {"description": "Приглашение недействительно/истекло или имя занято в этой компании"},
        403: {"description": "Создание компаний отключено"},
        422: {"description": "Не указан ровно один из company_name / invite_token"},
        429: {"description": "Слишком много попыток"},
    },
)
@limiter.limit("5/minute")
async def register(request: Request, data: RegisterRequest, session: SessionDep):
    user_repo = UserRepository(session)
    service = WorkspaceService(WorkspaceRepository(session), user_repo)
    if data.company_name:
        user = await service.register_company(data)
    else:
        user = await service.join_by_invite(data)
    tokens = await AuthService(user_repo, get_redis()).issue_tokens(user)
    return RegistrationResult(**tokens.model_dump(), login=user.login)


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
