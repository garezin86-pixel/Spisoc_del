from abc import ABC, abstractmethod

from sqlalchemy import Select
from src.models.group import GroupModel
from src.models.user import UserModel


class AbstractGroupRepository(ABC):
    @abstractmethod
    async def get_all(self) -> list[GroupModel]:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, group_id: int) -> GroupModel | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id_users_in_group(self, group_id: int) -> GroupModel | None:
        raise NotImplementedError

    @abstractmethod
    async def get_id_group_for_name(self, name: str) -> GroupModel | None:
        raise NotImplementedError

    @abstractmethod
    async def create(self, group: GroupModel) -> GroupModel:
        raise NotImplementedError

    @abstractmethod
    async def add_user_in_group(self, group: GroupModel, user: UserModel) -> UserModel:
        raise NotImplementedError

    @abstractmethod
    async def delete_user_group(self, group: GroupModel, user: UserModel) -> UserModel:
        raise NotImplementedError

    @abstractmethod
    async def delete_group(self, group: GroupModel) -> GroupModel:
        raise NotImplementedError

    @abstractmethod
    async def get_group_users(self, group_id: int) -> list[UserModel]:
        raise NotImplementedError

    @abstractmethod
    async def get_user_groups(self, user_id: int) -> list[GroupModel]:
        raise NotImplementedError

    @abstractmethod
    def get_groups_paginated_for_user(self, query, user_id: int) -> Select:
        raise NotImplementedError

    @abstractmethod
    async def get_groups_paginated_total(self, query):
        raise NotImplementedError

    @abstractmethod
    async def get_groups_offset_limit(self, query, offset, limit):
        raise NotImplementedError

    @abstractmethod
    async def get_groups_paginated_for_access(
        self,
        *,
        user_id: int,
        unrestricted: bool,
        offset: int,
        limit: int,
    ):
        raise NotImplementedError

    @abstractmethod
    async def get_user_group(self, group_id):
        raise NotImplementedError

    @abstractmethod
    async def get_group_users_with_telegram(
        self, group_id: int, exclude_user_id: int | None = None
    ):
        raise NotImplementedError
