from fastapi import APIRouter, Depends, Query
from fastapi import BackgroundTasks

from src.db import SessionDep
from src.models.user import UserModel
from src.schemas.task import (
    FilterUserGroup,
    SpisokAddSchema,
    SpisokSchema,
    SpisokUpdate,
    TaskFilter,
)
from src.core.dependencies import get_current_user
from src.services.notifications import notify_task_assigned
from src.services.task_service import TaskService
from src.repositories.task_repository import TaskRepository
from src.repositories.users_repository import UserRepository
from src.repositories.groups_repository import GroupRepository
from src.schemas.pagination import PaginationParams, PaginatedResponse
from fastapi_cache.decorator import cache
from src.utils.cache_keys import user_scoped_key_builder
from src.utils.cache_manager import cache_manager

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def get_task_service(session: SessionDep) -> TaskService:
    return TaskService(
        task_repo=TaskRepository(session),
        user_repo=UserRepository(session),
        group_repo=GroupRepository(session),
        session=session,
    )


@router.post(
    "",
    response_model=SpisokSchema,
    status_code=201,
    summary="Создать задачу",
    description="""
Создаёт новую задачу. Автором становится текущий пользователь.

Можно назначить либо конкретному пользователю (`user_id`), либо группе (`group_id`) — но **не одновременно**.

Side-effects:
- Запускает фоновую отправку Telegram-уведомления исполнителю/группе.
- Инвалидирует кэш задач в Redis.
- Пишет запись в audit-лог.
""",
    responses={
        201: {
            "description": "Задача создана",
            "content": {
                "application/json": {
                    "example": {
                        "id": 42,
                        "title": "Подготовить отчёт",
                        "description": "За Q3 2025",
                        "is_done": False,
                        "deadline": "31.12.2025 18:00",
                        "user_id": 3,
                        "group_id": None,
                        "author": {"id": 1, "username": "alice"},
                        "user": {"id": 3, "username": "bob"},
                        "group": None,
                        "created_at": "01.06.2025 10:00",
                        "updated_at": None,
                    }
                }
            },
        },
        400: {
            "description": "Нельзя указывать user_id и group_id одновременно, или один из них не существует"
        },
        401: {"description": "Не аутентифицирован"},
    },
)
async def add_task(
    data: SpisokAddSchema,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    session.info["audit_user_id"] = current_user.id
    task = await get_task_service(session).add_task(data, current_user)
    await cache_manager.invalidate_tasks()
    return task


@router.get(
    "/filter",
    response_model=PaginatedResponse[SpisokSchema],
    summary="Фильтрация задач",
    description="""
Возвращает задачи с фильтрацией и пагинацией.

**Параметры фильтрации:**

- `filter_user_group`:
  - `user` — задачи, назначенные текущему пользователю
  - `group` — задачи группы (требует `group_id`)
  - `free` — задачи без исполнителя и группы
  - `author` — задачи, созданные текущим пользователем

- `filter_type`:
  - `today` — дедлайн сегодня
  - `overdue` — дедлайн просрочен
  - `planned` — дедлайн в будущем
  - `deadline_null` — без дедлайна

- `is_done` — фильтр по статусу выполнения

Ответ кэшируется в Redis на 120 секунд.
""",
    responses={
        200: {"description": "Постраничный список задач"},
        400: {
            "description": "filter_user_group=group требует group_id; группа не найдена"
        },
    },
)
@cache(expire=120, namespace="tasks", key_builder=user_scoped_key_builder)
async def filter_tasks(
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
    filter_user_group: FilterUserGroup | None = Query(None),
    group_id: int | None = Query(None),
    filter_type: TaskFilter | None = Query(None),
    is_done: bool | None = Query(None),
    limit: int | None = Query(None, ge=1, le=100),
):
    final_limit = limit or pagination.size
    tasks, total = await get_task_service(session).filter_tasks_paginated(
        user=current_user,
        offset=pagination.offset,
        limit=final_limit,
        filter_user_group=filter_user_group,
        group_id=group_id,
        filter_type=filter_type,
        is_done=is_done,
    )
    return PaginatedResponse.create(
        items=[SpisokSchema.model_validate(task) for task in tasks],
        total=total,
        page=pagination.page,
        size=pagination.size,
    )


@router.get(
    "/trash",
    response_model=PaginatedResponse[SpisokSchema],
    summary="Корзина задач",
    description="""
Возвращает мягко удалённые задачи (soft-deleted), доступные пользователю.

- Обычный пользователь видит только задачи, где он **автор или исполнитель**.
- Admin/manager видит **все** удалённые задачи.

Поддерживает поиск по заголовку (`search`).

> ⚠️ Эндпоинт должен быть зарегистрирован **до** `/{task_id}`, иначе FastAPI интерпретирует «trash» как task_id.
""",
    responses={
        200: {"description": "Список удалённых задач с пагинацией"},
    },
)
async def list_deleted_tasks(
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
    search: str | None = Query(None),
):
    tasks, total = await get_task_service(session).get_deleted_tasks(
        user=current_user,
        offset=pagination.offset,
        limit=pagination.size,
        search=search,
    )
    return PaginatedResponse.create(
        items=tasks, total=total, page=pagination.page, size=pagination.size
    )


@router.get(
    "/{task_id}",
    response_model=SpisokSchema,
    summary="Получить задачу",
    description="""
Возвращает задачу по ID.

Доступ разрешён, если пользователь является:
- автором задачи
- исполнителем задачи
- членом группы, которой назначена задача
- admin или manager
""",
    responses={
        200: {"description": "Данные задачи"},
        403: {"description": "Нет доступа к задаче"},
        404: {"description": "Задача не найдена"},
    },
)
async def get_task(
    task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_task_service(session).get_task(task_id, current_user)


@router.patch(
    "/{task_id}/reassign",
    response_model=SpisokSchema,
    summary="Переназначить задачу",
    description="""
Меняет исполнителя или группу задачи.

Должен быть передан ровно один из параметров: `user_id` или `group_id`.
При смене на пользователя — `group_id` обнуляется, и наоборот.

**Требует роль admin/manager или быть автором задачи.**

Side-effects:
- Отправляет Telegram-уведомление новому исполнителю/группе (в фоне).
- Инвалидирует кэш задач.
- Пишет запись в audit-лог.
""",
    responses={
        200: {"description": "Задача переназначена"},
        400: {
            "description": "Нужно передать ровно один из параметров: user_id или group_id"
        },
        403: {"description": "Нет прав на переназначение"},
        404: {"description": "Задача, пользователь или группа не найдены"},
    },
)
async def reassign_task(
    task_id: int,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    current_user: UserModel = Depends(get_current_user),
    user_id: int | None = Query(None),
    group_id: int | None = Query(None),
):
    session.info["audit_user_id"] = current_user.id
    result = await get_task_service(session).reassign_task(
        task_id, current_user, user_id, group_id
    )
    await cache_manager.invalidate_tasks()
    background_tasks.add_task(notify_task_assigned, result.id)
    return result


@router.patch(
    "/{task_id}",
    response_model=SpisokSchema,
    summary="Обновить задачу",
    description="""
Частичное обновление задачи (title, description, is_done, deadline).

Право на изменение дедлайна — только у **автора, admin или manager**.

Side-effects:
- При переводе `is_done = true` отправляет Telegram-уведомление автору.
- Инвалидирует кэш задач.
- Пишет запись в audit-лог.
""",
    responses={
        200: {"description": "Обновлённая задача"},
        403: {"description": "Нет доступа к задаче или нет прав менять дедлайн"},
        404: {"description": "Задача не найдена"},
    },
)
async def update_task(
    task_id: int,
    data: SpisokUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    session.info["audit_user_id"] = current_user.id
    task = await get_task_service(session).update_task(task_id, data, current_user)
    await cache_manager.invalidate_tasks()
    return task


@router.delete(
    "/{task_id}",
    response_model=dict,
    summary="Мягкое удаление задачи",
    description="""
Помечает задачу как удалённую (устанавливает `deleted_at`). Физически из БД не удаляется.

Задача остаётся доступна через `/tasks/trash` и может быть восстановлена.

**Требует быть автором, admin или manager.**

Side-effects:
- Пишет запись в audit-лог.
- Инвалидирует кэш задач.
""",
    responses={
        200: {
            "description": "Задача перемещена в корзину",
            "content": {
                "application/json": {"example": {"message": "Task 42 deleted"}}
            },
        },
        403: {"description": "Нет прав на удаление"},
        404: {"description": "Задача не найдена"},
    },
)
async def delete_task(
    task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    session.info["audit_user_id"] = current_user.id
    result = await get_task_service(session).delete_task(task_id, current_user)
    await cache_manager.invalidate_tasks()
    return result


@router.patch(
    "/{task_id}/restore",
    response_model=SpisokSchema,
    summary="Восстановить задачу из корзины",
    description="""
Восстанавливает задачу: сбрасывает `deleted_at = NULL`.

**Требует быть автором, admin или manager.**

Side-effects:
- Пишет запись в audit-лог.
- Инвалидирует кэш задач.
""",
    responses={
        200: {"description": "Задача восстановлена"},
        403: {"description": "Нет прав на восстановление"},
        404: {"description": "Задача не найдена"},
    },
)
async def restore_task(
    task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    session.info["audit_user_id"] = current_user.id
    task = await get_task_service(session).restore_task(task_id, current_user)
    await cache_manager.invalidate_tasks()
    return task


@router.delete(
    "/{task_id}/hard",
    response_model=dict,
    summary="Полное удаление задачи",
    description="""
Физически удаляет задачу из БД. **Восстановление невозможно.**

Перед удалением записывает audit-лог с пометкой `hard_delete: true`.

**Требует быть автором, admin или manager.**

Side-effects:
- Каскадно удаляет все комментарии к задаче.
- Пишет запись в audit-лог.
- Инвалидирует кэш задач.
""",
    responses={
        200: {
            "description": "Задача удалена навсегда",
            "content": {
                "application/json": {
                    "example": {"message": "Task 42 permanently deleted"}
                }
            },
        },
        403: {"description": "Нет прав на удаление"},
        404: {"description": "Задача не найдена"},
    },
)
async def hard_delete_task(
    task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    session.info["audit_user_id"] = current_user.id
    await get_task_service(session).hard_delete_task(task_id, current_user)
    await cache_manager.invalidate_tasks()
    return {"message": f"Task {task_id} permanently deleted"}
