# src/models/custom_field.py
"""Свои поля (Smart Tables, этап 3): колонки, которых нет в CRM, например «ЛС» у клиента.

`custom_fields` — определение поля (сущность, название, тип, список значений для типа «список»).
`custom_field_values` — значение поля у конкретной записи (клиента или сделки). Значения хранятся в
ТИПИЗИРОВАННЫХ колонках (текст, число, дата, флажок), а не в JSON: так фильтры и сортировка работают как у
обычных колонок, без приведения типов и без различий между PostgreSQL и SQLite.

Запись значения: одна строка на пару (поле, запись). Очистка значения обнуляет колонки, строка остаётся
(нет жёсткого удаления — каждое изменение видно в аудите). У записи заполнена ровно одна value_* колонка,
соответствующая типу поля. Таблицы CRM (clients, deals) не меняются.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base
from src.models.audit import AuditMixin, SoftDeleteMixin
from src.models.mixins import TenantMixin


class CustomFieldType(str, Enum):
    text = "text"
    number = "number"
    date = "date"
    select = "select"
    boolean = "boolean"


# Сущности, к которым можно добавлять поля
CUSTOM_ENTITY_TYPES = ("client", "deal")

# В какой колонке custom_field_values хранится значение поля каждого типа
VALUE_COLUMN_BY_TYPE: dict[str, str] = {
    CustomFieldType.text.value: "value_text",
    CustomFieldType.select.value: "value_text",
    CustomFieldType.number.value: "value_number",
    CustomFieldType.date.value: "value_date",
    CustomFieldType.boolean.value: "value_bool",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CustomFieldModel(AuditMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "custom_fields"
    __audit_skip_fields__ = frozenset({"position"})

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # client | deal
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    field_type: Mapped[str] = mapped_column(String(10), nullable=False)  # CustomFieldType; после создания не меняется
    options: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)  # только для типа «список»
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (Index("ix_custom_fields_workspace_entity", "workspace_id", "entity_type"),)

    def __str__(self):
        return f"{self.name} ({self.entity_type}, id={self.id})"


class CustomFieldValueModel(AuditMixin, TenantMixin, Base):
    __tablename__ = "custom_field_values"

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("custom_fields.id", ondelete="CASCADE"), nullable=False)
    # id клиента или сделки (какой именно — определяет поле). Внешнего ключа нет: ссылка на две таблицы,
    # существование записи проверяет сервис.
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)

    value_text: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)  # текст и список
    value_number: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    value_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    value_bool: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("field_id", "entity_id", name="uq_custom_field_values_field_entity"),
        Index("ix_custom_field_values_entity_id", "entity_id"),
    )

    def value_for(self, field_type: str) -> Any:
        """Значение в виде для API: число — float, дата — ISO-строка (как во всём API)."""
        raw = getattr(self, VALUE_COLUMN_BY_TYPE[field_type])
        if raw is None:
            return None
        if isinstance(raw, Decimal):
            return float(raw)
        if isinstance(raw, date):
            return raw.isoformat()
        return raw

    def __str__(self):
        return f"field {self.field_id} / entity {self.entity_id}"
