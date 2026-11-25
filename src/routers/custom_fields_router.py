# src/routers/custom_fields_router.py
"""Свои поля клиентов и сделок (Smart Tables, этап 3)."""

from fastapi import APIRouter, Depends, Query

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.client_repository import ClientRepository
from src.repositories.custom_field_repository import CustomFieldRepository
from src.repositories.deal_repository import DealRepository
from src.schemas.custom_field import (
    CustomEntityType,
    CustomFieldCreate,
    CustomFieldSchema,
    CustomFieldUpdate,
    CustomValueSchema,
    CustomValueSet,
)
from src.services.custom_field_service import CustomFieldService

router = APIRouter(prefix="/custom-fields", tags=["Custom fields"])


def get_custom_field_service(session: SessionDep) -> CustomFieldService:
    return CustomFieldService(CustomFieldRepository(session), ClientRepository(session), DealRepository(session))


@router.get(
    "",
    response_model=list[CustomFieldSchema],
    summary="Свои поля",
    description="Свои поля компании в порядке отображения. `entity_type` (client | deal) — только поля этой сущности. "
    "Читать могут все.",
)
async def list_fields(
    session: SessionDep,
    entity_type: CustomEntityType | None = Query(None),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_custom_field_service(session).list_fields(entity_type)


@router.post(
    "",
    response_model=CustomFieldSchema,
    status_code=201,
    summary="Создать своё поле",
    description="Новая колонка для клиентов или сделок: text, number, date, select (со списком значений `options`) "
    "или boolean. Тип после создания не меняется. Название уникально в пределах сущности (без учёта регистра). "
    "До 30 полей на сущность. **Требует роль admin или manager.**",
    responses={
        403: {"description": "Требуется роль admin или manager"},
        409: {"description": "Поле с таким названием уже есть или достигнут лимит"},
    },
)
async def create_field(
    data: CustomFieldCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_custom_field_service(session).create_field(data, current_user)


@router.get(
    "/values",
    response_model=list[CustomValueSchema],
    summary="Значения полей записи",
    description="Заполненные значения своих полей клиента или сделки (пустые не возвращаются). Читать могут все.",
)
async def list_values(
    session: SessionDep,
    entity_type: CustomEntityType = Query(...),
    entity_id: int = Query(..., ge=1),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_custom_field_service(session).list_values(entity_type, entity_id)


@router.patch(
    "/{field_id}",
    response_model=CustomFieldSchema,
    summary="Изменить своё поле",
    description="Название, значения списка (только у select), порядок. Тип и сущность не меняются. "
    "Значения, которых уже нет в списке, остаются у записей как есть. **Требует роль admin или manager.**",
    responses={
        403: {"description": "Требуется роль admin или manager"},
        404: {"description": "Поле не найдено"},
        409: {"description": "Поле с таким названием уже есть"},
    },
)
async def update_field(
    field_id: int,
    data: CustomFieldUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_custom_field_service(session).update_field(field_id, data, current_user)


@router.delete(
    "/{field_id}",
    summary="Удалить своё поле",
    description="Мягкое удаление: колонка исчезает из таблиц, введённые значения остаются в базе. "
    "**Требует роль admin или manager.**",
    responses={403: {"description": "Требуется роль admin или manager"}, 404: {"description": "Поле не найдено"}},
)
async def delete_field(
    field_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_custom_field_service(session).delete_field(field_id, current_user)


@router.put(
    "/{field_id}/values/{entity_id}",
    response_model=CustomValueSchema,
    summary="Задать значение поля у записи",
    description="`value: null` (или пустая строка) очищает значение. Тип проверяется по типу поля: text и select — "
    "строка (select — из списка), number — число (до 4 знаков после запятой), date — «ГГГГ-ММ-ДД», boolean — "
    "true/false. Править могут те же, кто правит саму запись: ответственный, admin, manager.",
    responses={
        403: {"description": "Нет прав на правку этой записи"},
        404: {"description": "Поле или запись не найдены"},
        422: {"description": "Значение не подходит к типу поля"},
    },
)
async def set_value(
    field_id: int,
    entity_id: int,
    data: CustomValueSet,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_custom_field_service(session).set_value(field_id, entity_id, data.value, current_user)
