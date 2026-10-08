# src/models/interaction.py
"""Взаимодействия с клиентом (Этап 2 lite-CRM): звонки, встречи, письма, заметки.

Поля делятся по влиянию на процесс работы с клиентом:
  * процессные — type, occurred_at (от них считается «последний контакт»): после
    создания их меняют только admin и manager;
  * справочные — summary, contact_id: правят автор, ответственный за клиента, admin, manager.
Тип хранится строкой (значения — InteractionType), а не PG-enum: список типов проще менять без миграций.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base
from src.models.audit import AuditMixin, SoftDeleteMixin
from src.models.mixins import TenantMixin


class InteractionType(str, Enum):
    call = "call"
    meeting = "meeting"
    email = "email"
    message = "message"
    note = "note"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InteractionModel(AuditMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    contact_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (Index("ix_interactions_client_occurred", "client_id", "occurred_at"),)

    def __str__(self):
        return f"{self.type} #{self.id}"
