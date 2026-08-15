# src/routers/chat_router.py
from fastapi import APIRouter, Depends, Query

from src.core.dependencies import get_current_user
from src.core.exceptions import not_found
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.chat_repository import ChatRepository
from src.repositories.users_repository import UserRepository
from src.schemas.chat import ChatChannel, ChatMessageCreate, ChatMessageResponse, DirectMessageCreate, DMConversation
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
            recipient_id=m.recipient_id,
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
        recipient_id=message.recipient_id,
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


# ── Личные сообщения ─────────────────────────────────────────────────────


@router.get(
    "/dm/conversations",
    response_model=list[DMConversation],
    summary="Список личных переписок текущего пользователя (по свежести)",
)
async def get_dm_conversations(
    service: ChatService = Depends(get_chat_service),
    current_user: UserModel = Depends(get_current_user),
):
    conversations = await service.get_conversations(current_user)
    return sorted(conversations, key=lambda c: c["last_message_at"], reverse=True)


@router.get(
    "/dm/{other_user_id}",
    response_model=list[ChatMessageResponse],
    summary="История переписки с конкретным пользователем",
    description="Приватно для двух участников — even admin не имеет доступа к чужим ЛС.",
)
async def get_dm_history(
    other_user_id: int,
    session: SessionDep,
    service: ChatService = Depends(get_chat_service),
    current_user: UserModel = Depends(get_current_user),
    before_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
):
    other = await UserRepository(session).get_user_id(other_user_id)
    if not other:
        not_found("Пользователь не найден")

    messages = await service.get_dm_history(current_user, other_user_id, before_id=before_id, limit=limit)
    return [
        ChatMessageResponse(
            id=m.id,
            user_id=m.user_id,
            username=m.user.username if m.user else "?",
            group_id=m.group_id,
            recipient_id=m.recipient_id,
            content=m.content,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post(
    "/dm/{other_user_id}",
    response_model=ChatMessageResponse,
    summary="Отправить личное сообщение",
)
async def send_dm(
    other_user_id: int,
    data: DirectMessageCreate,
    session: SessionDep,
    service: ChatService = Depends(get_chat_service),
    current_user: UserModel = Depends(get_current_user),
):
    recipient = await UserRepository(session).get_user_id(other_user_id)
    if not recipient:
        not_found("Пользователь не найден")

    message = await service.send_dm(current_user, recipient, data.content)
    return ChatMessageResponse(
        id=message.id,
        user_id=message.user_id,
        username=current_user.username,
        group_id=message.group_id,
        recipient_id=message.recipient_id,
        content=message.content,
        created_at=message.created_at,
    )
