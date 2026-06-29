from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi_cache.decorator import cache

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.task import TaskStatus
from src.models.user import UserModel
from src.repositories.audit_repository import AuditRepository
from src.repositories.groups_repository import GroupRepository
from src.repositories.task_repository import TaskRepository
from src.repositories.users_repository import UserRepository
from src.schemas.pagination import PaginatedResponse, PaginationParams
from src.schemas.schemas_audit import AuditLogSchema
from src.schemas.task import (
    FilterUserGroup,
    KanbanResponse,
    SpisokAddSchema,
    SpisokSchema,
    SpisokUpdate,
    TaskFilter,
    TaskPriorityFilter,
    TaskStatusUpdate,
)
from src.services.notifications import notify_task_assigned
from src.services.task_service import TaskService
from src.services.ws_events import (
    emit_kanban_moved,
    emit_task_created,
    emit_task_deleted,
    emit_task_restored,
    emit_task_updated,
)
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


@router.post("", response_model=SpisokSchema, status_code=201)
async def add_task(
    data: SpisokAddSchema,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    session.info["audit_user_id"] = current_user.id
    task = await get_task_service(session).add_task(data, current_user)
    await cache_manager.invalidate_tasks()
    await emit_task_created(task)
    return task


@router.get("/filter", response_model=PaginatedResponse[SpisokSchema])
@cache(expire=120, namespace="tasks", key_builder=user_scoped_key_builder)
async def filter_tasks(
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
    filter_user_group: FilterUserGroup | None = Query(None),
    group_id: int | None = Query(None),
    project_id: int | None = Query(None),  # ← добавить
    filter_type: TaskFilter | None = Query(None),
    priority: TaskPriorityFilter | None = Query(None),
    status: TaskStatus | None = Query(None, description="Фильтр по статусу канбана"),
    limit: int | None = Query(None, ge=1, le=100),
):
    final_limit = limit or pagination.size
    tasks, total = await get_task_service(session).filter_tasks_paginated(
        user=current_user,
        offset=pagination.offset,
        limit=final_limit,
        filter_user_group=filter_user_group,
        group_id=group_id,
        project_id=project_id,
        filter_type=filter_type,
        priority=priority,
        status=status,
    )

    return PaginatedResponse.create(
        items=[SpisokSchema.model_validate(task) for task in tasks],
        total=total,
        page=pagination.page,
        size=pagination.size,
    )


# ── Корзина ───────────────────────────────────────────────────────────────────
# ВАЖНО: /trash должен быть ДО /{task_id}, иначе FastAPI примет "trash" как task_id


@router.get("/trash", response_model=PaginatedResponse[SpisokSchema])
async def list_deleted_tasks(
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
    search: str | None = Query(None),
):
    """Показать все мягко удалённые задачи, доступные пользователю."""
    tasks, total = await get_task_service(session).get_deleted_tasks(
        user=current_user,
        offset=pagination.offset,
        limit=pagination.size,
        search=search,
    )
    return PaginatedResponse.create(items=tasks, total=total, page=pagination.page, size=pagination.size)


# ── Канбан GET — должен быть до /{task_id} ────────────────────────────────────


@router.get(
    "/kanban",
    response_model=KanbanResponse,
    summary="Канбан-доска",
    description=(
        "Возвращает все доступные задачи, сгруппированные по статусам. "
        "Один запрос вместо пяти. "
        "Параметр project_id фильтрует задачи по проекту. "
        "Параметр only_mine=true показывает только задачи где текущий пользователь — исполнитель."
    ),
)
async def get_kanban(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
    project_id: int | None = Query(None, description="Фильтр по проекту"),
    only_mine: bool = Query(False, description="Только мои задачи (исполнитель)"),
    only_author: bool = Query(False, description="Только задачи, где текущий пользователь — автор"),
):
    return await get_task_service(session).get_kanban(
        current_user,
        project_id=project_id,
        only_mine=only_mine,
        only_author=only_author,
    )


# ── Обычные CRUD ──────────────────────────────────────────────────────────────


@router.get("/{task_id}", response_model=SpisokSchema)
async def get_task(
    task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_task_service(session).get_task(task_id, current_user)


@router.patch("/{task_id}/reassign", response_model=SpisokSchema)
async def reassign_task(
    task_id: int,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    current_user: UserModel = Depends(get_current_user),
    user_id: int | None = Query(None),
    group_id: int | None = Query(None),
):
    session.info["audit_user_id"] = current_user.id
    result = await get_task_service(session).reassign_task(task_id, current_user, user_id, group_id)
    await cache_manager.invalidate_tasks()
    background_tasks.add_task(notify_task_assigned, result.id)
    return result


@router.patch("/{task_id}", response_model=SpisokSchema)
async def update_task(
    task_id: int,
    data: SpisokUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    session.info["audit_user_id"] = current_user.id
    task = await get_task_service(session).update_task(task_id, data, current_user)
    await cache_manager.invalidate_tasks()
    await emit_task_updated(task)
    return task


@router.delete("/{task_id}", response_model=dict)
async def delete_task(
    task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    """Мягкое удаление. Задача помечается deleted_at, физически не удаляется."""
    session.info["audit_user_id"] = current_user.id
    task = await get_task_service(session).get_task(task_id, current_user)
    result = await get_task_service(session).delete_task(task_id, current_user)
    await cache_manager.invalidate_tasks()
    await emit_task_deleted(task)
    return result


@router.patch("/{task_id}/restore", response_model=SpisokSchema)
async def restore_task(
    task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    """Восстановить задачу из корзины."""
    session.info["audit_user_id"] = current_user.id
    task = await get_task_service(session).restore_task(task_id, current_user)
    await cache_manager.invalidate_tasks()
    await emit_task_restored(task)
    return task


@router.delete("/{task_id}/hard", response_model=dict)
async def hard_delete_task(
    task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    """Полностью удалить задачу из БД без возможности восстановления."""
    session.info["audit_user_id"] = current_user.id
    await get_task_service(session).hard_delete_task(task_id, current_user)
    await cache_manager.invalidate_tasks()
    return {"message": f"Task {task_id} permanently deleted"}


@router.get(
    "/{task_id}/audit",
    response_model=list[AuditLogSchema],
    summary="История изменений задачи",
    description="Возвращает последние 50 записей audit_log для задачи. Доступно всем авторизованным пользователям.",
)
async def get_task_audit(
    task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    entries = await AuditRepository(session).get_task_audit_entries(task_id)
    return [AuditLogSchema.from_model(e) for e in entries]


@router.patch(
    "/{task_id}/status",
    response_model=SpisokSchema,
    summary="Сменить статус задачи",
    description="Атомарная операция перемещения карточки между колонками канбана.",
)
async def update_task_status(
    task_id: int,
    data: TaskStatusUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    task = await get_task_service(session).update_task_status(task_id, data.status, current_user)
    await cache_manager.invalidate_tasks()
    await emit_kanban_moved(task)
    return task
