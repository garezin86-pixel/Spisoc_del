# src/models/chat_message.py
"""Командный чат — общий канал для непринуждённого общения, не привязанный
к конкретной задаче (в отличие от комментариев). См. src/routers/chat_router.py.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base


class ChatMessageModel(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # NULL — общий канал (виден всем). Заполнен — приватный канал конкретной
    # группы (виден только её участникам, см. ChatService/chat_router).
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True)
    # Заполнен — личное сообщение конкретному пользователю (взаимоисключимо
    # с group_id: у ЛС group_id всегда NULL). См. ChatService.send_dm.
    recipient_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    # Простое скрытие своего сообщения — без полноценного audit-трейла, как
    # у задач/комментариев: для непринуждённого чата это overkill.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("UserModel", foreign_keys=[user_id])
    recipient = relationship("UserModel", foreign_keys=[recipient_id])
