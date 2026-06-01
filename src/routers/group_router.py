from fastapi import APIRouter, BackgroundTasks, Depends
from src.db import SessionDep
from src.models.group import ConfirmDelete
from src.models.user import UserModel
from src.schemas.group import GroupCreate, GroupSchema
from src.schemas.user import UserSchema
from src.core.dependencies import (
    get_current_admin,
    get_current_user,
    get_current_manager,
)
from src.services.group_service import GroupService
from src.repositories.groups_repository import GroupRepository
from src.repositories.users_repository import UserRepository

from fastapi_cache.decorator import cache
from src.utils.cache_keys import user_scoped_key_builder
from src.utils.cache_manager import cache_manager
from src.schemas.pagination import PaginationParams, PaginatedResponse

router = APIRouter(prefix="/groups", tags=["Groups"])


def get_group_service(session: SessionDep) -> GroupService:
    return GroupService(
        GroupRepository(session),
        UserRepository(session),
    )


@router.post("", response_model=GroupSchema)
async def create_group(
    data: GroupCreate,
    session: SessionDep,
    admin: UserModel = Depends(get_current_admin),  # ← только admin
):

    group = await get_group_service(session).create_group(data)

    await cache_manager.invalidate_groups()

    return group


@router.get("", response_model=PaginatedResponse[GroupSchema])
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

    # 🔁 Преобразуем SQLAlchemy объекты в Pydantic схемы
    groups_schemas = [GroupSchema.model_validate(group) for group in groups]

    return PaginatedResponse.create(
        items=groups_schemas, total=total, page=pagination.page, size=pagination.size
    )


@router.post("/{group_id}/users/{user_id}", response_model=dict)
async def add_user_to_group(
    group_id: int,
    user_id: int,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    current_user: UserModel = Depends(get_current_manager),  # ← admin + manager
):
    # 1. Добавляем пользователя в группу через сервис
    user = await get_group_service(session).add_user_to_group(
        group_id, user_id, background_tasks
    )

    await cache_manager.invalidate_groups()

    return {"message": f"User {user_id} added to group {group_id}", "user": user}


@router.get("/{group_id}/users", response_model=PaginatedResponse[UserSchema])
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

    # 🔁 Преобразуем SQLAlchemy объекты в Pydantic схемы
    users_schemas = [UserSchema.model_validate(user) for user in users]

    return PaginatedResponse.create(
        items=users_schemas, total=total, page=pagination.page, size=pagination.size
    )


@router.delete("/{group_id}/users/{user_id}", response_model=dict)
async def delete_group_user(
    group_id: int,
    user_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_manager),  # ← admin + manager
):
    result = await get_group_service(session).delete_group_user(group_id, user_id)
    await cache_manager.invalidate_groups()
    return result


@router.delete("/{group_id}", response_model=dict)
async def delete_group(
    group_id: int,
    data: ConfirmDelete,
    session: SessionDep,
    admin: UserModel = Depends(get_current_admin),  # ← только admin
):

    group = await get_group_service(session).delete_group(group_id, data)

    # await invalidate_cache("groups", redis)
    await cache_manager.invalidate_groups()

    return group
