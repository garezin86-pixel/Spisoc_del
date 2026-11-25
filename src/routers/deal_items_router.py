# src/routers/deal_items_router.py
"""Оборудование сделки (Smart Tables, этап 2): строки «название + цена» внутри сделки."""

from fastapi import APIRouter, Depends, Query

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.deal_item_repository import DealItemRepository
from src.repositories.deal_repository import DealRepository
from src.schemas.deal_item import DealItemCreate, DealItemSchema, DealItemUpdate
from src.services.deal_item_service import DealItemService

router = APIRouter(tags=["Deal items"])


def get_deal_item_service(session: SessionDep) -> DealItemService:
    return DealItemService(DealItemRepository(session), DealRepository(session))


@router.get(
    "/deal-items/suggest",
    response_model=list[str],
    summary="Подсказка названий оборудования",
    description="Ранее введённые в компании названия оборудования (самые частые сверху, до 10). "
    "`q` — часть названия; без `q` — самые частые. Нужна для автодополнения, чтобы не плодить разные написания.",
)
async def suggest_names(
    session: SessionDep,
    q: str = Query("", max_length=100),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_deal_item_service(session).suggest_names(q)


@router.get(
    "/deals/{deal_id}/items",
    response_model=list[DealItemSchema],
    summary="Оборудование сделки",
    description="Строки оборудования сделки в порядке добавления. Читать могут все.",
    responses={404: {"description": "Сделка не найдена"}},
)
async def list_items(
    deal_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_deal_item_service(session).list_items(deal_id)


@router.post(
    "/deals/{deal_id}/items",
    response_model=DealItemSchema,
    status_code=201,
    summary="Добавить оборудование в сделку",
    description="Одна строка — одно оборудование: название (текст) и цена (вручную, можно не указывать). "
    "Валюта строки — валюта сделки; цена не меняет сумму сделки. Добавлять может ответственный за сделку, "
    "admin и manager; в закрытой сделке (Успех/Отказ) — только admin и manager. До 100 позиций в сделке.",
    responses={
        403: {"description": "Нет прав на правку этой сделки"},
        404: {"description": "Сделка не найдена"},
        409: {"description": "Достигнут лимит позиций"},
    },
)
async def create_item(
    deal_id: int,
    data: DealItemCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_deal_item_service(session).create_item(deal_id, data, current_user)


@router.patch(
    "/deals/{deal_id}/items/{item_id}",
    response_model=DealItemSchema,
    summary="Изменить оборудование сделки",
    description="Меняются только переданные поля; `price: null` очищает цену. Права — как при добавлении.",
    responses={
        403: {"description": "Нет прав на правку этой сделки"},
        404: {"description": "Сделка или позиция не найдены"},
    },
)
async def update_item(
    deal_id: int,
    item_id: int,
    data: DealItemUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_deal_item_service(session).update_item(deal_id, item_id, data, current_user)


@router.delete(
    "/deals/{deal_id}/items/{item_id}",
    summary="Удалить оборудование из сделки",
    description="Мягкое удаление (запись остаётся в аудите). Права — как при добавлении.",
    responses={
        403: {"description": "Нет прав на правку этой сделки"},
        404: {"description": "Сделка или позиция не найдены"},
    },
)
async def delete_item(
    deal_id: int,
    item_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_deal_item_service(session).delete_item(deal_id, item_id, current_user)
