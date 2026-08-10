# src/routers/chat_router.py
from fastapi import APIRouter, Depends, Query

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.chat_repository import ChatRepository
from src.schemas.chat import ChatChannel, ChatMessageCreate, ChatMessageResponse
from src.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["Chat"])


def get_chat_service(session: SessionDep) -> ChatService:
    return ChatService(ChatRepository(session))


@router.get(
    "/channels",
    response_model=list[ChatChannel],
    summary="Список доступных пользователю каналов: общий + группы, в которых он состоит",
)
async def get_channels(
    service: ChatService = Depends(get_chat_service),
    current_user: UserModel = Depends(get_current_user),
):
    return await service.get_channels(current_user)


@router.get(
    "/messages",
    response_model=list[ChatMessageResponse],
    summary="Последние сообщения канала чата",
    description=(
        "group_id не задан — общий канал (виден всем). group_id=<id> — канал "
        "группы (только для её участников или admin). "
        "before_id — курсор для подгрузки более старой истории при скролле вверх."
    ),
)
async def get_messages(
    service: ChatService = Depends(get_chat_service),
    current_user: UserModel = Depends(get_current_user),
    group_id: int | None = Query(None),
    before_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
):
    messages = await service.get_recent(current_user, group_id=group_id, before_id=before_id, limit=limit)
    return [
        ChatMessageResponse(
            id=m.id,
            user_id=m.user_id,
            username=m.user.username if m.user else "?",
            group_id=m.group_id,
            content=m.content,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post(
    "/messages",
    response_model=ChatMessageResponse,
    summary="Отправить сообщение в канал (общий или группы)",
)
async def send_message(
    data: ChatMessageCreate,
    service: ChatService = Depends(get_chat_service),
    current_user: UserModel = Depends(get_current_user),
):
    message = await service.send_message(current_user, data.content, group_id=data.group_id)
    return ChatMessageResponse(
        id=message.id,
        user_id=message.user_id,
        username=current_user.username,
        group_id=message.group_id,
        content=message.content,
        created_at=message.created_at,
    )


@router.delete(
    "/messages/{message_id}",
    status_code=204,
    summary="Удалить сообщение (своё, либо любое — если admin)",
)
async def delete_message(
    message_id: int,
    service: ChatService = Depends(get_chat_service),
    current_user: UserModel = Depends(get_current_user),
):
    await service.delete_message(message_id, current_user)
