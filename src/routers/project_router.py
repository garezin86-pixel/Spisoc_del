# src/routers/project_router.py
from fastapi import APIRouter, Depends
from src.db import SessionDep
from src.models.user import UserModel
from src.schemas.schemas_project import ProjectCreate, ProjectSchema, ProjectUpdate
from src.schemas.pagination import PaginationParams, PaginatedResponse
from src.core.dependencies import get_current_user
from src.services.project_service import ProjectService
from src.repositories.project_repository import ProjectRepository
from src.repositories.users_repository import UserRepository
from src.repositories.groups_repository import GroupRepository

router = APIRouter(prefix="/projects", tags=["Projects"])


def get_project_service(session: SessionDep) -> ProjectService:
    return ProjectService(
        ProjectRepository(session), UserRepository(session), GroupRepository(session)
    )


@router.post(
    "",
    response_model=ProjectSchema,
    status_code=201,
    summary="Создать проект",
    description="Создаёт проект. Владельцем становится текущий пользователь. **Требует роль admin или manager.**",
    responses={
        201: {"description": "Проект создан"},
        403: {"description": "Требуется роль admin или manager"},
    },
)
async def create_project(
    data: ProjectCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    project = await get_project_service(session).create_project(data, current_user)
    return ProjectSchema.from_model(project)


@router.get(
    "",
    response_model=PaginatedResponse[ProjectSchema],
    summary="Список проектов",
    description="""
Возвращает проекты доступные текущему пользователю.

Пользователь видит проект если он:
- владелец проекта
- добавлен как участник
- является исполнителем хотя бы одной задачи проекта

Admin и manager видят все проекты.
""",
)
async def get_projects(
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
):
    projects, total = await get_project_service(session).get_projects(
        current_user, offset=pagination.offset, limit=pagination.size
    )
    items = [ProjectSchema.from_model(p) for p in projects]
    return PaginatedResponse.create(
        items=items, total=total, page=pagination.page, size=pagination.size
    )


@router.get(
    "/{project_id}",
    response_model=ProjectSchema,
    summary="Получить проект",
    responses={
        200: {"description": "Данные проекта со статистикой и участниками"},
        403: {"description": "Нет доступа к проекту"},
        404: {"description": "Проект не найден"},
    },
)
async def get_project(
    project_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    project = await get_project_service(session).get_project(project_id, current_user)
    return ProjectSchema.from_model(project)


@router.patch(
    "/{project_id}",
    response_model=ProjectSchema,
    summary="Обновить проект",
    description="Обновляет название и/или описание. **Требует быть владельцем или admin.**",
    responses={
        200: {"description": "Обновлённый проект"},
        403: {"description": "Нет прав"},
        404: {"description": "Проект не найден"},
    },
)
async def update_project(
    project_id: int,
    data: ProjectUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    project = await get_project_service(session).update_project(
        project_id, data, current_user
    )
    return ProjectSchema.from_model(project)


@router.delete(
    "/{project_id}",
    response_model=dict,
    summary="Удалить проект",
    description="""
Удаляет проект и **все связанные задачи** (cascade).

**Требует быть владельцем или admin.**
""",
    responses={
        200: {
            "description": "Проект удалён",
            "content": {
                "application/json": {"example": {"message": "Project 1 deleted"}}
            },
        },
        403: {"description": "Нет прав"},
        404: {"description": "Проект не найден"},
    },
)
async def delete_project(
    project_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_project_service(session).delete_project(project_id, current_user)


@router.post(
    "/{project_id}/members/{user_id}",
    response_model=dict,
    summary="Добавить участника",
    description="Добавляет пользователя в участники проекта. **Требует роль admin/manager или быть владельцем.**",
    responses={
        200: {"description": "Участник добавлен"},
        403: {"description": "Нет прав"},
        404: {"description": "Проект или пользователь не найден"},
    },
)
async def add_member(
    project_id: int,
    user_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_project_service(session).add_member(
        project_id, user_id, current_user
    )


@router.delete(
    "/{project_id}/members/{user_id}",
    response_model=dict,
    summary="Удалить участника",
    description="Исключает участника из проекта. **Требует быть владельцем или admin.**",
)
async def remove_member(
    project_id: int,
    user_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_project_service(session).remove_member(
        project_id, user_id, current_user
    )


@router.patch(
    "/{project_id}/group",
    response_model=ProjectSchema,
    summary="Привязать группу к проекту",
    description="Назначает или снимает группу с проекта. Передай `group_id: null` чтобы отвязать. **Требует быть владельцем или admin.**",
    responses={
        200: {"description": "Проект обновлён"},
        403: {"description": "Нет прав"},
        404: {"description": "Проект или группа не найдена"},
    },
)
async def set_project_group(
    project_id: int,
    data: ProjectUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    project = await get_project_service(session).set_project_group(
        project_id, data.group_id, current_user
    )
    return ProjectSchema.from_model(project)
