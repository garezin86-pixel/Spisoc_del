from abc import ABC, abstractmethod

from sqlalchemy import Select
from src.models.user import UserModel


class AbstractUserRepository(ABC):
    @abstractmethod
    async def get_all(self) -> list[UserModel]:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, user_id: int) -> UserModel | None:
        raise NotImplementedError

    @abstractmethod
    async def get_user_id(self, user_id: int) -> UserModel | None:
        raise NotImplementedError

    @abstractmethod
    async def get_users_limit(self, limit: int, offset: int) -> list[UserModel]:
        raise NotImplementedError

    @abstractmethod
    async def create(self, user: UserModel) -> UserModel:
        raise NotImplementedError

    @abstractmethod
    async def get_by_username(self, username: str) -> UserModel | None:
        raise NotImplementedError

    @abstractmethod
    async def update(self, user: UserModel) -> UserModel:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, user: UserModel) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_telegram_id(self, telegram_id: int) -> UserModel | None:
        raise NotImplementedError

    @abstractmethod
    async def set_role(self, username: str, role: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_admin_by_username(self, username: str) -> UserModel | None:
        raise NotImplementedError

    @abstractmethod
    def select_users_offset_limit(self, offset: int, limit: int):
        raise NotImplementedError

    @abstractmethod
    async def get_total_count(self, model) -> int:
        raise NotImplementedError

    @abstractmethod
    async def execute_scalars(self, query: Select):
        raise NotImplementedError

    @abstractmethod
    async def select_user(self, *args, **kwargs):
        raise NotImplementedError
