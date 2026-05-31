import structlog

from src.repositories.abstract import AbstractUserRepository
from src.models.user import UserModel
from src.core.constants import INVALID_CREDENTIALS, USER_ALREADY_EXISTS
from src.core.exceptions import invalid_credentials, user_already_exists
from src.core.security import create_access_token, hash_password, verify_password
from src.schemas.user import UserLogin, UserRegister
from src.core.metrics import users_registered

logger = structlog.get_logger()


class AuthService:

    def __init__(self, user_repo: AbstractUserRepository):
        self.user_repo = user_repo

    async def register(self, user: UserRegister) -> UserModel:
        existing = await self.user_repo.get_by_username(user.username)
        if existing:
            user_already_exists(USER_ALREADY_EXISTS)

        new_user = UserModel(
            username=user.username,
            password_hash=hash_password(user.password),
            role="user",
        )
        created_user = await self.user_repo.create(new_user)
        await logger.ainfo(
            "user_registered",
            user_id=created_user.id,
            username=created_user.username,
        )
        users_registered.inc()
        return created_user

    async def login(self, user: UserLogin) -> dict:
        db_user = await self.user_repo.get_by_username(user.username)

        if not db_user or not verify_password(user.password, db_user.password_hash):
            await logger.awarning("login_failed", username=user.username)
            invalid_credentials(INVALID_CREDENTIALS)
            raise

        token = create_access_token(
            {"sub": str(db_user.id), "role": db_user.role, "username": db_user.username}
        )
        await logger.ainfo(
            "user_login",
            user_id=db_user.id,
            username=db_user.username,
        )
        return {"access_token": token, "token_type": "bearer"}
