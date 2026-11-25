# src/models/deal_item.py
"""Оборудование сделки (Smart Tables, этап 2): строки «что продали и за сколько».

Одна строка — одно оборудование: название (свободный текст, справочника нет) и цена, которую вводят вручную.
Валюта строки — валюта сделки (отдельной валюты у позиции нет). Цена позиции НЕ меняет сумму сделки:
сумма остаётся отдельным полем сделки, правило «у выигранной сделки сумма обязательна» не затрагивается.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base
from src.models.audit import AuditMixin, SoftDeleteMixin
from src.models.mixins import TenantMixin


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DealItemModel(AuditMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "deal_items"
    __audit_skip_fields__ = frozenset({"position"})

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    # Порядок строк внутри сделки (0 — первая). Перестановки в аудит не пишутся.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    author_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Сделка (только чтение): из неё берётся валюта строки
    deal = relationship("DealModel", lazy="selectin", viewonly=True)

    @property
    def currency(self) -> Optional[str]:
        return self.deal.currency if self.deal is not None else None

    __table_args__ = (Index("ix_deal_items_deal_id", "deal_id"),)

    def __str__(self):
        return f"{self.name} (id={self.id})"
