from fastapi import APIRouter, Request
from src.db import SessionDep
from src.schemas.token import TokenSchema
from src.schemas.user import UserLogin
from src.services.auth_service import AuthService
from src.repositories.users_repository import UserRepository
from src.core.limiter import limiter

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenSchema)
@limiter.limit("5/minute")  # ← защита от брутфорса
async def login(
    request: Request,
    user: UserLogin,
    session: SessionDep,
):
    return await AuthService(UserRepository(session)).login(user)


# @router.post("/register", response_model=UserSchema, status_code=201)
# @limiter.limit("3/minute")  # ← защита от спама регистраций
# async def register(
#     request: Request,
#     user: UserRegister,
#     session: SessionDep,
# ):
#     return await AuthService(UserRepository(session)).register(user)
