# src/routers/tags_router.py
from fastapi import APIRouter, Depends

from src.core.dependencies import get_current_user
from src.core.exceptions import no_access
from src.db import SessionDep
from src.models.user import UserModel, UserRole
from src.repositories.groups_repository import GroupRepository
from src.repositories.tag_repository import TagRepository
from src.repositories.task_repository import TaskRepository
from src.schemas.tag import TagCreate, TagSchema, TaskTagsUpdate
from src.schemas.task import SpisokSchema
from src.services.tag_service import TagService

router = APIRouter(prefix="/tags", tags=["Tags"])


def get_tag_service(session: SessionDep) -> TagService:
    return TagService(
        tag_repo=TagRepository(session),
        task_repo=TaskRepository(session),
        group_repo=GroupRepository(session),
    )


@router.get("", response_model=list[TagSchema])
async def list_tags(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_tag_service(session).list_tags()


@router.post("", response_model=TagSchema, status_code=201)
async def create_tag(
    data: TagCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    """Создать тег может любой авторизованный пользователь — теги общий словарь команды."""
    return await get_tag_service(session).create_tag(data)


@router.delete("/{tag_id}", response_model=dict)
async def delete_tag(
    tag_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    """Удалять тег может только admin/manager — иначе кто угодно мог бы стереть общий тег у всех задач."""
    if current_user.role not in (UserRole.admin, UserRole.manager):
        no_access("Удалять теги может только admin или manager")
    return await get_tag_service(session).delete_tag(tag_id)


@router.put("/tasks/{task_id}", response_model=SpisokSchema)
async def set_task_tags(
    task_id: int,
    data: TaskTagsUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    """Полностью заменяет набор тегов на задаче (не добавление по одному)."""
    return await get_tag_service(session).set_task_tags(task_id, data.tag_ids, current_user)
