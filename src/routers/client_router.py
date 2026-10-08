# src/routers/client_router.py
from fastapi import APIRouter, Depends, Query

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.client_repository import ClientRepository
from src.repositories.interaction_repository import InteractionRepository
from src.repositories.users_repository import UserRepository
from src.schemas.client import (
    ClientCreate,
    ClientDetailSchema,
    ClientSchema,
    ClientUpdate,
    ContactCreate,
    ContactSchema,
    ContactUpdate,
)
from src.schemas.pagination import PaginatedResponse, PaginationParams
from src.services.client_service import ClientService

router = APIRouter(prefix="/clients", tags=["Clients"])


def get_client_service(session: SessionDep) -> ClientService:
    return ClientService(ClientRepository(session), UserRepository(session))


@router.post(
    "",
    response_model=ClientSchema,
    status_code=201,
    summary="Создать клиента",
    description="Создаёт клиента. Ответственным становится создатель (или `owner_id`). "
    "**Требует роль admin или manager.**",
    responses={201: {"description": "Клиент создан"}, 403: {"description": "Требуется роль admin или manager"}},
)
async def create_client(
    data: ClientCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).create_client(data, current_user)


@router.get(
    "",
    response_model=PaginatedResponse[ClientSchema],
    summary="Список клиентов",
    description="Клиенты компании. Читать могут все. "
    "Поиск `search` — по названию, телефону и email (без учёта регистра).",
)
async def get_clients(
    session: SessionDep,
    search: str | None = Query(None, max_length=100, description="Поиск по названию, телефону, email"),
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
):
    clients, total = await get_client_service(session).get_clients(
        search, offset=pagination.offset, limit=pagination.size
    )
    items = [ClientSchema.model_validate(c) for c in clients]
    return PaginatedResponse.create(items=items, total=total, page=pagination.page, size=pagination.size)


@router.get(
    "/{client_id}",
    response_model=ClientDetailSchema,
    summary="Получить клиента",
    responses={404: {"description": "Клиент не найден"}},
)
async def get_client(
    client_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    client = await get_client_service(session).get_client(client_id)
    detail = ClientDetailSchema.model_validate(client)
    detail.last_interaction_at = await InteractionRepository(session).last_occurred_at(client_id)
    return detail


@router.patch(
    "/{client_id}",
    response_model=ClientSchema,
    summary="Обновить клиента",
    description="Меняются только переданные поля. **Требует роль admin/manager или быть ответственным за клиента.** "
    "Менять `owner_id` могут только admin и manager.",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Клиент не найден"}},
)
async def update_client(
    client_id: int,
    data: ClientUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).update_client(client_id, data, current_user)


@router.delete(
    "/{client_id}",
    response_model=dict,
    summary="Удалить клиента",
    description="Мягкое удаление клиента вместе с его контактами. **Требует роль admin или manager.**",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Клиент не найден"}},
)
async def delete_client(
    client_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).delete_client(client_id, current_user)


@router.get(
    "/{client_id}/contacts",
    response_model=list[ContactSchema],
    summary="Контакты клиента",
    responses={404: {"description": "Клиент не найден"}},
)
async def get_contacts(
    client_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).get_contacts(client_id)


@router.post(
    "/{client_id}/contacts",
    response_model=ContactSchema,
    status_code=201,
    summary="Добавить контакт клиенту",
    description="**Требует роль admin/manager или быть ответственным за клиента.**",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Клиент не найден"}},
)
async def create_contact(
    client_id: int,
    data: ContactCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).create_contact(client_id, data, current_user)


@router.patch(
    "/{client_id}/contacts/{contact_id}",
    response_model=ContactSchema,
    summary="Обновить контакт",
    description="**Требует роль admin/manager или быть ответственным за клиента.**",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Клиент или контакт не найден"}},
)
async def update_contact(
    client_id: int,
    contact_id: int,
    data: ContactUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).update_contact(client_id, contact_id, data, current_user)


@router.delete(
    "/{client_id}/contacts/{contact_id}",
    response_model=dict,
    summary="Удалить контакт",
    description="Мягкое удаление. **Требует роль admin/manager или быть ответственным за клиента.**",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Клиент или контакт не найден"}},
)
async def delete_contact(
    client_id: int,
    contact_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).delete_contact(client_id, contact_id, current_user)
