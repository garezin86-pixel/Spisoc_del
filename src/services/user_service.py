from src.repositories.abstract import AbstractUserRepository
from src.schemas.user import UserRegister, UserUpdate
from src.models.user import UserModel
from src.core.constants import NO_ACCESS, USER_ALREADY_EXISTS, USER_NOT_FOUND
from src.core.exceptions import (
    current_admin,
    no_access,
    user_already_exists,
    user_not_found,
)
from src.core.security import hash_password


class UserService:

    def __init__(self, user_repo: AbstractUserRepository):
        self.user_repo = user_repo

    async def create_user(
        self, data: UserRegister, current_user: UserModel
    ) -> UserModel:
        if current_user.role != "admin":
            current_admin()

        existing = await self.user_repo.get_by_username(data.username)
        if existing:
            user_already_exists(USER_ALREADY_EXISTS)

        new_user = UserModel(
            username=data.username,
            password_hash=hash_password(data.password),
            role=data.role,
        )
        return await self.user_repo.create(new_user)

    async def get_users(self) -> list[UserModel]:
        return await self.user_repo.get_all()

    async def get_user(self, user_id: int, current_user: UserModel) -> UserModel:
        user = await self.user_repo.get_user_id(user_id)
        if not user:
            user_not_found(USER_NOT_FOUND)
            raise

        if current_user.role != "admin" and current_user.id != user_id:
            no_access(NO_ACCESS)
            raise

        return user

    async def update_user(
        self, user_id: int, data: UserUpdate, current_user: UserModel
    ) -> UserModel:
        user = await self.user_repo.get_user_id(user_id)
        if not user:
            user_not_found(USER_NOT_FOUND)
            raise
        if current_user.role != "admin" and current_user.id != user_id:
            no_access(NO_ACCESS)
            raise

        if data.username is not None:
            user.username = data.username
        if data.password is not None:
            user.password_hash = hash_password(data.password)

        return await self.user_repo.update(user)

    async def delete_user(self, user_id: int) -> dict:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            user_not_found(USER_NOT_FOUND)
            raise

        await self.user_repo.delete(user)
        return {"message": f"User {user_id} deleted"}

    async def get_users_paginated(self, offset: int, limit: int):
        query = self.user_repo.select_users_offset_limit(offset, limit)
        total = await self.user_repo.get_total_count(UserModel)
        users = await self.user_repo.execute_scalars(query)
        return users, total
