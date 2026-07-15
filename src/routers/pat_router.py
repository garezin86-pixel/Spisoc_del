# src/routers/pat_router.py
from fastapi import APIRouter, Depends

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.pat_repository import PatRepository
from src.schemas.personal_access_token import (
    PersonalAccessTokenCreate,
    PersonalAccessTokenCreatedResponse,
    PersonalAccessTokenSchema,
)
from src.services.pat_service import PatService

router = APIRouter(prefix="/tokens", tags=["Personal Access Tokens"])


def get_pat_service(session: SessionDep) -> PatService:
    return PatService(PatRepository(session))


@router.get("", response_model=list[PersonalAccessTokenSchema])
async def list_tokens(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_pat_service(session).list_tokens(current_user)


@router.post(
    "",
    response_model=PersonalAccessTokenCreatedResponse,
    status_code=201,
    summary="Создать персональный API-токен",
    description=(
        "Полный токен возвращается ТОЛЬКО в этом ответе — сохраните его сразу, "
        "повторно получить не получится (хранится только хэш). "
        "Используйте как Bearer-токен: Authorization: Bearer pat_..."
    ),
)
async def create_token(
    data: PersonalAccessTokenCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_pat_service(session).create_token(current_user, data)


@router.delete("/{token_id}", response_model=dict)
async def revoke_token(
    token_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_pat_service(session).revoke_token(current_user, token_id)
