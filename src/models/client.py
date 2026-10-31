# src/models/client.py
"""Клиенты и их контактные лица (Этап 1 lite-CRM).

Оба класса — tenant-таблицы (TenantMixin), с аудитом (AuditMixin) и мягким
удалением (SoftDeleteMixin), как комментарии и задачи. Физически строки не
удаляются: DELETE /clients/{id} ставит deleted_at клиенту и всем его контактам.
"""

from datetime import date, datetime, timezone
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base
from src.models.audit import AuditMixin, SoftDeleteMixin
from src.models.mixins import TenantMixin

# Тип клиента: компания (B2B) или частное лицо (B2C). У частного лица в name хранится ФИО.
CLIENT_TYPES = ("company", "person")
DEFAULT_CLIENT_TYPE = "company"

# Статус клиента: active — работаем; inactive — «спящий» (давно не покупает, но не потерян);
# blacklisted — чёрный список (с ним не работаем: напоминания и «давно без контакта» его не затрагивают).
CLIENT_STATUSES = ("active", "inactive", "blacklisted")
DEFAULT_CLIENT_STATUS = "active"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ClientModel(AuditMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "clients"
    __audit_skip_fields__ = frozenset({"next_contact_notified_at"})  # системная отметка, не история

    id: Mapped[int] = mapped_column(primary_key=True)
    # Название не уникально: одноимённые клиенты бывают. Для частного лица (person) — ФИО.
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    client_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default=DEFAULT_CLIENT_TYPE, server_default=DEFAULT_CLIENT_TYPE
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=DEFAULT_CLIENT_STATUS, server_default=DEFAULT_CLIENT_STATUS
    )
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Создан кнопкой «Загрузить демо-данные»: по этому флагу демо убирается, не затрагивая настоящих клиентов
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())

    # Ответственный сотрудник. При удалении пользователя клиент остаётся без ответственного.
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Только для частного лица (client_type = person): дата рождения и пол. У компании всегда пусто.
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # "male" | "female"

    # «Связаться снова»: когда ответственный должен вернуться к клиенту. В этот день (или позже, если сервис не работал)
    # он получает напоминание; next_contact_notified_at — служебная отметка «напомнили», сбрасывается при смене даты.
    next_contact_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    next_contact_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_clients_owner_id", "owner_id"),
        Index("ix_clients_next_contact_at", "next_contact_at"),
        Index("ix_clients_status", "status"),
    )

    def __str__(self):
        return f"{self.name} (id={self.id})"


class ContactModel(AuditMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (Index("ix_contacts_client_id", "client_id"),)

    def __str__(self):
        return f"{self.name} (id={self.id})"
