# src/schemas/user_table_import.py
"""Схемы импорта CSV/XLSX в самостоятельные таблицы (Smart Tables, шаг 4.6)."""

from typing import Any, Optional

from pydantic import BaseModel, Field

from src.schemas.user_custom_table import UserTableSchema


class ImportFileColumn(BaseModel):
    index: int = Field(..., description="Номер колонки в файле, с 0")
    header: str
    samples: list[str] = Field(default_factory=list, description="Первые значения для ориентира")
    suggested_type: str = Field(..., description="Подсказанный тип: text, number, date или boolean")


class ImportTargetColumn(BaseModel):
    key: str
    name: str
    data_type: str
    importable: bool = Field(..., description="false — колонка-связь (client, deal, user): из файла не заполняется")


class ImportFileColumns(BaseModel):
    columns: list[ImportFileColumn]
    total_rows: int
    # Только для импорта в существующую таблицу
    table_columns: Optional[list[ImportTargetColumn]] = None
    suggested_mapping: Optional[dict[str, int]] = Field(
        default=None, description="Колонка таблицы (ключ c<id>) → номер колонки файла, угадано по совпадению названий"
    )


class ImportIssue(BaseModel):
    row: int = Field(..., description="Номер строки в файле (строка 1 — заголовки)")
    message: str


class ImportPreviewRow(BaseModel):
    row: int
    values: dict[str, Any] = Field(description="Значения по названиям колонок")


class TableImportReport(BaseModel):
    dry_run: bool
    total_rows: int = 0
    to_create: int = Field(default=0, description="Сколько строк годятся (при dry_run ещё не созданы)")
    created: int = 0
    errors: list[ImportIssue] = Field(default_factory=list)
    warnings: list[ImportIssue] = Field(default_factory=list)
    preview: list[ImportPreviewRow] = Field(default_factory=list)
    table: Optional[UserTableSchema] = Field(
        default=None, description="Созданная таблица (только для создания из файла)"
    )


class TableImportColumnSpec(BaseModel):
    """Колонка новой таблицы при создании из файла: какая колонка файла и каким типом."""

    index: int = Field(..., ge=0)
    name: Optional[str] = Field(default=None, max_length=100, description="По умолчанию — заголовок из файла")
    data_type: str = Field(default="text", description="text, number, date, boolean или select")
    options: Optional[list[str]] = Field(default=None, description="Значения для select")
