from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi_cache.decorator import cache

from src.core.config import ATTACHMENTS_STORAGE_PATH
from src.core.dependencies import (
    get_current_admin,
    get_current_user,
)
from src.core.exceptions import not_found
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.groups_repository import GroupRepository
from src.repositories.tag_repository import TagRepository
from src.repositories.task_repository import TaskRepository
from src.repositories.users_repository import UserRepository
from src.schemas.pagination import PaginatedResponse, PaginationParams
from src.schemas.user import ChangePasswordRequest, UserRegister, UserSchema, UserUpdate
from src.services.active_storage import storage
from src.services.task_service import TaskService
from src.services.user_service import UserService
from src.utils.cache_keys import user_scoped_key_builder
from src.utils.cache_manager import cache_manager

_LOCAL_STORAGE_BASE = Path(ATTACHMENTS_STORAGE_PATH).resolve()
MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5 МБ — с запасом достаточно для фото профиля

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/me",
    response_model=UserSchema,
    summary="Текущий пользователь",
    description="Возвращает данные авторизованного пользователя. "
    "Удобный способ получить свой профиль без знания user_id.",
)
async def get_me(
    current_user: UserModel = Depends(get_current_user),
):
    return current_user


@router.post(
    "/me/password",
    status_code=204,
    summary="Сменить свой пароль",
    description=(
        "Требует текущий пароль. Сбрасывает флаг must_change_password, если он был "
        "установлен (например, после автосоздания учётки через Telegram-бота)."
    ),
)
async def change_my_password(
    data: ChangePasswordRequest,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    await get_user_service(session).change_password(current_user, data.current_password, data.new_password)


def get_user_service(session: SessionDep):
    return UserService(UserRepository(session))


@router.get(
    "/{user_id}/stats",
    summary="Статистика задач пользователя",
    description="Возвращает агрегированную статистику задач: всего, выполнено, в работе, последние задачи.",
)
async def get_user_stats(
    user_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    # Видимость статистики — как у задач и ленты активности в этом
    # приложении: общая для всей команды, без скоупинга по владельцу
    # (см. страницу профиля пользователя). Авторизация всё равно нужна —
    # просто не ограничиваем конкретно "только своё".
    return await TaskService(
        task_repo=TaskRepository(session),
        user_repo=UserRepository(session),
        group_repo=GroupRepository(session),
        tag_repo=TagRepository(session),
        session=session,
    ).get_user_stats(user_id)


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
Возвращает постранично всех пользователей системы — справочник команды.

Видимость общая для всей команды (как у задач/ленты активности/статистики
в этом приложении), права admin/manager не требуются.

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
                                "position": "Backend-разработчик",
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
    },
)
@cache(expire=300, namespace="users", key_builder=user_scoped_key_builder)
async def get_users(
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
):
    """Список пользователей с пагинацией"""
    service = get_user_service(session)
    users, total = await service.get_users_paginated(offset=pagination.offset, limit=pagination.size)

    # 🔁 Преобразуем SQLAlchemy объекты в Pydantic схемы
    users_schemas = [UserSchema.model_validate(user) for user in users]

    return PaginatedResponse.create(items=users_schemas, total=total, page=pagination.page, size=pagination.size)


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


# ── Аватар профиля ───────────────────────────────────────────────────────
# Тот же storage backend, что и у вложений задач (src/services/active_storage.py),
# но раздача СПЕЦИАЛЬНО без авторизации: фото профиля — не приватные данные
# (в отличие от вложений задач), а <img src="..."> физически не может
# отправить заголовок Authorization, так что эндпоинт публичный по дизайну.


@router.post(
    "/me/avatar",
    response_model=UserSchema,
    summary="Загрузить свой аватар",
    description="Принимает multipart/form-data с изображением. Максимум 5 МБ. Заменяет предыдущий аватар.",
    responses={413: {"description": "Файл превышает 5 МБ"}},
)
async def upload_my_avatar(
    session: SessionDep,
    file: UploadFile = File(...),
    current_user: UserModel = Depends(get_current_user),
):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=415, detail="Аватар должен быть изображением")

    data = await file.read()
    if len(data) > MAX_AVATAR_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Файл слишком большой: {len(data) // (1024 * 1024)} МБ. Максимум 5 МБ.",
        )

    # Чистим предыдущий файл, чтобы не копить мусор в сторадже
    if current_user.avatar_storage_key and storage.is_configured:
        try:
            await storage.delete(current_user.avatar_storage_key)
        except Exception:  # noqa: BLE001 — не блокируем загрузку нового аватара из-за сбоя очистки старого
            pass

    key = storage.build_key(f"avatars/{current_user.id}", file.filename or "avatar")
    url = await storage.upload(key=key, data=data, content_type=file.content_type)

    current_user.avatar_storage_key = key
    current_user.avatar_storage_url = url or None
    await session.commit()
    await session.refresh(current_user)

    await cache_manager.invalidate_users()
    return current_user


@router.delete(
    "/me/avatar",
    status_code=204,
    summary="Удалить свой аватар",
)
async def delete_my_avatar(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    if current_user.avatar_storage_key and storage.is_configured:
        try:
            await storage.delete(current_user.avatar_storage_key)
        except Exception:  # noqa: BLE001
            pass

    current_user.avatar_storage_key = None
    current_user.avatar_storage_url = None
    await session.commit()
    await cache_manager.invalidate_users()


@router.get(
    "/{user_id}/avatar",
    summary="Получить аватар пользователя (без авторизации)",
    responses={404: {"description": "Аватар не задан"}},
)
async def get_user_avatar(user_id: int, session: SessionDep):
    user = await UserRepository(session).get_user_id(user_id)
    if not user or not user.avatar_storage_key:
        not_found("Аватар не задан")

    # R2 (или другой backend с публичным URL) — редиректим на прямую ссылку
    if user.avatar_storage_url:
        return RedirectResponse(user.avatar_storage_url)

    # Локальный storage — стримим файл напрямую с диска
    target_path = (_LOCAL_STORAGE_BASE / user.avatar_storage_key).resolve()
    if _LOCAL_STORAGE_BASE not in target_path.parents or not target_path.is_file():
        not_found("Аватар не задан")
    return FileResponse(target_path)
