from src.core.constants import LAST_ADMIN_CANNOT_BE_DEMOTED, NO_ACCESS, USER_ALREADY_EXISTS, USER_NOT_FOUND
from src.core.exceptions import (
    current_admin,
    incorrect_request,
    invalid_credentials,
    no_access,
    user_already_exists,
    user_not_found,
)
from src.core.security import hash_password, verify_password
from src.models.user import UserModel
from src.repositories.abstract import AbstractUserRepository
from src.schemas.user import UserRegister, UserUpdate
from src.services.login_service import generate_unique_login


class UserService:
    """Сервис управления пользователями.

    Инкапсулирует бизнес-правила доступа к данным пользователей:
    кто может создавать, читать, обновлять и удалять учётные записи.
    """

    def __init__(self, user_repo: AbstractUserRepository):
        self.user_repo = user_repo

    async def create_user(self, data: UserRegister, current_user: UserModel) -> UserModel:
        """Создаёт нового пользователя.

        Зачем: создание учётных записей доступно только admin —
        самостоятельная регистрация в системе отключена.

        Side-effects:
            - Пароль хэшируется через bcrypt перед сохранением в БД.

        Raises:
            HTTPException 403: если текущий пользователь не admin.
            HTTPException 400: если username уже занят.
        """
        if current_user.role != "admin":
            current_admin()

        existing = await self.user_repo.get_by_username(data.username)
        if existing:
            user_already_exists(USER_ALREADY_EXISTS)

        login = await generate_unique_login(data.username, self.user_repo)
        new_user = UserModel(
            username=data.username,
            login=login,
            password_hash=hash_password(data.password),
            role=data.role,
        )
        return await self.user_repo.create(new_user)

    async def get_users(self) -> list[UserModel]:
        """Возвращает всех пользователей без пагинации.

        Зачем: используется внутри системы (например, в админке).
        Для API-ответов предпочтительнее get_users_paginated.
        """
        return await self.user_repo.get_all()

    async def get_user(self, user_id: int, current_user: UserModel) -> UserModel:
        """Возвращает пользователя по ID.

        Видимость — как у задач/ленты активности/статистики в этом
        приложении: общая для всей команды (см. страницу профиля
        пользователя и справочник команды). Раньше здесь была проверка
        "только свой профиль или admin", но она стала противоречить новому
        функционалу (открыть чужой профиль по клику на имя) — убрана для
        консистентности с остальным приложением.

        Raises:
            HTTPException 404: пользователь не найден.
        """
        user = await self.user_repo.get_user_id(user_id)
        if not user:
            user_not_found(USER_NOT_FOUND)
            raise

        return user

    async def update_user(self, user_id: int, data: UserUpdate, current_user: UserModel) -> UserModel:
        """Обновляет имя пользователя и/или пароль.

        Зачем: пользователь может менять только свои данные.
        Admin может менять данные любого пользователя (например, сброс пароля).

        Side-effects:
            - При смене пароля он немедленно хэшируется через bcrypt.
            - После обновления данные сессии SQLAlchemy рефрешатся.

        Raises:
            HTTPException 404: пользователь не найден.
            HTTPException 403: попытка изменить чужой профиль без прав admin.
        """
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
        if data.position is not None:
            user.position = data.position or None

        return await self.user_repo.update(user)

    async def change_role(self, user_id: int, new_role: str, current_user: UserModel) -> UserModel:
        """Меняет роль участника своей компании (user / manager / admin).

        Правила:
            - только admin компании (проверяется и здесь, не только в роутере);
            - только пользователи ТОЙ ЖЕ компании — чужой id отвечает 404, как будто его нет;
            - нельзя понизить последнего активного админа (в т.ч. себя): компания
              осталась бы без администратора, а вернуть доступ можно только через SQLAdmin;
            - is_platform_admin эндпоинтом не затрагивается;
            - то же значение — no-op без записи в аудит.

        Raises:
            HTTPException 403: текущий пользователь не admin.
            HTTPException 404: пользователь не найден (или из другой компании).
            HTTPException 400: попытка понизить единственного админа.
        """
        if current_user.role != "admin":
            current_admin()

        user = await self.user_repo.get_user_id(user_id)
        if not user or user.workspace_id != current_user.workspace_id:
            user_not_found(USER_NOT_FOUND)
            raise

        if str(user.role) == new_role:
            return user

        if str(user.role) == "admin" and new_role != "admin":
            if await self.user_repo.count_active_admins(user.workspace_id) <= 1:
                incorrect_request(LAST_ADMIN_CANNOT_BE_DEMOTED)

        return await self.user_repo.update_role(user, new_role, current_user.id)

    async def delete_user(self, user_id: int) -> dict:
        """Полностью удаляет пользователя из БД (hard delete).

        Зачем: операция доступна только admin и выполняется из роутера,
        уже защищённого зависимостью get_current_admin.

        Raises:
            HTTPException 404: пользователь не найден.
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            user_not_found(USER_NOT_FOUND)
            raise

        await self.user_repo.delete(user)
        return {"message": f"User {user_id} deleted"}

    async def get_users_paginated(self, offset: int, limit: int):
        """Возвращает (users, total) для постраничного вывода.

        Зачем: разделяет построение запроса и его выполнение —
        total считается отдельным COUNT-запросом, чтобы не тащить все строки в память.
        """
        query = self.user_repo.select_users_offset_limit(offset, limit)
        total = await self.user_repo.get_total_count(UserModel)
        users = await self.user_repo.execute_scalars(query)
        return users, total

    async def change_password(self, user: UserModel, current_password: str, new_password: str) -> None:
        """
        Пользователь меняет свой пароль сам (в т.ч. обязательная смена
        сгенерированного пароля после регистрации через Telegram-бота —
        см. UserModel.must_change_password).
        """
        if not verify_password(current_password, user.password_hash):
            invalid_credentials("Текущий пароль указан неверно")

        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        await self.user_repo.update(user)
