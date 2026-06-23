from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query

from src.db import SessionDep
from src.models.user import UserModel
from src.core.dependencies import get_current_user
from src.repositories.template_repository import TemplateRepository
from src.schemas.template import (
    TemplateCreate,
    TemplateUpdate,
    TemplateResponse,
    ApplyTemplateRequest,
)
from src.schemas.task import SpisokSchema
from src.utils.cache_manager import cache_manager

router = APIRouter(prefix="/templates", tags=["Templates"])


def get_repo(session: SessionDep) -> TemplateRepository:
    return TemplateRepository(session)


@router.get("", response_model=list[TemplateResponse])
async def list_templates(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
    visibility: Literal["private", "group", "global"] | None = Query(
        None, description="Фильтр по видимости"
    ),
):
    """Список шаблонов доступных пользователю с опциональным фильтром по видимости."""
    return await get_repo(session).get_all(
        current_user.id, visibility_filter=visibility
    )


@router.post("", response_model=TemplateResponse, status_code=201)
async def create_template(
    data: TemplateCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    template = await get_repo(session).create(current_user.id, data)
    await session.commit()
    return template


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    template = await get_repo(session).get_by_id(template_id, current_user.id)
    if not template:
        raise HTTPException(404, "Шаблон не найден или недоступен")
    return template


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: int,
    data: TemplateUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    """Редактировать может только владелец."""
    repo = get_repo(session)
    template = await repo.get_by_id_owner_only(template_id, current_user.id)
    if not template:
        raise HTTPException(404, "Шаблон не найден или нет прав")
    template = await repo.update(template, data)
    await session.commit()
    return template


@router.delete("/{template_id}", response_model=dict)
async def delete_template(
    template_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    """Удалить может только владелец."""
    repo = get_repo(session)
    template = await repo.get_by_id_owner_only(template_id, current_user.id)
    if not template:
        raise HTTPException(404, "Шаблон не найден или нет прав")
    await repo.delete(template)
    await session.commit()
    return {"message": f"Template {template_id} deleted"}


@router.post(
    "/{template_id}/apply",
    response_model=list[SpisokSchema],
    summary="Применить шаблон",
)
async def apply_template(
    template_id: int,
    data: ApplyTemplateRequest,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    """Применить может любой у кого есть доступ (private/group/global)."""
    session.info["audit_user_id"] = current_user.id
    repo = get_repo(session)
    template = await repo.get_by_id(template_id, current_user.id)
    if not template:
        raise HTTPException(404, "Шаблон не найден или недоступен")
    if not template.items:
        raise HTTPException(400, "Шаблон не содержит задач")
    tasks = await repo.apply(template, data.project_id, current_user.id)
    await session.commit()
    await cache_manager.invalidate_tasks()
    for task in tasks:
        await session.refresh(task)
    return [SpisokSchema.model_validate(t) for t in tasks]
