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


@router.post("/", response_model=SpisokSchema, status_code=201)
async def add_task(
    data: SpisokAddSchema,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    session.info["audit_user_id"] = current_user.id
    task = await get_task_service(session).add_task(data, current_user)
    await cache_manager.invalidate_tasks()
    background_tasks.add_task(notify_task_assigned, task.id)
    return task


@router.get("/filter", response_model=PaginatedResponse[SpisokSchema])
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
    return PaginatedResponse.create(
        items=tasks, total=total, page=pagination.page, size=pagination.size
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
    current_user: UserModel = Depends(get_current_user),
    user_id: int | None = Query(None),
    group_id: int | None = Query(None),
):
    session.info["audit_user_id"] = current_user.id
    result = await get_task_service(session).reassign_task(
        task_id, current_user, user_id, group_id
    )
    await cache_manager.invalidate_tasks()
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
    return task


@router.delete("/{task_id}", response_model=dict)
async def delete_task(
    task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    """Мягкое удаление. Задача помечается deleted_at, физически не удаляется."""
    session.info["audit_user_id"] = current_user.id
    result = await get_task_service(session).delete_task(task_id, current_user)
    await cache_manager.invalidate_tasks()
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
