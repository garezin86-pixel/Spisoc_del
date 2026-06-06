from fastapi import APIRouter, Request
from src.db import SessionDep
from src.schemas.token import TokenSchema
from src.schemas.user import UserLogin
from src.services.auth_service import AuthService
from src.repositories.users_repository import UserRepository
from src.core.limiter import limiter

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/login",
    response_model=TokenSchema,
    summary="Авторизация пользователя",
    description="""
Выдаёт JWT access-token по логину и паролю.

- Защищён rate-limit: **5 запросов в минуту** с одного IP (защита от брутфорса).
- Токен кладётся в заголовок `Authorization: Bearer <token>` для всех последующих запросов.
- Payload токена содержит `sub` (user_id), `role`, `username`.
""",
    responses={
        200: {
            "description": "Успешная авторизация",
            "content": {
                "application/json": {
                    "example": {"access_token": "eyJhbGci...", "token_type": "bearer"}
                }
            },
        },
        401: {"description": "Неверный логин или пароль"},
        429: {"description": "Слишком много запросов — подождите и попробуйте снова"},
    },
)
@limiter.limit("5/minute")
async def login(
    request: Request,
    user: UserLogin,
    session: SessionDep,
):
    return await AuthService(UserRepository(session)).login(user)
