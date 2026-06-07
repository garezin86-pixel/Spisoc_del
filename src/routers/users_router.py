from fastapi import APIRouter, Depends
from src.db import SessionDep
from src.schemas.user import UserRegister, UserSchema, UserUpdate
from src.models.user import UserModel
from src.core.dependencies import (
    get_current_admin,
    get_current_user,
    get_current_manager,
)
from src.services.user_service import UserService
from src.repositories.users_repository import UserRepository

from fastapi_cache.decorator import cache
from src.utils.cache_keys import user_scoped_key_builder
from src.utils.cache_manager import cache_manager
from src.schemas.pagination import PaginationParams, PaginatedResponse

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/me",
    response_model=UserSchema,
    summary="Текущий пользователь",
    description="Возвращает данные авторизованного пользователя. Удобный способ получить свой профиль без знания user_id.",
)
async def get_me(
    current_user: UserModel = Depends(get_current_user),
):
    return current_user


def get_user_service(session: SessionDep):
    return UserService(UserRepository(session))


@router.post("", response_model=UserSchema, status_code=201)
async def create_user(
    data: UserRegister,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    user = await get_user_service(session).create_user(data, current_user)

    await cache_manager.invalidate_users()
    await cache_manager.invalidate_groups()

    return user


@router.get("", response_model=PaginatedResponse[UserSchema])
@cache(expire=300, namespace="users", key_builder=user_scoped_key_builder)
async def get_users(
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_manager),
):
    """Список пользователей с пагинацией"""
    service = get_user_service(session)
    users, total = await service.get_users_paginated(
        offset=pagination.offset, limit=pagination.size
    )

    # 🔁 Преобразуем SQLAlchemy объекты в Pydantic схемы
    users_schemas = [UserSchema.model_validate(user) for user in users]

    return PaginatedResponse.create(
        items=users_schemas, total=total, page=pagination.page, size=pagination.size
    )


@router.get("/{user_id}", response_model=UserSchema)
async def get_user(
    user_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_service(session).get_user(user_id, current_user)


@router.patch("/{user_id}", response_model=UserSchema)
async def update_user(
    user_id: int,
    data: UserUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    user = await get_user_service(session).update_user(user_id, data, current_user)

    await cache_manager.invalidate_users()
    await cache_manager.invalidate_groups()

    return user


@router.delete("/{user_id}", response_model=dict)
async def delete_user(
    user_id: int,
    session: SessionDep,
    admin: UserModel = Depends(get_current_admin),  # ← только admin
):
    user = await get_user_service(session).delete_user(user_id)

    await cache_manager.invalidate_users()
    await cache_manager.invalidate_groups()

    return user
