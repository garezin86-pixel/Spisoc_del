from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import UserModel
from src.repositories.abstract.base_user_repository import AbstractUserRepository


class UserRepository(AbstractUserRepository):
    """Репозиторий пользователей.

    Все запросы к таблице users. Не содержит бизнес-логики:
    проверки прав и условий — в сервисах.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self) -> list[UserModel]:
        """Возвращает всех пользователей без пагинации. Используется в тестах и admin."""
        result = await self.session.execute(select(UserModel).order_by(UserModel.id))
        return list(result.scalars().all())

    async def get_by_id(self, user_id: int) -> UserModel | None:
        """Возвращает пользователя по первичному ключу через SELECT WHERE."""
        result = await self.session.execute(select(UserModel).where(UserModel.id == user_id))
        return result.scalar_one_or_none()

    async def get_user_id(self, user_id: int) -> UserModel | None:
        """Возвращает пользователя через session.get() (читает из identity map если уже загружен).

        Зачем: быстрее get_by_id когда объект уже находится в кэше сессии SQLAlchemy.
        """
        return await self.session.get(UserModel, user_id)

    async def get_users_limit(self, limit: int, offset: int) -> list[UserModel]:
        """Устаревший метод пагинации. Используйте select_users_offset_limit + execute_scalars."""
        result = await self.session.execute(select(UserModel).limit(limit).offset(offset))
        return list(result.scalars().all())

    async def create(self, user: UserModel) -> UserModel:
        """Сохраняет нового пользователя и рефрешит объект для получения id и created_at."""
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_by_username(self, username: str) -> UserModel | None:
        """Ищет пользователя по уникальному username. Используется при логине и регистрации."""
        return await self.session.scalar(select(UserModel).where(UserModel.username == username))

    async def update(self, user: UserModel) -> UserModel:
        """Фиксирует изменения пользователя (commit + refresh).

        Зачем: изменения полей уже внесены в объект в сервисе,
        этот метод только сохраняет их в БД и синхронизирует updated_at.
        """
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def delete(self, user: UserModel) -> None:
        """Физически удаляет пользователя из БД."""
        await self.session.delete(user)
        await self.session.commit()

    async def get_by_telegram_id(self, telegram_id: int) -> UserModel | None:
        """Ищет пользователя по Telegram ID.

        Зачем: Telegram-бот идентифицирует пользователей по telegram_id,
        а не по username/password. Этот метод — точка входа для бота.
        """
        result = await self.session.execute(select(UserModel).where(UserModel.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def set_role(self, username: str, role: str) -> None:
        """Обновляет роль пользователя через UPDATE без загрузки объекта.

        Зачем: используется скриптом make_admin.py для выдачи роли admin
        напрямую через CLI без API.
        """
        await self.session.execute(update(UserModel).where(UserModel.username == username).values(role=role))
        await self.session.commit()

    async def get_admin_by_username(self, username: str) -> UserModel | None:
        """Возвращает пользователя только если он существует и имеет роль admin."""
        return await self.session.scalar(
            select(UserModel).where(
                UserModel.username == username,
                UserModel.role == "admin",
            )
        )

    def select_users_offset_limit(self, offset: int, limit: int) -> Select:
        """Строит SELECT-запрос с пагинацией (без выполнения).

        Зачем: позволяет разделить построение запроса и его выполнение —
        сервис сначала считает total через get_total_count, потом выполняет этот запрос.
        """
        query = select(UserModel).offset(offset).limit(limit)
        return query

    async def get_total_count(self, model) -> int:
        """Считает общее количество записей в таблице модели.

        Зачем: для корректной пагинации нужно знать total независимо от LIMIT.
        """
        result = await self.session.scalar(select(func.count()).select_from(model))
        return result or 0

    async def execute_scalars(self, query: Select):
        """Выполняет SELECT-запрос и возвращает список scalar-значений.

        Зачем: разделяет построение запроса (select_users_offset_limit)
        от его выполнения — упрощает тестирование и переиспользование запросов.
        """
        result = await self.session.execute(query)
        return result.scalars().all()

    async def select_user(self, stmt) -> UserModel | None:
        """Выполняет произвольный SELECT-запрос и возвращает одного пользователя."""
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
