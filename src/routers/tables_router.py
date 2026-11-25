# src/routers/tables_router.py
"""Smart Tables (Этап 1): таблицы как живые запросы к данным CRM. Только чтение.

Запросы — GET (а не POST), чтобы read-only токены (PAT) тоже могли читать таблицы: мутирующими считаются
только POST/PUT/PATCH/DELETE. Фильтры и сортировка передаются JSON-строкой в query-параметре.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import TypeAdapter, ValidationError

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.table_repository import TableRepository
from src.schemas.tables import SourceSchema, TableFilter, TableMetaSchema, TableRowsSchema, TableSort
from src.services.table_query_service import TableQueryService

router = APIRouter(prefix="/tables", tags=["Tables"])

_FILTERS = TypeAdapter(list[TableFilter])
_SORTS = TypeAdapter(list[TableSort])


def get_table_service(session: SessionDep) -> TableQueryService:
    return TableQueryService(TableRepository(session))


def _parse_json_list(raw: str | None, adapter: TypeAdapter, name: str) -> list:
    if not raw:
        return []
    try:
        return adapter.validate_python(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(422, f"Параметр «{name}» должен быть корректным JSON-списком") from exc


@router.get(
    "",
    response_model=list[SourceSchema],
    summary="Источники таблиц",
    description="Список источников данных, из которых можно собирать таблицы: клиенты, сделки, оборудование и "
    "самостоятельные таблицы пользователей (`uct_<id>`), которые видит пользователь.",
)
async def list_sources(
    service: TableQueryService = Depends(get_table_service),
    current_user: UserModel = Depends(get_current_user),
):
    return await service.list_sources(current_user)


@router.get(
    "/{source}/meta",
    response_model=TableMetaSchema,
    summary="Колонки источника",
    description="Колонки источника: тип, допустимые операции фильтра, значения списков, можно ли править ячейку. "
    "Интерфейс строит по этому описанию выбор колонок и фильтров.",
    responses={404: {"description": "Источник не найден"}},
)
async def table_meta(
    source: str,
    service: TableQueryService = Depends(get_table_service),
    current_user: UserModel = Depends(get_current_user),
):
    return await service.meta(source, current_user)


@router.get(
    "/{source}/rows",
    response_model=TableRowsSchema,
    summary="Строки таблицы",
    description=(
        "Строки источника. `columns` — ключи колонок через запятую (по умолчанию набор источника). "
        '`filters` — JSON: `[{"field":"stage_kind","op":"eq","value":"won"}]`. '
        '`sort` — JSON: `[{"field":"amount","direction":"desc"}]`. '
        "Данные читаются из тех же таблиц, что и обычные списки CRM, и только своей компании. "
        "В каждой строке есть служебные `_id` и `_version` (updated_at)."
    ),
    responses={
        404: {"description": "Источник не найден"},
        422: {"description": "Неверная колонка, операция или значение"},
    },
)
async def table_rows(
    source: str,
    columns: str | None = Query(None, max_length=1000, description="Колонки через запятую"),
    filters: str | None = Query(None, max_length=10000, description="JSON-список условий"),
    sort: str | None = Query(None, max_length=1000, description="JSON-список ключей сортировки"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    service: TableQueryService = Depends(get_table_service),
    current_user: UserModel = Depends(get_current_user),
):
    keys = [c.strip() for c in columns.split(",") if c.strip()] if columns else None
    return await service.query(
        source,
        current_user,
        keys,
        _parse_json_list(filters, _FILTERS, "filters"),
        _parse_json_list(sort, _SORTS, "sort"),
        page,
        size,
    )
