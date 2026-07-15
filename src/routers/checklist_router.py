# src/routers/checklist_router.py
from fastapi import APIRouter, Depends

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.checklist_repository import ChecklistRepository
from src.repositories.groups_repository import GroupRepository
from src.repositories.task_repository import TaskRepository
from src.schemas.checklist import (
    ChecklistItemCreate,
    ChecklistItemSchema,
    ChecklistItemUpdate,
    ChecklistReorderRequest,
)
from src.services.checklist_service import ChecklistService

router = APIRouter(prefix="/tasks/{task_id}/checklist", tags=["Checklist"])


def get_checklist_service(session: SessionDep) -> ChecklistService:
    return ChecklistService(
        checklist_repo=ChecklistRepository(session),
        task_repo=TaskRepository(session),
        group_repo=GroupRepository(session),
    )


@router.get("", response_model=list[ChecklistItemSchema])
async def list_checklist_items(
    task_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_checklist_service(session).list_items(task_id, current_user)


@router.post("", response_model=ChecklistItemSchema, status_code=201)
async def add_checklist_item(
    task_id: int,
    data: ChecklistItemCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_checklist_service(session).add_item(task_id, data, current_user)


@router.patch("/reorder", response_model=list[ChecklistItemSchema])
async def reorder_checklist_items(
    task_id: int,
    data: ChecklistReorderRequest,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    """Массовое переупорядочивание — используется drag-and-drop на фронте."""
    ordering = {item.id: item.order_index for item in data.items}
    return await get_checklist_service(session).reorder(task_id, ordering, current_user)


@router.patch("/{item_id}", response_model=ChecklistItemSchema)
async def update_checklist_item(
    task_id: int,
    item_id: int,
    data: ChecklistItemUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_checklist_service(session).update_item(task_id, item_id, data, current_user)


@router.delete("/{item_id}", response_model=dict)
async def delete_checklist_item(
    task_id: int,
    item_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_checklist_service(session).delete_item(task_id, item_id, current_user)
