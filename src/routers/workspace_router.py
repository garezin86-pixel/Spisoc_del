# src/routers/workspace_router.py
"""Приглашения в компанию. Доступны только role="admin" своей компании."""

from fastapi import APIRouter, Depends

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.models.workspace_invite import WorkspaceInviteModel
from src.repositories.users_repository import UserRepository
from src.repositories.workspace_repository import WorkspaceRepository
from src.schemas.workspace import InviteSchema
from src.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/workspace", tags=["Workspace"])


def _service(session) -> WorkspaceService:
    return WorkspaceService(WorkspaceRepository(session), UserRepository(session))


def _to_schema(invite: WorkspaceInviteModel) -> InviteSchema:
    from src.bot.setup import get_bot_username

    schema = InviteSchema.model_validate(invite)
    schema.bot_start_param = f"ws_{invite.token}"
    bot = get_bot_username()
    schema.bot_link = f"https://t.me/{bot}?start=ws_{invite.token}" if bot else None
    return schema


@router.post(
    "/invites",
    response_model=InviteSchema,
    status_code=201,
    summary="Создать приглашение в компанию",
    description=(
        "Токен действует 7 дней, без лимита использований, до отзыва. "
        "Присоединившийся получает роль user. Требует роль admin."
    ),
    responses={403: {"description": "Только администратор компании"}},
)
async def create_invite(session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    return _to_schema(await _service(session).create_invite(current_user))


@router.get(
    "/invites",
    response_model=list[InviteSchema],
    summary="Приглашения компании",
    description="По умолчанию только действующие (не отозванные и не истёкшие). Требует роль admin.",
)
async def list_invites(
    session: SessionDep,
    include_inactive: bool = False,
    current_user: UserModel = Depends(get_current_user),
):
    invites = await _service(session).list_invites(current_user, only_active=not include_inactive)
    return [_to_schema(i) for i in invites]


@router.delete(
    "/invites/{invite_id}",
    response_model=InviteSchema,
    summary="Отозвать приглашение",
    responses={404: {"description": "Приглашение не найдено (в том числе чужой компании)"}},
)
async def revoke_invite(invite_id: int, session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    return _to_schema(await _service(session).revoke_invite(current_user, invite_id))
