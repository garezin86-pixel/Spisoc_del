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

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import aliased

from src.models.client import CLIENT_STATUSES, CLIENT_TYPES, ClientModel
from src.models.custom_field import VALUE_COLUMN_BY_TYPE, CustomFieldModel, CustomFieldValueModel
from src.models.deal import SUPPORTED_CURRENCIES, DealModel, StageKind, StageModel
from src.models.deal_item import DealItemModel
from src.models.interaction import InteractionModel
from src.models.user import UserModel
from src.models.user_custom_table import (
    CELL_VALUE_COLUMN_BY_TYPE,
    LINK_COLUMN_TYPES,
    UserCustomTableCellModel,
    UserCustomTableColumnModel,
    UserCustomTableModel,
    UserCustomTableRowModel,
)

# Допустимые операции фильтра по типу колонки
OPS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "text": ("eq", "ne", "contains", "in", "is_null", "not_null"),
    "number": ("eq", "ne", "gt", "gte", "lt", "lte", "in", "is_null", "not_null"),
    "date": ("eq", "gt", "gte", "lt", "lte", "is_null", "not_null"),
    "datetime": ("eq", "gt", "gte", "lt", "lte", "is_null", "not_null"),
    "select": ("eq", "ne", "in", "is_null", "not_null"),
    "user": ("eq", "ne", "in", "is_null", "not_null"),
    "client": ("eq", "ne", "in", "is_null", "not_null"),
    "deal": ("eq", "ne", "in", "is_null", "not_null"),
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
class CustomEntity:
    """Чьи свои поля показывает источник: сущность, выражение id её записи в запросе источника и подпись.

    linked=True — поля связанной сущности (клиент в таблице сделок): в таблице только чтение,
    подпись колонки начинается с prefix («Клиент: ЛС»)."""

    entity_type: str  # client | deal
    id_expr: Any
    linked: bool = False
    prefix: str = ""


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
    custom_entities: tuple[CustomEntity, ...] = ()  # свои поля каких сущностей добавляются колонками


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


# ── оборудование сделок ──────────────────────────────────────────────────────
# Строка таблицы — одна позиция оборудования; менеджер, клиент, стадия и дата закрытия берутся из её сделки.
_ITEM_COLUMNS: tuple[ColumnDef, ...] = (
    ColumnDef("id", "№", "number", DealItemModel.id, integer=True),
    ColumnDef("name", "Оборудование", "text", DealItemModel.name, editable=True),
    ColumnDef("price", "Цена", "number", DealItemModel.price, editable=True),
    ColumnDef("currency", "Валюта", "select", DealModel.currency, linked=True, options=tuple(SUPPORTED_CURRENCIES)),
    ColumnDef("deal_id", "Сделка (id)", "number", DealItemModel.deal_id, integer=True, linked=True),
    ColumnDef("deal_title", "Сделка", "text", DealModel.title, linked=True),
    ColumnDef("client_id", "Клиент (id)", "number", DealModel.client_id, integer=True, linked=True),
    ColumnDef("client_name", "Клиент", "text", ClientModel.name, linked=True),
    ColumnDef("owner_id", "Менеджер (id)", "user", DealModel.owner_id, linked=True),
    ColumnDef("owner_name", "Менеджер", "text", UserModel.username, linked=True),
    ColumnDef("stage_name", "Стадия", "text", StageModel.name, linked=True),
    ColumnDef(
        "stage_kind", "Вид стадии", "select", StageModel.kind, linked=True, options=tuple(k.value for k in StageKind)
    ),
    ColumnDef("closed_at", "Сделка закрыта", "datetime", DealModel.closed_at, linked=True),
    ColumnDef("created_at", "Добавлено", "datetime", DealItemModel.created_at),
    ColumnDef("updated_at", "Изменено", "datetime", DealItemModel.updated_at),
)


