# src/routers/deal_router.py
from fastapi import APIRouter, Depends, Query

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.routers.pipeline_router import get_deal_service
from src.schemas.deal import DealCreate, DealMove, DealSchema, DealStageChange, DealUpdate
from src.schemas.pagination import PaginatedResponse, PaginationParams

router = APIRouter(tags=["Deals"])


def _page(items, total, pagination: PaginationParams):
    return PaginatedResponse.create(
        items=[DealSchema.model_validate(d) for d in items],
        total=total,
        page=pagination.page,
        size=pagination.size,
    )


@router.get(
    "/deals",
    response_model=PaginatedResponse[DealSchema],
    summary="Сделки компании",
    description="Читать могут все. Фильтры: `stage_id`, `owner_id`, `client_id`. "
    "Новые сверху; с `stage_id` — в порядке карточек колонки.",
)
async def list_deals(
    session: SessionDep,
    stage_id: int | None = Query(None),
    owner_id: int | None = Query(None),
    client_id: int | None = Query(None),
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
):
    items, total = await get_deal_service(session).list_deals(
        pagination.offset, pagination.size, client_id=client_id, stage_id=stage_id, owner_id=owner_id
    )
    return _page(items, total, pagination)


@router.get(
    "/clients/{client_id}/deals",
    response_model=PaginatedResponse[DealSchema],
    summary="Сделки клиента",
    responses={404: {"description": "Клиент не найден"}},
)
async def list_client_deals(
    client_id: int,
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
):
    items, total = await get_deal_service(session).list_deals(pagination.offset, pagination.size, client_id=client_id)
    return _page(items, total, pagination)


@router.post(
    "/clients/{client_id}/deals",
    response_model=DealSchema,
    status_code=201,
    summary="Создать сделку клиента",
    description="Создаётся в первой открытой стадии (или в `stage_id`, если она открытая). "
    "**Требует роль admin/manager или быть ответственным за клиента.** "
    "Другого ответственного (`owner_id`) назначает только admin/manager.",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Клиент не найден"}},
)
async def create_deal(
    client_id: int,
    data: DealCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_deal_service(session).create_deal(client_id, data, current_user)


@router.get(
    "/deals/{deal_id}",
    response_model=DealSchema,
    summary="Получить сделку",
    responses={404: {"description": "Сделка не найдена"}},
)
async def get_deal(deal_id: int, session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    return await get_deal_service(session).get_deal(deal_id)


@router.patch(
    "/deals/{deal_id}",
    response_model=DealSchema,
    summary="Обновить сделку",
    description="Справочные поля (`title`, `notes`): ответственный, admin, manager. "
    "Процессные (`amount`, `owner_id`, `expected_close_date`): только admin и manager. "
    "Стадию меняет `POST /deals/{id}/move`.",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Не найдено"}},
)
async def update_deal(
    deal_id: int,
    data: DealUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_deal_service(session).update_deal(deal_id, data, current_user)


@router.patch(
    "/deals/{deal_id}/stage",
    response_model=DealSchema,
    summary="Перевести сделку на другую стадию",
    description="Ответственный по сделке, admin, manager. Стадия `lost` требует `lost_reason`, `won` — суммы "
    "сделки; закрытие ставит `closed_at`. Вернуть закрытую сделку в работу могут только admin и manager. "
    "`position` — место в целевой колонке (с нуля, остальные сдвигаются; не передана — в конец); "
    "тот же `stage_id` с `position` переставляет карточку внутри колонки.",
    responses={
        403: {"description": "Нет прав"},
        404: {"description": "Сделка или стадия не найдена"},
        422: {"description": "Нет причины проигрыша или суммы"},
    },
)
async def move_deal(
    deal_id: int,
    data: DealMove,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_deal_service(session).move_deal(deal_id, data, current_user)


@router.get(
    "/deals/{deal_id}/history",
    response_model=list[DealStageChange],
    summary="История смены стадий сделки",
    description="От старых к новым: кто, когда и из какой стадии в какую перевёл. Читать могут все.",
    responses={404: {"description": "Сделка не найдена"}},
)
async def get_deal_history(deal_id: int, session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    return await get_deal_service(session).get_history(deal_id)


@router.delete(
    "/deals/{deal_id}",
    response_model=dict,
    summary="Удалить сделку",
    description="Мягкое удаление. **Требует роль admin или manager.**",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Не найдено"}},
)
async def delete_deal(deal_id: int, session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    return await get_deal_service(session).delete_deal(deal_id, current_user)
