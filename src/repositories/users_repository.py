from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import UserModel
from src.repositories.abstract.base_user_repository import AbstractUserRepository


class UserRepository(AbstractUserRepository):

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self) -> list[UserModel]:
        result = await self.session.execute(select(UserModel))
        return list(result.scalars().all())

    async def get_by_id(self, user_id: int) -> UserModel | None:
        result = await self.session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_user_id(self, user_id: int) -> UserModel | None:
        return await self.session.get(UserModel, user_id)

    async def get_users_limit(self, limit: int, offset: int) -> list[UserModel]:
        result = await self.session.execute(
            select(UserModel).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def create(self, user: UserModel) -> UserModel:
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_by_username(self, username: str) -> UserModel | None:
        return await self.session.scalar(
            select(UserModel).where(UserModel.username == username)
        )

    async def update(self, user: UserModel) -> UserModel:
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def delete(self, user: UserModel) -> None:
        await self.session.delete(user)
        await self.session.commit()

    async def get_by_telegram_id(self, telegram_id: int) -> UserModel | None:
        result = await self.session.execute(
            select(UserModel).where(UserModel.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def set_role(self, username: str, role: str) -> None:
        await self.session.execute(
            update(UserModel).where(UserModel.username == username).values(role=role)
        )
        await self.session.commit()

    async def get_admin_by_username(self, username: str) -> UserModel | None:
        return await self.session.scalar(
            select(UserModel).where(
                UserModel.username == username,
                UserModel.role == "admin",
            )
        )

    def select_users_offset_limit(self, offset: int, limit: int):
        query = select(UserModel).offset(offset).limit(limit)
        return query

    async def get_total_count(self, model) -> int:
        result = await self.session.scalar(select(func.count()).select_from(model))
        return result or 0

    async def execute_scalars(self, query: Select):
        """Выполняет запрос и возвращает scalars()"""
        result = await self.session.execute(query)
        return result.scalars().all()

    async def select_user(self, stmt):
        """Выбирает одного пользователя по запросу"""
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
