# src/services/user_table_import_service.py
"""Импорт CSV/XLSX в самостоятельные таблицы (Smart Tables, шаг 4.6).

Файл читается теми же функциями, что и импорт клиентов (`client_import_service.read_table`: кодировки
cp1251/utf-8, разделитель «,» или «;», .xlsx, лимиты 5 МБ и 5000 строк); дополнительно не больше 30 000 ячеек
за раз. Два сценария:
  * импорт в существующую таблицу: колонки файла сопоставляются с колонками таблицы (подсказка по названиям);
  * создание таблицы из файла: колонки и их типы берутся из заголовков и значений (тип можно задать явно).
`dry_run=True` ничего не пишет и отдаёт тот же отчёт — это предпросмотр. Строки создаются одной транзакцией.

Неверное значение ячейки не отменяет импорт: ячейка остаётся пустой, в отчёте появляется предупреждение с номером
строки. Строка, в которой после разбора не осталось ни одного значения, пропускается (ошибка в отчёте).
Колонки-связи (client, deal, user) из файла не заполняются.

Права: импорт в таблицу — как добавление строк (тот, кто может их править); создание из файла — как создание
таблицы (любой пользователь компании).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog
from fastapi import HTTPException

from src.models.user import UserModel
from src.models.user_custom_table import (
    CELL_VALUE_COLUMN_BY_TYPE,
    LINK_COLUMN_TYPES,
    UserCustomTableCellModel,
    UserCustomTableColumnModel,
    UserCustomTableModel,
    UserCustomTableRowModel,
)
from src.repositories.user_custom_table_row_repository import UserCustomTableRowRepository
from src.schemas.user_custom_table import (
    MAX_COLUMNS_PER_TABLE,
    UserTableColumnCreate,
    UserTableCreate,
)
from src.schemas.user_table_import import (
    ImportFileColumn,
    ImportFileColumns,
    ImportIssue,
    ImportPreviewRow,
    ImportTargetColumn,
    TableImportColumnSpec,
    TableImportReport,
)
from src.services import user_custom_table_row_service as row_limits
from src.services import user_custom_table_service as table_limits
from src.services.client_import_service import ClientImportError, _cell_text, _parse_date, read_table
from src.services.user_custom_table_service import UserCustomTableService
from src.services.value_coercion import MAX_NUMBER, MAX_TEXT_LENGTH

logger = structlog.get_logger()

PREVIEW_ROWS = 10
# Каждая ячейка пишется в аудит, поэтому импорт ограничен по числу ячеек (строки × колонки), а не только по строкам:
# замер — 25 000 ячеек за ~12 с. Больше — частями.
MAX_IMPORT_CELLS = 30_000
INFER_SAMPLE_ROWS = 200
IMPORT_TYPES = ("text", "number", "date", "boolean", "select")  # типы, которые заполняются из файла

_TRUE_WORDS = {"да", "д", "yes", "y", "true", "истина", "+", "✓", "1"}
_FALSE_WORDS = {"нет", "н", "no", "n", "false", "ложь", "-", "0"}
_SPACES = re.compile(r"[\s\u00a0\u202f]")
_ID_LIKE = re.compile(r"^(0\d+|\d{9,})$")  # «0123456», телефон, ЛС, ИНН: теряют вид при хранении числом


# ── разбор значений ячеек ────────────────────────────────────────────────────
def _is_empty(raw: Any) -> bool:
    return raw is None or (isinstance(raw, str) and not raw.strip())


def parse_number(raw: Any) -> tuple[Decimal | None, str | None]:
    """Число из ячейки: 12.5, «12,5», «1 234,50», «1.234,50». До 4 знаков после запятой (лишние округляются)."""
    if _is_empty(raw):
        return None, None
    if isinstance(raw, bool):
        return None, "число «да/нет» не распознано, оставлено пустым"
    try:
        if isinstance(raw, (int, float, Decimal)):
            number = Decimal(str(raw))
            shown = str(raw)
        else:
            shown = str(raw).strip()
            text = _SPACES.sub("", shown)
            if "," in text and "." in text:  # последний разделитель — десятичный, другой — тысячные
                decimal = "," if text.rfind(",") > text.rfind(".") else "."
                thousands = "." if decimal == "," else ","
                text = text.replace(thousands, "").replace(decimal, ".")
            elif text.count(",") > 1 or text.count(".") > 1:
                text = text.replace(",", "").replace(".", "")
            else:
                text = text.replace(",", ".")
            number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None, f"число «{_cell_text(raw)}» не распознано, оставлено пустым"
    if not number.is_finite() or abs(number) >= MAX_NUMBER:
        return None, f"число «{shown}» слишком большое, оставлено пустым"
    rounded = number.quantize(Decimal("0.0001"))
    warning = f"число «{shown}» округлено до 4 знаков" if abs(rounded - number) > Decimal("0.000001") else None
    return rounded, warning


def parse_bool(raw: Any) -> tuple[bool | None, str | None]:
    if _is_empty(raw):
        return None, None
    if isinstance(raw, bool):
        return raw, None
    key = str(raw).strip().lower()
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        key = str(int(raw)) if float(raw).is_integer() else key
    if key in _TRUE_WORDS:
        return True, None
    if key in _FALSE_WORDS:
        return False, None
    return None, f"значение «{_cell_text(raw)}» не распознано как да/нет, оставлено пустым"


def parse_date(raw: Any) -> tuple[date | None, str | None]:
    if _is_empty(raw):
        return None, None
    return _parse_date(raw)


def parse_select(raw: Any, options: list[str]) -> tuple[str | None, str | None]:
    if _is_empty(raw):
        return None, None
    text = _cell_text(raw)
    by_case = {option.casefold(): option for option in options}
    found = by_case.get(text.casefold())
    if found is None:
        return None, f"значения «{text}» нет в списке, оставлено пустым"
    return found, None


def parse_text(raw: Any) -> tuple[str | None, str | None]:
    if _is_empty(raw):
        return None, None
    text = _cell_text(raw)
    if len(text) > MAX_TEXT_LENGTH:
        return text[:MAX_TEXT_LENGTH], f"текст длиннее {MAX_TEXT_LENGTH} символов обрезан"
    return text, None


def convert(data_type: str, options: list[str] | None, raw: Any) -> tuple[Any, str | None]:
    """Значение ячейки файла → значение для колонки данного типа и предупреждение (если было)."""
    if data_type == "number":
        return parse_number(raw)
    if data_type == "boolean":
        return parse_bool(raw)
    if data_type == "date":
        return parse_date(raw)
    if data_type == "select":
        return parse_select(raw, options or [])
    return parse_text(raw)


def infer_type(samples: list[Any]) -> str:
    """Тип колонки по значениям: подходит только если ПОДХОДЯТ ВСЕ непустые значения (иначе text — без потерь).

    Числа с ведущим нулём и длинные цифровые строки (телефоны, ЛС, ИНН) остаются текстом: числом они потеряли бы вид."""
    values = [v for v in samples if not _is_empty(v)][:INFER_SAMPLE_ROWS]
    if not values:
        return "text"
    if all(isinstance(v, bool) for v in values):
        return "boolean"
    if all(isinstance(v, (datetime, date)) or (isinstance(v, str) and _parse_date(v)[0] is not None) for v in values):
        return "date"
    if all(
        not isinstance(v, bool) and parse_number(v) != (None, None) and parse_number(v)[0] is not None for v in values
    ):
        if not any(_ID_LIKE.match(_cell_text(v)) for v in values):
            return "number"
        return "text"
    words = {str(v).strip().lower() for v in values}
    if (
        words <= (_TRUE_WORDS | _FALSE_WORDS)
        and not words <= {"0", "1"}
        and all(not isinstance(v, (int, float)) for v in values)
    ):
        return "boolean"
    return "text"


def _column_samples(rows: list[list[Any]], index: int) -> list[Any]:
    return [r[index] for r in rows if index < len(r)]


def _header_title(raw: Any, index: int) -> str:
    text = str(raw if raw is not None else "").strip()
    return text or f"Колонка {index + 1}"


def describe_file(filename: str, content: bytes) -> ImportFileColumns:
    """Колонки файла с примерами значений и подсказанным типом."""
    header, rows = _read(filename, content)
    columns = []
    for index, raw in enumerate(header):
        column_values = _column_samples(rows, index)
        columns.append(
            ImportFileColumn(
                index=index,
                header=_header_title(raw, index),
                samples=[_cell_text(v) for v in column_values if not _is_empty(v)][:3],
                suggested_type=infer_type(column_values),
            )
        )
    return ImportFileColumns(columns=columns, total_rows=len(rows))


def _require_cells_limit(rows: int, columns: int) -> None:
    if rows * columns > MAX_IMPORT_CELLS:
        raise HTTPException(
            422,
            f"Слишком большой импорт: {rows} строк × {columns} колонок = {rows * columns} ячеек, "
            f"за один раз не больше {MAX_IMPORT_CELLS}. Загрузите файл частями или выберите меньше колонок",
        )


def _read(filename: str, content: bytes) -> tuple[list[Any], list[list[Any]]]:
    try:
        return read_table(filename, content)
    except ClientImportError as exc:
        raise HTTPException(422, str(exc)) from exc


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


@dataclass
class _Target:
    """Колонка, в которую пишем: описание плюс номер колонки файла."""

    index: int
    name: str
    data_type: str
    options: list[str] | None
    key: str = ""  # c<id> для существующей таблицы


class UserTableImportService:
    def __init__(self, table_service: UserCustomTableService, row_repo: UserCustomTableRowRepository):
        self.table_service = table_service
        self.row_repo = row_repo

    # ── общее: разбор строк файла по колонкам ────────────────────────────────
    @staticmethod
    def _parse_rows(
        rows: list[list[Any]], targets: list[_Target]
    ) -> tuple[list[tuple[int, list[Any]]], list[ImportIssue], list[ImportIssue]]:
        """Годные строки (номер строки файла, значения по порядку targets), ошибки и предупреждения."""
        valid: list[tuple[int, list[Any]]] = []
        errors: list[ImportIssue] = []
        warnings: list[ImportIssue] = []
        for offset, raw_row in enumerate(rows):
            number = offset + 2  # строка 1 — заголовки
            values: list[Any] = []
            for target in targets:
                raw = raw_row[target.index] if target.index < len(raw_row) else None
                value, warning = convert(target.data_type, target.options, raw)
                if warning:
                    warnings.append(ImportIssue(row=number, message=f"«{target.name}»: {warning}"))
                values.append(value)
            if all(v is None for v in values):
                errors.append(ImportIssue(row=number, message="в строке не осталось ни одного значения — пропущена"))
                continue
            valid.append((number, values))
        return valid, errors, warnings

    @staticmethod
    def _preview(valid: list[tuple[int, list[Any]]], targets: list[_Target]) -> list[ImportPreviewRow]:
        return [
            ImportPreviewRow(row=number, values={t.name: _json_value(v) for t, v in zip(targets, values, strict=True)})
            for number, values in valid[:PREVIEW_ROWS]
        ]

    @staticmethod
    def _cells(values: list[Any], column_ids: list[int], data_types: list[str]) -> list[UserCustomTableCellModel]:
        cells = []
        for value, column_id, data_type in zip(values, column_ids, data_types, strict=True):
            if value is None:
                continue  # пустое значение ячейкой не хранится
            cell = UserCustomTableCellModel(column_id=column_id)
            setattr(cell, CELL_VALUE_COLUMN_BY_TYPE[data_type], value)
            cells.append(cell)
        return cells

    async def _insert_rows(
        self,
        table_id: int,
        valid: list[tuple[int, list[Any]]],
        column_ids: list[int],
        data_types: list[str],
        user: UserModel,
    ) -> None:
        """Строки одним flush (чтобы получить id), затем их ячейки. Коммитит вызывающий."""
        session = self.row_repo.session
        new_rows = [UserCustomTableRowModel(table_id=table_id, created_by_id=user.id) for _ in valid]
        session.add_all(new_rows)
        await session.flush()
        for row, (_number, values) in zip(new_rows, valid, strict=True):
            for cell in self._cells(values, column_ids, data_types):
                cell.row_id = row.id
                session.add(cell)

    # ── импорт в существующую таблицу ────────────────────────────────────────
    async def describe_for_table(
        self, table_id: int, filename: str, content: bytes, user: UserModel
    ) -> ImportFileColumns:
        table = await self.table_service.get_table_for_row_edit(table_id, user)
        columns = await self.table_service.list_columns(table.id)
        described = describe_file(filename, content)
        used: set[int] = set()
        suggested: dict[str, int] = {}
        for column in columns:
            if column.data_type in LINK_COLUMN_TYPES:
                continue
            for file_column in described.columns:
                if file_column.index not in used and file_column.header.casefold() == column.name.casefold():
                    suggested[column.key] = file_column.index
                    used.add(file_column.index)
                    break
        described.table_columns = [
            ImportTargetColumn(
                key=c.key, name=c.name, data_type=c.data_type, importable=c.data_type not in LINK_COLUMN_TYPES
            )
            for c in columns
        ]
        described.suggested_mapping = suggested
        return described

    async def import_rows(
        self,
        table_id: int,
        *,
        filename: str,
        content: bytes,
        mapping: dict[str, int],
        user: UserModel,
        dry_run: bool = False,
    ) -> TableImportReport:
        table = await self.table_service.get_table_for_row_edit(table_id, user)
        columns = {c.key: c for c in await self.table_service.list_columns(table.id)}
        if not mapping:
            raise HTTPException(422, "Не выбрано ни одной колонки для импорта")
        if len(set(mapping.values())) != len(mapping):
            raise HTTPException(422, "Одна колонка файла выбрана для нескольких колонок таблицы")
        header, rows = _read(filename, content)

        targets: list[_Target] = []
        for key, index in mapping.items():
            column = columns.get(key)
            if column is None:
                raise HTTPException(422, f"Неизвестная колонка таблицы «{key}»")
            if column.data_type in LINK_COLUMN_TYPES:
                raise HTTPException(422, f"Колонку-связь «{column.name}» из файла заполнить нельзя")
            if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(header):
                raise HTTPException(422, "Выбрана колонка, которой нет в файле")
            targets.append(_Target(index, column.name, column.data_type, column.options, key))

        _require_cells_limit(len(rows), len(targets))
        valid, errors, warnings = self._parse_rows(rows, targets)
        report = TableImportReport(
            dry_run=dry_run,
            total_rows=len(rows),
            to_create=len(valid),
            errors=errors,
            warnings=warnings,
            preview=self._preview(valid, targets),
        )
        existing = await self.row_repo.count_rows(table.id)
        if existing + len(valid) > row_limits.MAX_ROWS_PER_TABLE:
            raise HTTPException(
                409,
                f"В таблице не больше {row_limits.MAX_ROWS_PER_TABLE} строк: сейчас {existing}, в файле {len(valid)}",
            )
        if dry_run or not valid:
            return report

        self.row_repo.set_audit_user(user.id)
        column_ids = [columns[t.key].id for t in targets]
        data_types = [t.data_type for t in targets]
        await self._insert_rows(table.id, valid, column_ids, data_types, user)
        await self.row_repo.session.commit()  # одна транзакция: либо все строки, либо ни одной
        report.created = len(valid)
        await logger.ainfo("user_table_imported", table_id=table.id, user_id=user.id, created=report.created)
        return report

    # ── создание таблицы из файла ────────────────────────────────────────────
    def _targets_from_file(
        self, header: list[Any], rows: list[list[Any]], specs: list[TableImportColumnSpec] | None
    ) -> list[_Target]:
        if specs is None:
            if len(header) > MAX_COLUMNS_PER_TABLE:
                raise HTTPException(
                    422, f"В файле {len(header)} колонок, в таблице не больше {MAX_COLUMNS_PER_TABLE}: выберите нужные"
                )
            specs = [
                TableImportColumnSpec(index=i, data_type=infer_type(_column_samples(rows, i)))
                for i in range(len(header))
            ]
        if not specs:
            raise HTTPException(422, "Не выбрано ни одной колонки")
        if len(specs) > MAX_COLUMNS_PER_TABLE:
            raise HTTPException(422, f"В таблице не больше {MAX_COLUMNS_PER_TABLE} колонок")
        if len({s.index for s in specs}) != len(specs):
            raise HTTPException(422, "Одна колонка файла выбрана несколько раз")

        targets: list[_Target] = []
        taken: set[str] = set()
        for spec in specs:
            if spec.index >= len(header):
                raise HTTPException(422, "Выбрана колонка, которой нет в файле")
            if spec.data_type not in IMPORT_TYPES:
                raise HTTPException(422, "Из файла заполняются колонки text, number, date, boolean и select")
            name = (spec.name or _header_title(header[spec.index], spec.index)).strip()
            base, suffix = name, 2
            while name.casefold() in taken:  # одинаковые заголовки в файле получают номера: «Имя», «Имя (2)»
                name, suffix = f"{base} ({suffix})", suffix + 1
            taken.add(name.casefold())
            try:
                column = UserTableColumnCreate(name=name, data_type=spec.data_type, options=spec.options)  # type: ignore[arg-type]
            except ValueError as exc:
                raise HTTPException(422, f"Колонка «{name}»: {exc}") from exc
            targets.append(_Target(spec.index, column.name, column.data_type, column.options))
        return targets

    async def create_from_file(
        self,
        *,
        filename: str,
        content: bytes,
        name: str,
        visibility: str,
        specs: list[TableImportColumnSpec] | None,
        user: UserModel,
        dry_run: bool = False,
    ) -> TableImportReport:
        try:
            UserTableCreate(name=name, visibility=visibility)  # type: ignore[arg-type]
        except ValueError as exc:
            raise HTTPException(422, f"Название или видимость таблицы не подходят: {exc}") from exc
        header, rows = _read(filename, content)
        targets = self._targets_from_file(header, rows, specs)
        _require_cells_limit(len(rows), len(targets))
        valid, errors, warnings = self._parse_rows(rows, targets)
        report = TableImportReport(
            dry_run=dry_run,
            total_rows=len(rows),
            to_create=len(valid),
            errors=errors,
            warnings=warnings,
            preview=self._preview(valid, targets),
        )
        if await self.table_service.repo.count_tables() >= table_limits.MAX_TABLES_PER_WORKSPACE:
            raise HTTPException(
                409, f"В компании не больше {table_limits.MAX_TABLES_PER_WORKSPACE} самостоятельных таблиц"
            )
        if len(valid) > row_limits.MAX_ROWS_PER_TABLE:
            raise HTTPException(409, f"В таблице не больше {row_limits.MAX_ROWS_PER_TABLE} строк")
        if dry_run:
            return report
        if not valid:
            raise HTTPException(422, "В файле нет строк с данными: таблица не создана")

        self.row_repo.set_audit_user(user.id)
        session = self.row_repo.session
        data = UserTableCreate(name=name, visibility=visibility)  # type: ignore[arg-type]
        table = UserCustomTableModel(name=data.name, visibility=data.visibility, owner_id=user.id)
        session.add(table)
        await session.flush()
        columns = [
            UserCustomTableColumnModel(
                table_id=table.id, name=t.name, data_type=t.data_type, options=t.options, position=i
            )
            for i, t in enumerate(targets)
        ]
        session.add_all(columns)
        await session.flush()
        column_ids = [c.id for c in columns]
        data_types = [t.data_type for t in targets]
        await self._insert_rows(table.id, valid, column_ids, data_types, user)
        await session.commit()
        await session.refresh(table)
        report.created = len(valid)
        report.table = await self.table_service.get_table(table.id, user)
        await logger.ainfo("user_table_created_from_file", table_id=table.id, user_id=user.id, rows=report.created)
        return report
