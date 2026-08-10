from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from fastapi_cache.decorator import cache
from sqlalchemy.exc import IntegrityError

from src.core.constants import (
    PRESET_NAME_ALREADY_EXISTS,
    PRESET_NOT_FOUND,
)

# (добавить константы — см. ниже)
from src.core.dependencies import get_current_user
from src.core.exceptions import (
    incorrect_request,
    not_found,
)

# (not_found и/или incorrect_request — если ещё не импортированы в этом файле)
from src.db import SessionDep
from src.models.enums import WebhookEvent
from src.models.filter_preset import FilterPresetModel
from src.models.task import TaskStatus
from src.models.user import UserModel
from src.repositories.audit_repository import AuditRepository
from src.repositories.filter_preset_repository import FilterPresetRepository
from src.repositories.groups_repository import GroupRepository
from src.repositories.tag_repository import TagRepository
from src.repositories.task_repository import TaskRepository
from src.repositories.users_repository import UserRepository
from src.schemas.filter_preset_schema import FilterPresetCreate, FilterPresetSchema
from src.schemas.pagination import PaginatedResponse, PaginationParams
from src.schemas.schemas_audit import AuditLogSchema
from src.schemas.task import (
    BulkTaskUpdate,
    BulkTaskUpdateResult,
    FilterUserGroup,
    KanbanResponse,
    SpisokAddSchema,
    SpisokSchema,
    SpisokUpdate,
    TaskFilter,
    TaskImportSummary,
    TaskPriorityFilter,
    TaskStatusUpdate,
)
from src.schemas.task_dependency import TaskDependenciesSchema, TaskDependencyCreate
from src.services.notifications import notify_task_assigned
from src.services.task_export_service import TaskExportService
from src.services.task_service import TaskService
from src.services.webhook_dispatcher import dispatch_webhook_event
from src.services.ws_events import (
    affected_users,
    emit_kanban_moved,
    emit_task_created,
    emit_task_deleted,
    emit_task_restored,
    emit_task_updated,
    task_payload,
)
from src.utils.cache_keys import user_scoped_key_builder
from src.utils.cache_manager import cache_manager

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def get_task_service(session: SessionDep) -> TaskService:
    return TaskService(
        task_repo=TaskRepository(session),
        user_repo=UserRepository(session),
        group_repo=GroupRepository(session),
        tag_repo=TagRepository(session),  # ← новая строка
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
    dispatch_webhook_event(WebhookEvent.task_created, affected_users(task), task_payload(task))
    return task


@router.get("/filter", response_model=PaginatedResponse[SpisokSchema])
@cache(expire=120, namespace="tasks", key_builder=user_scoped_key_builder)
async def filter_tasks(
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
    filter_user_group: FilterUserGroup | None = Query(None),
    group_id: int | None = Query(None),
    project_id: int | None = Query(None),
    filter_type: TaskFilter | None = Query(None),
    priority: TaskPriorityFilter | None = Query(None),
    status: TaskStatus | None = Query(None, description="Фильтр по статусу канбана"),
    search: str | None = Query(
        None,
        min_length=1,
        max_length=200,
        description="Полнотекстовый поиск по названию и описанию",
    ),
    tag_id: int | None = Query(None, description="Фильтр по тегу"),
    limit: int | None = Query(None, ge=1, le=100),
    target_user_id: int | None = Query(
        None, description="Показать задачи другого пользователя (например, со страницы его профиля), а не свои"
    ),
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
        search=search,
        tag_id=tag_id,
        target_user_id=target_user_id,
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


@router.get(
    "/export",
    summary="Экспорт задач в CSV",
    description=(
        "Выгружает задачи в CSV-файл (для отчётности перед начальством и т.п.). "
        "Обычный пользователь всегда видит в выгрузке только свои задачи "
        "(автор или исполнитель) — это проверяется на сервере, независимо от "
        "переданных фильтров. admin/manager видят всё, что подпадает под фильтры."
    ),
)
async def export_tasks_csv(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
    project_id: int | None = Query(None),
    status: TaskStatus | None = Query(None),
    priority: TaskPriorityFilter | None = Query(None),
    tag_id: int | None = Query(None),
    deadline_from: datetime | None = Query(None, description="Начало периода (по дедлайну)"),
    deadline_to: datetime | None = Query(None, description="Конец периода (по дедлайну)"),
):
    csv_content = await TaskExportService(TaskRepository(session)).export_tasks_csv(
        current_user,
        project_id=project_id,
        status=status,
        priority=priority,
        tag_id=tag_id,
        deadline_from=deadline_from,
        deadline_to=deadline_to,
    )

    filename = f"tasks_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(
        iter([csv_content.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/import",
    response_model=TaskImportSummary,
    summary="Импорт задач из CSV/Excel",
    description=(
        "Пачечное создание задач из файла с колонками Название/Дедлайн/Приоритет "
        "(регистр и порядок колонок не важны, лишние колонки игнорируются — можно "
        "загрузить в том числе файл, ранее экспортированный этой же системой). "
        "Поддерживаются .csv и .xlsx. Опциональный project_id — все созданные "
        "задачи попадут в указанный проект."
    ),
)
async def import_tasks(
    session: SessionDep,
    file: UploadFile = File(...),
    current_user: UserModel = Depends(get_current_user),
    project_id: int | None = Query(None),
):
    content = await file.read()
    session.info["audit_user_id"] = current_user.id
    summary = await get_task_service(session).import_tasks(
        filename=file.filename or "",
        content=content,
        current_user=current_user,
        project_id=project_id,
    )
    await cache_manager.invalidate_tasks()
    return summary


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


def get_filter_preset_repo(session: SessionDep) -> FilterPresetRepository:
    return FilterPresetRepository(session)


@router.get(
    "/presets",
    response_model=list[FilterPresetSchema],
    summary="Список сохранённых пресетов фильтров",
)
async def list_filter_presets(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_filter_preset_repo(session).get_all_for_user(current_user.id)


@router.post(
    "/presets",
    response_model=FilterPresetSchema,
    status_code=201,
    summary="Сохранить текущую комбинацию фильтров как именной пресет",
)
async def create_filter_preset(
    data: FilterPresetCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    preset = FilterPresetModel(
        user_id=current_user.id,
        name=data.name,
        status=data.status,
        priority=data.priority,
        tag_id=data.tag_id,
        project_id=data.project_id,
        filter_user_group=(data.filter_user_group.value if data.filter_user_group else None),
        filter_type=(data.filter_type.value if data.filter_type else None),
    )
    try:
        return await get_filter_preset_repo(session).create(preset)
    except IntegrityError:
        # UniqueConstraint(user_id, name) — у пользователя уже есть пресет
        # с таким именем. Откатываем сессию (иначе она "отравлена" после
        # неудачного commit и следующий запрос в этой же сессии упадёт),
        # затем отдаём внятный 400 вместо голого 500.
        await session.rollback()
        incorrect_request(PRESET_NAME_ALREADY_EXISTS)


@router.delete(
    "/presets/{preset_id}",
    response_model=dict,
    summary="Удалить сохранённый пресет",
)
async def delete_filter_preset(
    preset_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    repo = get_filter_preset_repo(session)
    preset = await repo.get_by_id(preset_id)
    if preset is None or preset.user_id != current_user.id:
        # Пресет либо не существует, либо принадлежит другому пользователю —
        # в обоих случаях отдаём одинаковый 404, чтобы не палить чужие id.
        not_found(PRESET_NOT_FOUND)
    await repo.delete(preset)
    return {"message": f"Preset {preset_id} deleted"}


# ── Обычные CRUD ──────────────────────────────────────────────────────────────


@router.get("/{task_id}", response_model=SpisokSchema)
async def get_task(
    task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_task_service(session).get_task(task_id, current_user)


@router.patch(
    "/bulk",
    response_model=BulkTaskUpdateResult,
    summary="Массовое изменение задач",
    description=(
        "Меняет статус/приоритет/тег/исполнителя у пачки задач одним запросом. "
        "Задачи, к которым нет доступа (или которых не существует), не прерывают "
        "операцию — попадают в skipped."
    ),
)
async def bulk_update_tasks(
    data: BulkTaskUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    session.info["audit_user_id"] = current_user.id
    result = await get_task_service(session).bulk_update_tasks(data, current_user)
    await cache_manager.invalidate_tasks()
    return result


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
    users = affected_users(task)
    payload = task_payload(task)
    dispatch_webhook_event(WebhookEvent.task_updated, users, payload)
    if data.status is not None:
        dispatch_webhook_event(WebhookEvent.task_status_changed, users, payload)
        if task.status == TaskStatus.done:
            dispatch_webhook_event(WebhookEvent.task_done, users, payload)
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
    dispatch_webhook_event(WebhookEvent.task_deleted, affected_users(task), {"id": task.id})
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


@router.get(
    "/{task_id}/dependencies",
    response_model=TaskDependenciesSchema,
    summary="Зависимости задачи (блокеры и заблокированные)",
)
async def get_task_dependencies(
    task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_task_service(session).get_dependencies(task_id, current_user)


@router.post(
    "/{task_id}/dependencies",
    status_code=201,
    summary="Добавить блокирующую задачу",
    description=(
        "Задача task_id не сможет перейти в статус done, пока указанная в теле "
        "blocker_task_id задача не будет закрыта. Отклоняется, если получился бы цикл."
    ),
)
async def add_task_dependency(
    task_id: int,
    data: TaskDependencyCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    await get_task_service(session).add_dependency(task_id, data.blocker_task_id, current_user)
    return {"message": "Зависимость добавлена"}


@router.delete(
    "/{task_id}/dependencies/{blocker_task_id}",
    summary="Убрать блокирующую задачу",
)
async def remove_task_dependency(
    task_id: int,
    blocker_task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    await get_task_service(session).remove_dependency(task_id, blocker_task_id, current_user)
    return {"message": "Зависимость удалена"}


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
    users = affected_users(task)
    payload = task_payload(task)
    dispatch_webhook_event(WebhookEvent.task_status_changed, users, payload)
    if task.status == TaskStatus.done:
        dispatch_webhook_event(WebhookEvent.task_done, users, payload)
    return task
