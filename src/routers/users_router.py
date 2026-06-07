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


@router.post(
    "",
    response_model=UserSchema,
    status_code=201,
    summary="Создать пользователя",
    description="""
Создаёт нового пользователя в системе.

**Требует роль admin** (проверяется внутри сервиса).

Side-effects:
- Инвалидирует кэш пользователей и групп в Redis.

Пароль хранится в виде bcrypt-хэша — в ответе не возвращается.
""",
    responses={
        201: {"description": "Пользователь создан"},
        400: {"description": "Пользователь с таким именем уже существует"},
        403: {"description": "Недостаточно прав — требуется роль admin"},
    },
)
async def create_user(
    data: UserRegister,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    user = await get_user_service(session).create_user(data, current_user)

    await cache_manager.invalidate_users()
    await cache_manager.invalidate_groups()

    return user


@router.get(
    "",
    response_model=PaginatedResponse[UserSchema],
    summary="Список пользователей",
    description="""
Возвращает постранично всех пользователей системы.

**Требует роль admin или manager.**

Ответ кэшируется в Redis на 300 секунд (ключ привязан к пользователю и странице).
""",
    responses={
        200: {
            "description": "Список пользователей с метаданными пагинации",
            "content": {
                "application/json": {
                    "example": {
                        "items": [
                            {
                                "id": 1,
                                "username": "alice",
                                "role": "admin",
                                "is_active": True,
                                "telegram_id": 123456789,
                            }
                        ],
                        "total": 1,
                        "page": 1,
                        "size": 20,
                        "pages": 1,
                    }
                }
            },
        },
        403: {"description": "Недостаточно прав"},
    },
)
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


@router.get(
    "/{user_id}",
    response_model=UserSchema,
    summary="Получить пользователя",
    description="""
Возвращает данные конкретного пользователя по ID.

Обычный пользователь может смотреть **только свой** профиль.
Admin видит любого пользователя.
""",
    responses={
        200: {"description": "Данные пользователя"},
        403: {"description": "Нет доступа к чужому профилю"},
        404: {"description": "Пользователь не найден"},
    },
)
async def get_user(
    user_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_service(session).get_user(user_id, current_user)


@router.patch(
    "/{user_id}",
    response_model=UserSchema,
    summary="Обновить пользователя",
    description="""
Обновляет имя пользователя и/или пароль.

Обычный пользователь может менять **только свои** данные.
Admin может менять данные любого пользователя.

Side-effects:
- Инвалидирует кэш пользователей и групп в Redis.
""",
    responses={
        200: {"description": "Обновлённые данные пользователя"},
        403: {"description": "Нет доступа к чужому профилю"},
        404: {"description": "Пользователь не найден"},
    },
)
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


@router.delete(
    "/{user_id}",
    response_model=dict,
    summary="Удалить пользователя",
    description="""
Удаляет пользователя из системы.

**Требует роль admin** (проверяется внутри сервиса).

Side-effects:
- Инвалидирует кэш пользователей и групп в Redis.
""",
    responses={
        200: {"description": "Пользователь удален"},
        403: {"description": "Недостаточно прав — требуется роль admin"},
        404: {"description": "Пользователь не найден"},
    },
)
async def delete_user(
    user_id: int,
    session: SessionDep,
    admin: UserModel = Depends(get_current_admin),  # ← только admin
):
    user = await get_user_service(session).delete_user(user_id)

    await cache_manager.invalidate_users()
    await cache_manager.invalidate_groups()

    return user
