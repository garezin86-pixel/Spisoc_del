# src/models/scheduled_event.py
"""Запланированные встречи и звонки (Этап 4 lite-CRM).

Прошедшее живёт в `interactions` (там дата не может быть в будущем), будущее — здесь. Когда встреча состоялась,
`POST /events/{id}/complete` в одной транзакции ставит статус done и создаёт взаимодействие
(`completed_interaction_id` указывает на него) — так «последний контакт» считается по-прежнему только по interactions.
Тип и статус хранятся строками (значения — EventType / EventStatus), как InteractionType: без PG-enum.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base
from src.models.audit import AuditMixin, SoftDeleteMixin
from src.models.mixins import TenantMixin


class EventType(str, Enum):
    call = "call"
    meeting = "meeting"


class EventStatus(str, Enum):
    planned = "planned"
    done = "done"
    cancelled = "cancelled"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScheduledEventModel(AuditMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "scheduled_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    contact_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Ответственный за событие. При удалении пользователя событие остаётся без ответственного.
    assignee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=EventStatus.planned.value, server_default=EventStatus.planned.value
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Взаимодействие, в которое превратилось состоявшееся событие (заполняется при complete)
    completed_interaction_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("interactions.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_scheduled_events_assignee_starts", "assignee_id", "starts_at"),
        Index("ix_scheduled_events_client_starts", "client_id", "starts_at"),
    )

    def __str__(self):
        return f"{self.type} #{self.id}"
