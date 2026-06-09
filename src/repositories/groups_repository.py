from typing import Optional

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.group import GroupModel
from src.models.user import UserModel
from src.repositories.abstract.base_group_repository import AbstractGroupRepository


class GroupRepository(AbstractGroupRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self) -> list[GroupModel]:
        result = await self.session.execute(select(GroupModel))
        groups = list(result.scalars().all())
        return groups

    async def get_by_id(self, group_id: int) -> GroupModel | None:
        result = await self.session.execute(
            select(GroupModel).where(GroupModel.id == group_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_users_in_group(self, group_id: int) -> GroupModel | None:
        result = await self.session.execute(
            select(GroupModel)
            .options(selectinload(GroupModel.users))
            .where(GroupModel.id == group_id)
        )
        return result.scalar_one_or_none()

    async def get_id_group_for_name(self, name: str) -> GroupModel | None:
        return await self.session.scalar(
            select(GroupModel).where(GroupModel.name == name)
        )

    async def create(self, group: GroupModel) -> GroupModel:
        self.session.add(group)
        await self.session.commit()
        await self.session.refresh(group)
        return group

    async def add_user_in_group(self, group: GroupModel, user: UserModel) -> UserModel:
        group.users.append(user)
        await self.session.commit()
        return user

    async def delete_user_group(self, group: GroupModel, user: UserModel) -> UserModel:
        group.users.remove(user)
        await self.session.commit()
        return user

    async def delete_group(self, group: GroupModel) -> GroupModel:
        group.users.clear()
        await self.session.delete(group)
        await self.session.commit()
        return group

    async def get_group_users(self, group_id: int) -> list[UserModel]:
        group = await self.get_by_id_users_in_group(group_id)
        if not group:
            return []
        return group.users

    async def get_user_groups(self, user_id: int) -> list[GroupModel]:
        result = await self.session.execute(
            select(GroupModel)
            .options(selectinload(GroupModel.users))
            .where(GroupModel.users.any(UserModel.id == user_id))
        )
        user = list(result.scalars().all())
        return user

    def get_groups_paginated_for_user(self, query, user_id: int) -> Select:
        result = query.where(GroupModel.users.any(id=user_id))
        return result

    async def get_groups_paginated_total(self, query):
        result = await self.session.scalar(
            select(func.count()).select_from(query.subquery())
        )
        return result

    async def get_groups_offset_limit(self, query, offset, limit):
        query = query.offset(offset).limit(limit)
        result = await self.session.execute(query)
        groups = result.scalars().all()
        return groups

    async def get_groups_paginated_for_access(
        self,
        *,
        user_id: int,
        unrestricted: bool,
        offset: int,
        limit: int,
    ):
        query = select(GroupModel)
        if not unrestricted:
            query = self.get_groups_paginated_for_user(query, user_id)

        total = await self.get_groups_paginated_total(query)
        groups = await self.get_groups_offset_limit(query, offset, limit)
        return groups, total

    async def get_user_group(self, group_id):
        groups = (
            select(UserModel).join(UserModel.groups).where(GroupModel.id == group_id)
        )
        return groups

    async def get_group_users_with_telegram(
        self, group_id: int, exclude_user_id: Optional[int] = None
    ):
        """Возвращает пользователей группы, у которых есть telegram_id."""
        query = (
            select(UserModel).join(UserModel.groups).where(GroupModel.id == group_id)
        )
        if exclude_user_id is not None:
            query = query.where(UserModel.id != exclude_user_id)
        # Добавляем фильтр по наличию telegram_id
        query = query.where(UserModel.telegram_id.isnot(None))
        result = await self.session.execute(query)
        return result.scalars().all()
