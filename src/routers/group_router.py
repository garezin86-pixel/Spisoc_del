from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi_cache.decorator import cache

from src.core.dependencies import (
    get_current_admin,
    get_current_manager,
    get_current_user,
)
from src.db import SessionDep
from src.models.group import ConfirmDelete
from src.models.user import UserModel
from src.repositories.groups_repository import GroupRepository
from src.repositories.users_repository import UserRepository
from src.schemas.group import GroupCreate, GroupSchema
from src.schemas.pagination import PaginatedResponse, PaginationParams
from src.schemas.user import UserSchema
from src.services.group_service import GroupService
from src.utils.cache_keys import user_scoped_key_builder
from src.utils.cache_manager import cache_manager

router = APIRouter(prefix="/groups", tags=["Groups"])


def get_group_service(session: SessionDep) -> GroupService:
    return GroupService(
        GroupRepository(session),
        UserRepository(session),
    )


@router.post(
    "",
    response_model=GroupSchema,
    summary="Создать группу",
    description="""
Создаёт новую группу пользователей.

**Требует роль admin.**

Имя группы должно быть уникальным. Попытка создать группу с существующим именем вернёт 409.

Side-effects:
- Инвалидирует кэш групп в Redis.
""",
    responses={
        200: {
            "description": "Группа создана",
            "content": {"application/json": {"example": {"id": 1, "name": "Backend Team"}}},
        },
        403: {"description": "Требуется роль admin"},
        409: {"description": "Группа с таким именем уже существует"},
    },
)
async def create_group(
    data: GroupCreate,
    session: SessionDep,
    admin: UserModel = Depends(get_current_admin),
):
    group = await get_group_service(session).create_group(data)
    await cache_manager.invalidate_groups()
    return group


@router.get(
    "",
    response_model=PaginatedResponse[GroupSchema],
    summary="Список групп",
    description="""
Возвращает постраничный список групп.

- Admin/manager видят **все** группы.
- Обычный пользователь видит только группы, **членом которых является**.

Ответ кэшируется в Redis на 300 секунд (ключ привязан к пользователю).
""",
    responses={
        200: {
            "description": "Список групп с метаданными пагинации",
            "content": {
                "application/json": {
                    "example": {
                        "items": [{"id": 1, "name": "Backend Team"}],
                        "total": 1,
                        "page": 1,
                        "size": 20,
                        "pages": 1,
                    }
                }
            },
        },
    },
)
@cache(expire=300, namespace="groups", key_builder=user_scoped_key_builder)
async def get_group(
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
):
    """Получить список групп с пагинацией"""
    service = get_group_service(session)
    groups, total = await service.get_groups_paginated(
        offset=pagination.offset, limit=pagination.size, user=current_user
    )
    groups_schemas = [GroupSchema.model_validate(group) for group in groups]
    return PaginatedResponse.create(items=groups_schemas, total=total, page=pagination.page, size=pagination.size)


@router.post(
    "/{group_id}/users/{user_id}",
    response_model=dict,
    summary="Добавить пользователя в группу",
    description="""
Добавляет существующего пользователя в группу.

**Требует роль admin или manager.**

Если пользователь уже состоит в группе — возвращает успешный ответ без изменений.

Side-effects:
- Отправляет Telegram-уведомление пользователю о добавлении в группу (в фоне).
- Инвалидирует кэш групп в Redis.
""",
    responses={
        200: {
            "description": "Пользователь добавлен (или уже состоял в группе)",
            "content": {
                "application/json": {
                    "example": {
                        "message": "User 3 added to group 1",
                        "user": {"id": 3, "username": "bob"},
                    }
                }
            },
        },
        403: {"description": "Требуется роль admin или manager"},
        404: {"description": "Пользователь или группа не найдены"},
    },
)
async def add_user_to_group(
    group_id: int,
    user_id: int,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    current_user: UserModel = Depends(get_current_manager),
):
    user = await get_group_service(session).add_user_to_group(group_id, user_id, background_tasks)
    await cache_manager.invalidate_groups()
    return {"message": f"User {user_id} added to group {group_id}", "user": user}


@router.get(
    "/{group_id}/users",
    response_model=PaginatedResponse[UserSchema],
    summary="Участники группы",
    description="""
Возвращает постраничный список пользователей группы.

Ответ кэшируется в Redis на 300 секунд.
""",
    responses={
        200: {"description": "Список участников группы"},
        404: {"description": "Группа не найдена"},
    },
)
@cache(expire=300, namespace="groups", key_builder=user_scoped_key_builder)
async def get_group_users(
    group_id: int,
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
):
    """Получить пользователей группы с пагинацией"""
    service = get_group_service(session)
    users, total = await service.get_group_users_paginated(
        group_id=group_id,
        offset=pagination.offset,
        limit=pagination.size,
        user=current_user,
    )
    users_schemas = [UserSchema.model_validate(user) for user in users]
    return PaginatedResponse.create(items=users_schemas, total=total, page=pagination.page, size=pagination.size)


@router.delete(
    "/{group_id}/users/{user_id}",
    response_model=dict,
    summary="Удалить пользователя из группы",
    description="""
Исключает пользователя из группы.

**Требует роль admin или manager.**

Если пользователь не состоит в группе — возвращает успешный ответ без изменений.

Side-effects:
- Инвалидирует кэш групп в Redis.
""",
    responses={
        200: {
            "description": "Пользователь удалён из группы",
            "content": {"application/json": {"example": {"message": "User 3 removed from group 1"}}},
        },
        403: {"description": "Требуется роль admin или manager"},
        404: {"description": "Пользователь или группа не найдены"},
    },
)
async def delete_group_user(
    group_id: int,
    user_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_manager),
):
    result = await get_group_service(session).delete_group_user(group_id, user_id)
    await cache_manager.invalidate_groups()
    return result


@router.delete(
    "/{group_id}",
    response_model=dict,
    summary="Удалить группу",
    description="""
Полностью удаляет группу и все связи с пользователями.

**Требует роль admin.**

Для подтверждения необходимо передать точное имя группы в теле запроса (`group_name`).
Это защита от случайного удаления.

Side-effects:
- Инвалидирует кэш групп в Redis.
- Задачи, назначенные группе, остаются в БД с `group_id = NULL` (зависит от настроек FK).
""",
    responses={
        200: {
            "description": "Группа удалена или имя не совпало",
            "content": {
                "application/json": {
                    "examples": {
                        "deleted": {"value": {"message": "Group 1 deleted"}},
                        "mismatch": {"value": {"message": "Введите точное имя группы для удаления"}},
                    }
                }
            },
        },
        403: {"description": "Требуется роль admin"},
        404: {"description": "Группа не найдена"},
    },
)
async def delete_group(
    group_id: int,
    data: ConfirmDelete,
    session: SessionDep,
    admin: UserModel = Depends(get_current_admin),
):
    group = await get_group_service(session).delete_group(group_id, data)
    await cache_manager.invalidate_groups()
    return group