def _item_joins(stmt: Select) -> Select:
    return (
        stmt.select_from(DealItemModel)
        .join(DealModel, DealModel.id == DealItemModel.deal_id)
        .join(ClientModel, ClientModel.id == DealModel.client_id)
        .join(StageModel, StageModel.id == DealModel.stage_id)
        .outerjoin(UserModel, UserModel.id == DealModel.owner_id)
    )


def custom_columns(source: SourceDef, fields: Sequence[CustomFieldModel], workspace_id: int) -> list[ColumnDef]:
    """Колонки по своим полям компании (ключ cf_<id>) для источника.

    Значение берётся коррелированным подзапросом из custom_field_values по паре (поле, запись): строки без
    значения дают NULL, поэтому фильтры (в том числе «пусто») и сортировка работают как у обычных колонок."""
    entities = {ce.entity_type: ce for ce in source.custom_entities}
    order = {ce.entity_type: i for i, ce in enumerate(source.custom_entities)}
    value_model = CustomFieldValueModel
    columns: list[ColumnDef] = []
    for field in sorted(
        (f for f in fields if f.entity_type in entities), key=lambda f: (order[f.entity_type], f.position, f.id)
    ):
        entity = entities[field.entity_type]
        value_column = getattr(value_model, VALUE_COLUMN_BY_TYPE[field.field_type])
        expr = (
            select(value_column)
            .where(
                value_model.field_id == field.id,
                value_model.entity_id == entity.id_expr,
                value_model.workspace_id == workspace_id,
            )
            .correlate_except(value_model)
            .scalar_subquery()
        )
        columns.append(
            ColumnDef(
                key=f"cf_{field.id}",
                label=f"{entity.prefix}: {field.name}" if entity.prefix else field.name,
                type=field.field_type,
                expr=expr,
                editable=not entity.linked,
                linked=entity.linked,
                options=tuple(field.options or ()) if field.field_type == "select" else None,
            )
        )
    return columns


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
        custom_entities=(CustomEntity("client", ClientModel.id),),
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
        custom_entities=(
            CustomEntity("deal", DealModel.id),
            CustomEntity("client", ClientModel.id, linked=True, prefix="Клиент"),
        ),
    ),
    "deal_items": SourceDef(
        key="deal_items",
        label="Оборудование",
        model=DealItemModel,
        columns=_ITEM_COLUMNS,
        default_columns=("owner_name", "client_name", "name", "price", "currency", "closed_at"),
        joins=_item_joins,
        # Позиции удалённой сделки или удалённого клиента не показываются (как и сами сделки)
        extra_conditions=lambda: [DealModel.not_deleted_filter(), ClientModel.not_deleted_filter()],
        default_sort=(("id", "desc"),),
        custom_entities=(
            CustomEntity("deal", DealModel.id, linked=True, prefix="Сделка"),
            CustomEntity("client", ClientModel.id, linked=True, prefix="Клиент"),
        ),
    ),
}


# ── самостоятельные таблицы пользователей (источник uct_<id>) ─────────────────
USER_TABLE_PREFIX = "uct_"


def parse_user_table_source_key(key: str) -> int | None:
    """`uct_12` → 12; всё остальное (в том числе `uct_012`, `uct_x`, `uct_0`) → None."""
    if not key.startswith(USER_TABLE_PREFIX):
        return None
    number = key[len(USER_TABLE_PREFIX) :]
    if not number.isascii() or not number.isdigit() or number != str(int(number)) or int(number) < 1:
        return None
    return int(number)


DELETED_LINK_LABEL = "(удалён)"


