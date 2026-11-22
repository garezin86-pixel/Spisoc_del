# src/schemas/tables.py
"""Схемы Smart Tables (Этап 1): метаданные колонок и запрос строк.

Таблица — это живой запрос к данным CRM, а не копия. Колонки, фильтры и сортировка берутся только
из реестра (src/services/table_registry.py): произвольный SQL и неизвестные поля не принимаются.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

FilterOp = Literal["eq", "ne", "contains", "gt", "gte", "lt", "lte", "in", "is_null", "not_null"]
ColumnType = Literal["text", "number", "date", "datetime", "select", "user", "boolean"]


class TableFilter(BaseModel):
    """Одно условие: колонка, операция, значение (для is_null / not_null значение не нужно)."""

    field: str = Field(..., min_length=1, max_length=64)
    op: FilterOp
    value: Any = None


class TableSort(BaseModel):
    field: str = Field(..., min_length=1, max_length=64)
    direction: Literal["asc", "desc"] = "asc"


class SourceSchema(BaseModel):
    key: str
    label: str


class ColumnSchema(BaseModel):
    key: str
    label: str
    type: ColumnType
    # Можно ли править ячейку (используется на этапе правки; сервер всё равно проверяет права сам)
    editable: bool = False
    # Правка только для admin и manager (процессные поля сделки, ответственный)
    manager_only: bool = False
    # Колонка из другой сущности (клиент в таблице сделок) или расчётная: правка не меняет «эту» запись
    linked: bool = False
    filterable: bool = True
    sortable: bool = True
    ops: list[FilterOp] = Field(default_factory=list, description="Допустимые операции фильтра")
    options: Optional[list[str]] = Field(default=None, description="Допустимые значения для select")


class TableMetaSchema(BaseModel):
    source: str
    label: str
    columns: list[ColumnSchema]
    default_columns: list[str]


class TableRowsSchema(BaseModel):
    """Строки таблицы. В каждой строке кроме запрошенных колонок есть служебные:
    `_id` — id записи, `_version` — её updated_at (токен защиты от одновременной правки, этап 4)."""

    source: str
    columns: list[str]
    items: list[dict[str, Any]]
    total: int
    page: int
    size: int
    pages: int
