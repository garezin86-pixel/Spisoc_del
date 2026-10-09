# src/models/deal.py
"""Сделки и воронка продаж (Этап 3 lite-CRM).

Воронка одна на компанию (создаётся при первом обращении, см. DealService), стадии — строки
таблицы stages с видом open / won / lost. Поля сделки делятся по влиянию на процесс:
  * процессные — stage_id (меняется только через move), amount, owner_id, expected_close_date,
    удаление: правят admin и manager (стадию двигает ещё ответственный по сделке);
  * справочные — title, notes: правят ещё и ответственный по сделке.
Валюты нет: сумма — в единой валюте компании. Тип стадии хранится строкой, как InteractionType.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base
from src.models.audit import AuditMixin, SoftDeleteMixin
from src.models.mixins import TenantMixin


class StageKind(str, Enum):
    open = "open"
    won = "won"
    lost = "lost"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PipelineModel(AuditMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "pipelines"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __str__(self):
        return self.name


class StageModel(AuditMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "stages"

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default=StageKind.open.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (Index("ix_stages_pipeline_id", "pipeline_id"),)

    def __str__(self):
        return self.name


class DealModel(AuditMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    stage_id: Mapped[int] = mapped_column(ForeignKey("stages.id", ondelete="RESTRICT"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expected_close_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    lost_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_deals_client_id", "client_id"),
        Index("ix_deals_stage_id", "stage_id"),
        Index("ix_deals_owner_id", "owner_id"),
    )

    def __str__(self):
        return f"{self.title} (id={self.id})"