def _link_label(column: UserCustomTableColumnModel, ref_expr: Any, workspace_id: int) -> Any:
    """Название записи, на которую ссылается ячейка-связь: клиент — имя, сделка — название, пользователь — логин.

    Нет связи — NULL; запись удалена или исчезла — «(удалён)». Подзапрос идёт по паре (ячейка, запись CRM) и
    коррелирует только со строкой источника (алиасы — чтобы не спутать с теми же таблицами во внешнем запросе)."""
    cell = UserCustomTableCellModel
    row = UserCustomTableRowModel
    if column.data_type == "client":
        target = aliased(ClientModel)
        name, alive = target.name, target.not_deleted_filter()
    elif column.data_type == "deal":
        target = aliased(DealModel)
        name, alive = target.title, target.not_deleted_filter()
    else:
        target = aliased(UserModel)
        name, alive = target.username, target.workspace_id == workspace_id
    label = (
        select(name)
        .select_from(cell)
        .join(target, target.id == cell.value_ref)
        .where(
            cell.column_id == column.id,
            cell.row_id == row.id,
            cell.workspace_id == workspace_id,
            target.workspace_id == workspace_id,
            alive,
        )
        .correlate(row)
        .scalar_subquery()
    )
    return case((ref_expr.is_(None), None), else_=func.coalesce(label, DELETED_LINK_LABEL))


def user_table_source(
    table: UserCustomTableModel, columns: Sequence[UserCustomTableColumnModel], workspace_id: int
) -> SourceDef:
    """Источник по самостоятельной таблице: строка таблицы = строка источника, колонка таблицы = колонка `c<id>`.

    Значение ячейки берётся коррелированным подзапросом из user_custom_table_cells по паре (строка, колонка):
    пустые ячейки дают NULL, поэтому фильтры (в том числе «пусто») и сортировка работают как у обычных колонок.
    Служебные колонки идут после пользовательских."""
    cell = UserCustomTableCellModel
    row = UserCustomTableRowModel
    user_columns: list[ColumnDef] = []
    default_keys: list[str] = []
    for column in columns:
        value_column = getattr(cell, CELL_VALUE_COLUMN_BY_TYPE[column.data_type])
        expr = (
            select(value_column)
            .where(cell.column_id == column.id, cell.row_id == row.id, cell.workspace_id == workspace_id)
            .correlate_except(cell)
            .scalar_subquery()
        )
        if column.data_type in LINK_COLUMN_TYPES:
            # Связь даёт две колонки, как «Клиент (id)» и «Клиент» в таблице сделок: id — для фильтров и правки,
            # название — для показа. Название удалённой записи — «(удалён)», а не битый id.
            user_columns.append(
                ColumnDef(
                    key=column.key,
                    label=f"{column.name} (id)",
                    type=column.data_type,
                    expr=expr,
                    editable=True,
                )
            )
            user_columns.append(
                ColumnDef(
                    key=f"{column.key}_name",
                    label=column.name,
                    type="text",
                    expr=_link_label(column, expr, workspace_id),
                    linked=True,
                )
            )
            default_keys.append(f"{column.key}_name")
            continue
        user_columns.append(
            ColumnDef(
                key=column.key,
                label=column.name,
                type=column.data_type,
                expr=expr,
                editable=True,
                options=tuple(column.options or ()) if column.data_type == "select" else None,
            )
        )
        default_keys.append(column.key)
    service_columns = (
        ColumnDef("id", "№", "number", row.id, integer=True),
        ColumnDef("created_by_name", "Добавил", "text", UserModel.username, linked=True),
        ColumnDef("created_at", "Добавлена", "datetime", row.created_at),
        ColumnDef("updated_at", "Изменена", "datetime", row.updated_at),
    )
    table_id = table.id

    def joins(stmt: Select) -> Select:
        return stmt.select_from(row).outerjoin(UserModel, UserModel.id == row.created_by_id)

    return SourceDef(
        key=f"{USER_TABLE_PREFIX}{table_id}",
        label=table.name,
        model=row,
        columns=(*user_columns, *service_columns),
        default_columns=tuple(default_keys) or ("id",),
        joins=joins,
        extra_conditions=lambda: [row.table_id == table_id],
        default_sort=(("id", "asc"),),
    )
