from fastapi import BackgroundTasks
import asyncio
import structlog
from src.repositories.abstract import AbstractGroupRepository, AbstractUserRepository
from src.core.constants import GROUP_NOT_FOUND, USER_OR_GROUP_NOT_FOUND
from src.core.exceptions import group_already_exists, not_found
from src.models.group import ConfirmDelete, GroupModel
from src.models.user import UserModel
from src.schemas.group import GroupCreate
from src.utils.reminders import notify_group_assigned

logger = structlog.get_logger()


class GroupService:
    """Сервис управления группами пользователей.

    Группы используются для назначения задач сразу нескольким людям.
    Сервис управляет составом групп и их жизненным циклом.
    """

    def __init__(
        self,
        group_repo: AbstractGroupRepository,
        user_repo: AbstractUserRepository,
    ):
        self.group_repo = group_repo
        self.user_repo = user_repo

    async def create_group(self, data: GroupCreate) -> GroupModel:
        """Создаёт новую группу с уникальным именем.

        Зачем: имена групп должны быть уникальными, чтобы при назначении задачи
        не возникало путаницы между одноимёнными группами.

        Side-effects:
            - Логирует событие group_created.

        Raises:
            HTTPException 409: группа с таким именем уже существует.
        """
        existing = await self.group_repo.get_id_group_for_name(data.name)
        if existing:
            group_already_exists()

        group = GroupModel(name=data.name)
        created_group = await self.group_repo.create(group)
        await logger.ainfo(
            "group_created",
            group_id=created_group.id,
            name=created_group.name,
        )
        return created_group

    async def get_groups(self) -> list[GroupModel]:
        """Возвращает все группы без пагинации.

        Зачем: используется внутри системы (Telegram-бот, admin-панель).
        Для API-ответов предпочтительнее get_groups_paginated.
        """
        return await self.group_repo.get_all()

    async def add_user_to_group(
        self,
        group_id: int,
        user_id: int,
        background_tasks: BackgroundTasks | None = None,
    ) -> dict[str, str]:
        """Добавляет пользователя в группу.

        Зачем: после добавления пользователь начинает видеть задачи группы
        и получать уведомления о них.

        Идемпотентен: если пользователь уже в группе — возвращает успех без изменений.

        Side-effects:
            - Отправляет Telegram-уведомление через notify_group_assigned.
              Если передан background_tasks — выполняется в фоне FastAPI,
              иначе — через asyncio.create_task (например, из Telegram-бота).

        Raises:
            HTTPException 404: пользователь или группа не найдены.
        """
        group = await self.group_repo.get_by_id_users_in_group(group_id)
        user = await self.user_repo.get_user_id(user_id)

        if not group or not user:
            not_found(USER_OR_GROUP_NOT_FOUND)

        if user in group.users:
            return {"message": "User already in group"}

        await self.group_repo.add_user_in_group(group, user)
        await logger.ainfo("user_added_to_group", user_id=user_id, group_id=group_id)

        if background_tasks:
            background_tasks.add_task(
                notify_group_assigned, user_id, group_id, group.name
            )
        else:
            asyncio.create_task(notify_group_assigned(user_id, group_id, group.name))

        return {"message": "User added to group", "group_name": group.name}

    async def get_group_users(self, group_id: int) -> list[UserModel]:
        """Возвращает всех участников группы без пагинации.

        Зачем: используется внутри сервиса уведомлений для получения
        списка получателей при назначении групповой задачи.

        Raises:
            HTTPException 404: группа не найдена.
        """
        group = await self.group_repo.get_by_id_users_in_group(group_id)
        if not group:
            not_found()
        return group.users

    async def delete_group_user(
        self,
        group_id: int,
        user_id: int,
    ):
        """Удаляет пользователя из группы.

        Зачем: при исключении из группы пользователь перестаёт получать
        групповые задачи и уведомления.

        Идемпотентен: если пользователь не в группе — возвращает успех.

        Side-effects:
            - Логирует событие user_removed_from_group.

        Raises:
            HTTPException 404: пользователь или группа не найдены.
        """
        group = await self.group_repo.get_by_id_users_in_group(group_id)
        user = await self.user_repo.get_user_id(user_id)

        if not group or not user:
            not_found()

        if user not in group.users:
            return {"message": "User not in group"}

        await self.group_repo.delete_user_group(group, user)
        await logger.ainfo(
            "user_removed_from_group", user_id=user_id, group_id=group_id
        )

        return {"message": f"User {user_id} removed from group {group_id}"}

    async def delete_group(self, group_id: int, data: ConfirmDelete) -> dict:
        """Удаляет группу после подтверждения её имени.

        Зачем: группы могут содержать задачи. Подтверждение именем
        защищает от случайного удаления активной группы.

        Side-effects:
            - Очищает связи пользователей с группой (group.users.clear()).
            - Физически удаляет запись группы из БД.

        Returns:
            Сообщение об удалении или о несовпадении имени (не бросает 4xx).
        """
        group = await self.group_repo.get_by_id(group_id)
        if not group:
            return not_found()

        if data.group_name != group.name:
            return {"message": "Введите точное имя группы для удаления"}

        await self.group_repo.delete_group(group)
        return {"message": f"Group {group_id} deleted"}

    async def get_groups_paginated(
        self, offset: int, limit: int, user: UserModel
    ) -> tuple[list[GroupModel], int]:
        """Возвращает (groups, total) с учётом прав доступа пользователя.

        Зачем: обычный пользователь не должен видеть группы, в которых не состоит —
        это могло бы раскрыть структуру организации.
        Admin/manager видят все группы для управления составом.
        """
        return await self.group_repo.get_groups_paginated_for_access(
            user_id=user.id,
            unrestricted=user.role in ["admin", "manager"],
            offset=offset,
            limit=limit,
        )

    async def get_group_users_paginated(
        self, group_id: int, offset: int, limit: int, user: UserModel
    ) -> tuple[list[UserModel], int]:
        """Возвращает (users, total) для группы с пагинацией.

        Зачем: группы могут быть большими — постраничная загрузка
        участников снижает нагрузку на БД и объём ответа.

        Raises:
            HTTPException 404: группа не найдена.
        """
        # Проверка существования группы и прав доступа если нужно
        group = await self.group_repo.get_by_id(group_id)
        if not group:
            raise not_found(GROUP_NOT_FOUND)
        # Можете добавить проверку, что user видит эту группу
        query = await self.group_repo.get_user_group(group_id)

        total = await self.group_repo.get_groups_paginated_total(query)

        users = await self.group_repo.get_groups_offset_limit(query, offset, limit)
        return users, total
