# src/routers/scheduled_event_router.py
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.scheduled_event import EventStatus
from src.models.user import UserModel
from src.repositories.client_repository import ClientRepository
from src.repositories.scheduled_event_repository import ScheduledEventRepository
from src.repositories.users_repository import UserRepository
from src.schemas.pagination import PaginatedResponse, PaginationParams
from src.schemas.scheduled_event import EventComplete, EventCreate, EventSchema, EventUpdate
from src.services.scheduled_event_service import ScheduledEventService

client_events_router = APIRouter(prefix="/clients/{client_id}/events", tags=["Scheduled events"])
events_router = APIRouter(prefix="/events", tags=["Scheduled events"])


def get_event_service(session: SessionDep) -> ScheduledEventService:
    return ScheduledEventService(ClientRepository(session), ScheduledEventRepository(session), UserRepository(session))


def _page(items, total: int, page: int, size: int) -> PaginatedResponse[EventSchema]:
    return PaginatedResponse.create(
        items=[EventSchema.model_validate(i) for i in items], total=total, page=page, size=size
    )


# ── события клиента ──────────────────────────────────────────────────────────
@client_events_router.get(
    "",
    response_model=PaginatedResponse[EventSchema],
    summary="Запланированные события клиента",
    description="По возрастанию времени. Без `status` отменённые не возвращаются. "
    "Читать могут все пользователи компании.",
    responses={404: {"description": "Клиент не найден"}},
)
async def list_client_events(
    client_id: int,
    session: SessionDep,
    status: Optional[EventStatus] = None,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
):
    items, total = await get_event_service(session).list_events(
        offset=pagination.offset, limit=pagination.size, client_id=client_id, status=status
    )
    return _page(items, total, pagination.page, pagination.size)


@client_events_router.post(
    "",
    response_model=EventSchema,
    status_code=201,
    summary="Запланировать встречу или звонок",
    description="Тип: call, meeting. Ответственный за событие по умолчанию — вы. "
    "**Требует роль admin/manager или быть ответственным за клиента.**",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Клиент, контакт или сотрудник не найден"}},
)
async def create_event(
    client_id: int,
    data: EventCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_event_service(session).create(client_id, data, current_user)


# ── события компании (календарь, дашборд) ────────────────────────────────────
@events_router.get(
    "",
    response_model=PaginatedResponse[EventSchema],
    summary="События за период",
    description="Для календаря и дашборда. `from` включительно, `to` не включительно. "
    "Без `status` отменённые не возвращаются.",
)
async def list_events(
    session: SessionDep,
    date_from: Optional[datetime] = Query(None, alias="from"),
    date_to: Optional[datetime] = Query(None, alias="to"),
    assignee_id: Optional[int] = None,
    status: Optional[EventStatus] = None,
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    current_user: UserModel = Depends(get_current_user),
):
    items, total = await get_event_service(session).list_events(
        offset=(page - 1) * size,
        limit=size,
        assignee_id=assignee_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
    )
    return _page(items, total, page, size)


@events_router.patch(
    "/{event_id}",
    response_model=EventSchema,
    summary="Изменить событие",
    description="Время, длительность, ответственный, текст, статус (planned/cancelled). "
    "**Требует роль admin/manager или быть ответственным за событие.** Состоявшееся событие не меняется (409).",
    responses={
        403: {"description": "Нет прав"},
        404: {"description": "Не найдено"},
        409: {"description": "Уже состоялось"},
    },
)
async def update_event(
    event_id: int,
    data: EventUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_event_service(session).update(event_id, data, current_user)


@events_router.post(
    "/{event_id}/complete",
    response_model=EventSchema,
    summary="Отметить событие состоявшимся",
    description="В одной транзакции ставит статус done и создаёт взаимодействие того же типа с текущим временем "
    "(`summary` — из тела запроса, иначе заметки события). "
    "**Требует роль admin/manager или быть ответственным за событие.**",
    responses={
        403: {"description": "Нет прав"},
        404: {"description": "Не найдено"},
        409: {"description": "Уже состоялось или отменено"},
    },
)
async def complete_event(
    event_id: int,
    session: SessionDep,
    data: EventComplete = EventComplete(),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_event_service(session).complete(event_id, data, current_user)


@events_router.delete(
    "/{event_id}",
    response_model=dict,
    summary="Удалить событие",
    description="Мягкое удаление. **Требует роль admin или manager.**",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Не найдено"}},
)
async def delete_event(
    event_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_event_service(session).delete(event_id, current_user)
