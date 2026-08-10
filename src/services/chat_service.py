# src/services/chat_service.py
from src.core.exceptions import no_access, not_found
from src.core.ws_manager import ws_manager
from src.models.chat_message import ChatMessageModel
from src.models.user import UserModel
from src.repositories.chat_repository import ChatRepository


def _to_payload(message: ChatMessageModel) -> dict:
    return {
        "id": message.id,
        "user_id": message.user_id,
        "username": message.user.username if message.user else None,
        "group_id": message.group_id,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
    }


def _check_channel_access(current_user: UserModel, group_id: int | None) -> None:
    """Общий канал (group_id=None) открыт всем. Канал группы — только её
    участникам (или admin — тому доступно всё, как и везде в приложении)."""
    if group_id is None:
        return
    if current_user.role == "admin":
        return
    if not any(g.id == group_id for g in current_user.groups):
        no_access("Вы не состоите в этой группе")


class ChatService:
    def __init__(self, chat_repo: ChatRepository):
        self.chat_repo = chat_repo

    async def get_channels(self, current_user: UserModel) -> list[dict]:
        channels = [{"group_id": None, "name": "Общий чат"}]
        channels += [{"group_id": g.id, "name": g.name} for g in current_user.groups]
        return channels

    async def send_message(
        self, current_user: UserModel, content: str, group_id: int | None = None
    ) -> ChatMessageModel:
        _check_channel_access(current_user, group_id)
        message = await self.chat_repo.create(current_user.id, content.strip(), group_id=group_id)
        payload = _to_payload(message)
        if group_id is None:
            # Общий канал — рассылаем всем подключённым (переиспользуем тот же
            # механизм, что и у task_created/comment_added, см. ws_events.py).
            await ws_manager.broadcast_all("chat_message", payload)
        else:
            member_ids = await self.chat_repo.get_group_member_ids(group_id)
            await ws_manager.broadcast_to_users(member_ids, "chat_message", payload)
        return message

    async def get_recent(
        self, current_user: UserModel, group_id: int | None = None, before_id: int | None = None, limit: int = 50
    ) -> list[ChatMessageModel]:
        _check_channel_access(current_user, group_id)
        return await self.chat_repo.get_recent(group_id=group_id, before_id=before_id, limit=limit)

    async def delete_message(self, message_id: int, current_user: UserModel) -> None:
        message = await self.chat_repo.get_by_id(message_id)
        if not message:
            not_found("Сообщение не найдено")

        if message.user_id != current_user.id and current_user.role != "admin":
            no_access("Можно удалить только своё сообщение")

        group_id = message.group_id
        await self.chat_repo.soft_delete(message)

        payload = {"id": message_id, "group_id": group_id}
        if group_id is None:
            await ws_manager.broadcast_all("chat_message_deleted", payload)
        else:
            member_ids = await self.chat_repo.get_group_member_ids(group_id)
            if not member_ids:
                return
            await ws_manager.broadcast_to_users(member_ids, "chat_message_deleted", payload)
