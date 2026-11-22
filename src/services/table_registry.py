# src/services/table_registry.py
"""Реестр источников и колонок Smart Tables (Этап 1).

Реестр — единственное место, откуда берутся колонки, фильтры и сортировка таблиц: пользовательский
запрос может сослаться только на ключи отсюда. Это защищает от произвольного SQL и гарантирует, что
таблица читает те же записи, что и обычные списки CRM (с тем же мягким удалением и изоляцией компаний).

Чтобы добавить колонку: допишите ColumnDef в нужный источник. Чтобы добавить источник (например, задачи):
опишите колонки и функцию соединений, добавьте SourceDef в SOURCES.

Флаги editable / manager_only / linked на этапе 1 только описывают колонку для интерфейса; запись появится
на этапе 4 и пойдёт через существующие сервисы (права проверяют они).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, select

from src.models.client import CLIENT_STATUSES, CLIENT_TYPES, ClientModel
from src.models.deal import SUPPORTED_CURRENCIES, DealModel, StageKind, StageModel
from src.models.interaction import InteractionModel
from src.models.user import UserModel

# Допустимые операции фильтра по типу колонки
OPS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "text": ("eq", "ne", "contains", "in", "is_null", "not_null"),
    "number": ("eq", "ne", "gt", "gte", "lt", "lte", "in", "is_null", "not_null"),
    "date": ("eq", "gt", "gte", "lt", "lte", "is_null", "not_null"),
    "datetime": ("eq", "gt", "gte", "lt", "lte", "is_null", "not_null"),
    "select": ("eq", "ne", "in", "is_null", "not_null"),
    "user": ("eq", "ne", "in", "is_null", "not_null"),
    "boolean": ("eq",),
}


@dataclass(frozen=True)
class ColumnDef:
    key: str
    label: str
    type: str  # text | number | date | datetime | select | user | boolean
    expr: Any  # SQL-выражение колонки (атрибут модели, подзапрос и т.п.)
    editable: bool = False
    manager_only: bool = False
    linked: bool = False
    filterable: bool = True
    sortable: bool = True
    integer: bool = False  # number: целое (id), иначе Decimal
    options: tuple[str, ...] | None = None  # допустимые значения для select


@dataclass(frozen=True)
class SourceDef:
    key: str
    label: str
    model: Any  # главная модель (id, workspace_id, deleted_at, updated_at)
    columns: tuple[ColumnDef, ...]
    default_columns: tuple[str, ...]
    joins: Callable[[Select], Select]  # навешивает select_from и соединения
    extra_conditions: Callable[[], list[Any]]  # условия сверх workspace_id и мягкого удаления главной модели
    default_sort: tuple[
        tuple[str, str], ...
    ] = ()  # порядок, если пользователь не задал сортировку: (колонка, asc|desc)

    def column(self, key: str) -> ColumnDef | None:
        return next((c for c in self.columns if c.key == key), None)


# ── клиенты ──────────────────────────────────────────────────────────────────
# Дата последнего живого взаимодействия клиента (коррелированный подзапрос)
_LAST_INTERACTION = (
    select(func.max(InteractionModel.occurred_at))
    .where(InteractionModel.client_id == ClientModel.id, InteractionModel.not_deleted_filter())
    .correlate(ClientModel)
    .scalar_subquery()
)

_CLIENT_COLUMNS: tuple[ColumnDef, ...] = (
    ColumnDef("id", "№", "number", ClientModel.id, integer=True),
    ColumnDef("name", "Название", "text", ClientModel.name, editable=True),
    ColumnDef("client_type", "Тип", "select", ClientModel.client_type, editable=True, options=tuple(CLIENT_TYPES)),
    ColumnDef("status", "Статус", "select", ClientModel.status, editable=True, options=tuple(CLIENT_STATUSES)),
    ColumnDef("phone", "Телефон", "text", ClientModel.phone, editable=True),
    ColumnDef("email", "Email", "text", ClientModel.email, editable=True),
    ColumnDef("address", "Адрес", "text", ClientModel.address, editable=True),
    ColumnDef("notes", "Заметки", "text", ClientModel.notes, editable=True),
    ColumnDef("owner_id", "Ответственный (id)", "user", ClientModel.owner_id, editable=True, manager_only=True),
    ColumnDef("owner_name", "Ответственный", "text", UserModel.username, linked=True),
    ColumnDef("next_contact_at", "Связаться снова", "date", ClientModel.next_contact_at, editable=True),
    ColumnDef("last_interaction_at", "Последний контакт", "datetime", _LAST_INTERACTION, linked=True),
    ColumnDef("created_at", "Создан", "datetime", ClientModel.created_at),
    ColumnDef("updated_at", "Изменён", "datetime", ClientModel.updated_at),
)


def _client_joins(stmt: Select) -> Select:
    return stmt.select_from(ClientModel).outerjoin(UserModel, UserModel.id == ClientModel.owner_id)


# ── сделки ───────────────────────────────────────────────────────────────────
_DEAL_COLUMNS: tuple[ColumnDef, ...] = (
    ColumnDef("id", "№", "number", DealModel.id, integer=True),
    ColumnDef("title", "Сделка", "text", DealModel.title, editable=True),
    ColumnDef("client_id", "Клиент (id)", "number", DealModel.client_id, integer=True, linked=True),
    ColumnDef("client_name", "Клиент", "text", ClientModel.name, linked=True),
    ColumnDef(
        "client_type", "Тип клиента", "select", ClientModel.client_type, linked=True, options=tuple(CLIENT_TYPES)
    ),
    ColumnDef("stage_id", "Стадия (id)", "number", DealModel.stage_id, integer=True, linked=True),
    ColumnDef("stage_name", "Стадия", "text", StageModel.name, linked=True),
    ColumnDef(
        "stage_kind",
        "Вид стадии",
        "select",
        StageModel.kind,
        linked=True,
        options=tuple(k.value for k in StageKind),
    ),
    ColumnDef("amount", "Сумма", "number", DealModel.amount, editable=True, manager_only=True),
    ColumnDef(
        "currency",
        "Валюта",
        "select",
        DealModel.currency,
        editable=True,
        manager_only=True,
        options=tuple(SUPPORTED_CURRENCIES),
    ),
    ColumnDef("owner_id", "Менеджер (id)", "user", DealModel.owner_id, editable=True, manager_only=True),
    ColumnDef("owner_name", "Менеджер", "text", UserModel.username, linked=True),
    ColumnDef(
        "expected_close_date",
        "Ожидаемое закрытие",
        "date",
        DealModel.expected_close_date,
        editable=True,
        manager_only=True,
    ),
    ColumnDef("closed_at", "Закрыта", "datetime", DealModel.closed_at),
    ColumnDef("lost_reason", "Причина отказа", "text", DealModel.lost_reason),
    ColumnDef("notes", "Заметки", "text", DealModel.notes, editable=True),
    ColumnDef("created_at", "Создана", "datetime", DealModel.created_at),
    ColumnDef("updated_at", "Изменена", "datetime", DealModel.updated_at),
)


def _deal_joins(stmt: Select) -> Select:
    return (
        stmt.select_from(DealModel)
        .join(ClientModel, ClientModel.id == DealModel.client_id)
        .join(StageModel, StageModel.id == DealModel.stage_id)
        .outerjoin(UserModel, UserModel.id == DealModel.owner_id)
    )


SOURCES: dict[str, SourceDef] = {
    "clients": SourceDef(
        key="clients",
        label="Клиенты",
        model=ClientModel,
        columns=_CLIENT_COLUMNS,
        default_columns=("name", "client_type", "status", "phone", "owner_name", "last_interaction_at"),
        joins=_client_joins,
        extra_conditions=lambda: [],
        default_sort=(("name", "asc"),),
    ),
    "deals": SourceDef(
        key="deals",
        label="Сделки",
        model=DealModel,
        columns=_DEAL_COLUMNS,
        default_columns=("title", "client_name", "stage_name", "amount", "currency", "owner_name", "closed_at"),
        joins=_deal_joins,
        # Сделка удалённого клиента в таблице не показывается (как и в списках CRM)
        extra_conditions=lambda: [ClientModel.not_deleted_filter()],
        default_sort=(("id", "desc"),),
    ),
}
