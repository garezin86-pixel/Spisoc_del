# src/repositories/chat_repository.py
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.chat_message import ChatMessageModel
from src.models.group import user_group


class ChatRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: int, content: str, group_id: int | None = None) -> ChatMessageModel:
        message = ChatMessageModel(user_id=user_id, content=content, group_id=group_id)
        self.session.add(message)
        await self.session.commit()
        await self.session.refresh(message)
        await self.session.refresh(message, attribute_names=["user"])
        return message

    async def get_recent(
        self, group_id: int | None = None, before_id: int | None = None, limit: int = 50
    ) -> list[ChatMessageModel]:
        """Возвращает до `limit` последних сообщений канала (не удалённых), от старых к новым.

        group_id=None — общий канал. group_id=<id> — приватный канал этой группы.

        before_id — курсор для подгрузки более старой истории («загрузить ещё»
        при скролле вверх), а не offset: список живой (новые сообщения
        постоянно добавляются), offset-пагинация в такой ситуации будет
        "плавать" и дублировать/пропускать сообщения.
        """
        query = select(ChatMessageModel).where(ChatMessageModel.deleted_at.is_(None))
        query = (
            query.where(ChatMessageModel.group_id == group_id)
            if group_id is not None
            else query.where(ChatMessageModel.group_id.is_(None))
        )
        if before_id is not None:
            query = query.where(ChatMessageModel.id < before_id)

        result = await self.session.execute(
            query.options(selectinload(ChatMessageModel.user)).order_by(ChatMessageModel.id.desc()).limit(limit)
        )
        messages = list(result.scalars().all())
        messages.reverse()
        return messages

    async def get_by_id(self, message_id: int) -> ChatMessageModel | None:
        result = await self.session.execute(
            select(ChatMessageModel)
            .where(ChatMessageModel.id == message_id, ChatMessageModel.deleted_at.is_(None))
            .options(selectinload(ChatMessageModel.user))
        )
        return result.scalar_one_or_none()

    async def soft_delete(self, message: ChatMessageModel) -> None:
        message.deleted_at = datetime.now(timezone.utc)
        await self.session.commit()

    async def get_group_member_ids(self, group_id: int) -> list[int]:
        """Прямой запрос к user_group вместо обхода ORM-связи GroupModel.users —
        доступ к .users на объекте, полученном не через явный selectin в ЭТОМ
        запросе, падает с MissingGreenlet в асинхронной сессии."""
        result = await self.session.execute(select(user_group.c.user_id).where(user_group.c.group_id == group_id))
        return [row[0] for row in result.all()]
