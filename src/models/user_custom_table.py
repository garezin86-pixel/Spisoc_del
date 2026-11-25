# src/models/user_custom_table.py
"""Самостоятельные таблицы пользователей (Smart Tables, этап 4): свои колонки и строки без привязки к CRM.

Таблица принадлежит КОМПАНИИ (TenantMixin), а не человеку: `owner_id` — отдельное необязательное поле
(ON DELETE SET NULL), поэтому при увольнении владельца данные не теряются, а admin и manager могут назначить нового.

Шаг 4.1: таблицы и колонки. Шаг 4.2: строки и ячейки. Шаг 4.5: участники таблицы с ограниченным доступом.
Колонки хранят только описание; ключ колонки `c<id>` вычисляется из id и не меняется при переименовании.
Удаление таблиц и колонок мягкое — данные не теряются безвозвратно.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base
from src.models.audit import AuditMixin, SoftDeleteMixin
from src.models.custom_field import VALUE_COLUMN_BY_TYPE
from src.models.mixins import TenantMixin


class UserTableVisibility(str, Enum):
    private = "private"  # владелец, admin и manager
    shared = "shared"  # вся компания
    restricted = "restricted"  # владелец, admin, manager и выбранные пользователи (участники таблицы)


class UserTableColumnType(str, Enum):
    text = "text"
    number = "number"
    date = "date"
    boolean = "boolean"
    select = "select"
    # Связи (шаг 4.4): ячейка хранит id клиента, сделки или пользователя; одна связь на ячейку
    client = "client"
    deal = "deal"
    user = "user"


LINK_COLUMN_TYPES = (UserTableColumnType.client.value, UserTableColumnType.deal.value, UserTableColumnType.user.value)

# В какой value_* колонке ячейки хранится значение колонки каждого типа
CELL_VALUE_COLUMN_BY_TYPE: dict[str, str] = VALUE_COLUMN_BY_TYPE | {t: "value_ref" for t in LINK_COLUMN_TYPES}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserCustomTableModel(AuditMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "user_custom_tables"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # эмодзи
    visibility: Mapped[str] = mapped_column(
        String(10), nullable=False, default=UserTableVisibility.shared.value, server_default="shared"
    )
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __str__(self):
        return f"{self.name} (id={self.id})"


class UserCustomTableColumnModel(AuditMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "user_custom_table_columns"
    __audit_skip_fields__ = frozenset({"position"})

    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("user_custom_tables.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    data_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # UserTableColumnType; после создания не меняется
    options: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)  # только для типа «список»
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (Index("ix_user_custom_table_columns_table_id", "table_id"),)

    @property
    def key(self) -> str:
        """Стабильный ключ колонки (c<id>): не меняется при переименовании."""
        return f"c{self.id}"

    def __str__(self):
        return f"{self.name} (id={self.id})"


class UserCustomTableRowModel(AuditMixin, SoftDeleteMixin, TenantMixin, Base):
    """Строка самостоятельной таблицы. `updated_at` — токен версии строки для защиты от одновременной правки:
    он обновляется при записи ЛЮБОЙ ячейки строки (само обновление ячейки строку в БД не меняет, поэтому сервис
    ставит его явно)."""

    __tablename__ = "user_custom_table_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("user_custom_tables.id", ondelete="CASCADE"), nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (Index("ix_user_custom_table_rows_table_id", "table_id"),)

    def __str__(self):
        return f"row {self.id} (table {self.table_id})"


class UserCustomTableCellModel(AuditMixin, TenantMixin, Base):
    """Значение одной ячейки: пара (строка, колонка). Типизированные колонки value_* — как у своих полей (этап 3):
    фильтры и сортировка работают как у обычных колонок, без JSON. Заполнена ровно одна value_* колонка по типу
    колонки; очистка обнуляет их, строка остаётся (каждое изменение видно в аудите)."""

    __tablename__ = "user_custom_table_cells"

    id: Mapped[int] = mapped_column(primary_key=True)
    row_id: Mapped[int] = mapped_column(ForeignKey("user_custom_table_rows.id", ondelete="CASCADE"), nullable=False)
    column_id: Mapped[int] = mapped_column(
        ForeignKey("user_custom_table_columns.id", ondelete="CASCADE"), nullable=False
    )

    value_text: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)  # текст и список
    value_number: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    value_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    value_bool: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # Связь с CRM: id клиента, сделки или пользователя (вид определяет тип колонки). Внешнего ключа нет — ссылка на
    # разные таблицы; существование проверяет сервис, а удалённая запись показывается как «(удалён)».
    value_ref: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("row_id", "column_id", name="uq_user_custom_table_cells_row_column"),
        Index("ix_user_custom_table_cells_column_id", "column_id"),
        Index("ix_user_custom_table_cells_value_ref", "value_ref"),
    )

    def value_for(self, data_type: str) -> Any:
        """Значение в виде для API: число — float, дата — ISO-строка (как во всём API)."""
        raw = getattr(self, CELL_VALUE_COLUMN_BY_TYPE[data_type])
        if raw is None:
            return None
        if isinstance(raw, Decimal):
            return float(raw)
        if isinstance(raw, date):
            return raw.isoformat()
        return raw

    def __str__(self):
        return f"cell row {self.row_id} / column {self.column_id}"


class UserCustomTableMemberModel(AuditMixin, SoftDeleteMixin, TenantMixin, Base):
    """Участник таблицы с видимостью `restricted`: пользователь, которому владелец дал доступ.

    `can_edit` — может ли участник менять строки (иначе только читает). Структуру и список участников меняют
    только владелец, admin и manager — это не делегируется. Удаление мягкое (история в аудите); при повторном
    добавлении запись восстанавливается."""

    __tablename__ = "user_custom_table_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("user_custom_tables.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    can_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("table_id", "user_id", name="uq_user_custom_table_members_table_user"),
        Index("ix_user_custom_table_members_user_id", "user_id"),
    )

    def __str__(self):
        return f"member {self.user_id} of table {self.table_id}"
