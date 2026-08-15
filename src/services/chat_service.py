# src/services/chat_service.py
import structlog

from src.bot.setup import get_bot
from src.core.config import CHAT_BRIDGE_GROUP_ID
from src.core.exceptions import no_access, not_found
from src.core.ws_manager import ws_manager
from src.models.chat_message import ChatMessageModel
from src.models.user import UserModel
from src.repositories.chat_repository import ChatRepository
from src.services.dm_bridge_memory import remember_reply_target

logger = structlog.get_logger()


def _to_payload(message: ChatMessageModel) -> dict:
    return {
        "id": message.id,
        "user_id": message.user_id,
        "username": message.user.username if message.user else None,
        "group_id": message.group_id,
        "recipient_id": message.recipient_id,
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


async def _mirror_to_telegram(username: str, content: str) -> None:
    """Дублирует сообщение общего канала в привязанную Telegram-группу (мост,
    см. src/bot/handlers/chat_bridge.py). Настраивается через CHAT_BRIDGE_GROUP_ID —
    если не задан, мост просто выключен, ничего никуда не шлём."""
    if not CHAT_BRIDGE_GROUP_ID:
        return
    try:
        bot = get_bot()
        await bot.send_message(chat_id=CHAT_BRIDGE_GROUP_ID, text=f"{username}: {content}")
    except Exception as e:  # noqa: BLE001 — сбой моста не должен ронять отправку сообщения в веб-чате
        await logger.aerror("chat_bridge_mirror_failed", error=str(e)[:500])


async def _mirror_dm_to_telegram(sender: UserModel, recipient: UserModel, content: str) -> None:
    """Личное сообщение — зеркалим получателю в Telegram (если у него привязан
    аккаунт), и запоминаем ID отправленного сообщения: если получатель
    ответит на него в Telegram (reply), ответ найдёт дорогу обратно
    отправителю (см. src/bot/handlers/dm_bridge.py). Работает независимо от
    того, откуда пришло исходное сообщение — из веба или из Telegram: каждое
    зеркало — это НОВОЕ сообщение в Telegram, поэтому петли здесь не возникает
    (в отличие от общего канала, где эхо в ту же самую группу зациклилось бы)."""
    if not recipient.telegram_id:
        return
    try:
        bot = get_bot()
        sent = await bot.send_message(
            chat_id=recipient.telegram_id,
            text=f"💬 Личное сообщение от {sender.username}:\n{content}",
        )
        await remember_reply_target(recipient.telegram_id, sent.message_id, sender.id)
    except Exception as e:  # noqa: BLE001 — сбой доставки в Telegram не должен ронять отправку в вебе
        await logger.aerror("dm_bridge_mirror_failed", error=str(e)[:500])


class ChatService:
    def __init__(self, chat_repo: ChatRepository):
        self.chat_repo = chat_repo

    async def get_channels(self, current_user: UserModel) -> list[dict]:
        channels = [{"group_id": None, "name": "Общий чат"}]
        channels += [{"group_id": g.id, "name": g.name} for g in current_user.groups]
        return channels

    async def send_message(
        self,
        current_user: UserModel,
        content: str,
        group_id: int | None = None,
        origin: str = "web",
    ) -> ChatMessageModel:
        """origin — откуда пришло сообщение: "web" (обычная отправка из
        приложения) или "telegram" (см. chat_bridge.py). Нужно, чтобы не
        зациклить пересылку: сообщение, пришедшее ИЗ Telegram, не нужно
        отправлять обратно в Telegram."""
        _check_channel_access(current_user, group_id)
        message = await self.chat_repo.create(current_user.id, content.strip(), group_id=group_id)
        payload = _to_payload(message)
        if group_id is None:
            # Общий канал — рассылаем всем подключённым (переиспользуем тот же
            # механизм, что и у task_created/comment_added, см. ws_events.py).
            await ws_manager.broadcast_all("chat_message", payload)
            if origin == "web":
                await _mirror_to_telegram(current_user.username, message.content)
        else:
            member_ids = await self.chat_repo.get_group_member_ids(group_id)
            await ws_manager.broadcast_to_users(member_ids, "chat_message", payload)
        return message

    async def send_dm(self, sender: UserModel, recipient: UserModel, content: str) -> ChatMessageModel:
        """Личное сообщение. origin намеренно нет — в отличие от общего
        канала, здесь эхо в Telegram не создаёт петлю (см. docstring
        _mirror_dm_to_telegram): каждое зеркало — это НОВОЕ сообщение в
        Telegram, на которое можно ответить дальше, а не повтор одного и
        того же widely-broadcast события."""
        if sender.id == recipient.id:
            no_access("Нельзя написать самому себе")
        if not recipient.is_active:
            not_found("Пользователь не найден")

        message = await self.chat_repo.create(sender.id, content.strip(), recipient_id=recipient.id)
        payload = _to_payload(message)
        await ws_manager.broadcast_to_users([sender.id, recipient.id], "chat_message", payload)
        await _mirror_dm_to_telegram(sender, recipient, message.content)
        return message

    async def get_recent(
        self, current_user: UserModel, group_id: int | None = None, before_id: int | None = None, limit: int = 50
    ) -> list[ChatMessageModel]:
        _check_channel_access(current_user, group_id)
        return await self.chat_repo.get_recent(group_id=group_id, before_id=before_id, limit=limit)

    async def get_dm_history(
        self, current_user: UserModel, other_user_id: int, before_id: int | None = None, limit: int = 50
    ) -> list[ChatMessageModel]:
        # Личные сообщения — приватны для двух участников, без исключения
        # для admin (в отличие от общего/группового чата): это осознанное
        # решение, ЛС не предполагают, что их может прочитать кто-то третий.
        return await self.chat_repo.get_dm_history(current_user.id, other_user_id, before_id=before_id, limit=limit)

    async def get_conversations(self, current_user: UserModel) -> list[dict]:
        """Список диалогов текущего пользователя — по одному (последнему)
        сообщению на собеседника, отсортировано по свежести."""
        messages = await self.chat_repo.get_dm_conversations(current_user.id)
        seen: dict[int, dict] = {}
        for m in messages:
            other = m.recipient if m.user_id == current_user.id else m.user
            if other is None or other.id in seen:
                continue
            seen[other.id] = {
                "user_id": other.id,
                "username": other.username,
                "last_message": m.content,
                "last_message_at": m.created_at,
            }
        return list(seen.values())

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
