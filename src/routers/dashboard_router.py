# src/routers/dashboard_router.py
from typing import Optional

from fastapi import APIRouter, Depends, Query

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.client_repository import ClientRepository
from src.repositories.dashboard_repository import DashboardRepository
from src.repositories.deal_repository import DealRepository
from src.repositories.users_repository import UserRepository
from src.schemas.dashboard import DashboardSchema
from src.services.dashboard_service import DashboardService
from src.services.deal_service import DealService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def get_dashboard_service(session: SessionDep) -> DashboardService:
    user_repo = UserRepository(session)
    deal_service = DealService(DealRepository(session), ClientRepository(session), user_repo)
    return DashboardService(DashboardRepository(session), deal_service, user_repo)


@router.get(
    "",
    response_model=DashboardSchema,
    summary="Дашборд: что делать сегодня",
    description="Задачи на сегодня и просроченные, клиенты без контакта дольше `stale_days` дней, ближайшие встречи "
    "и звонки (`events_days` дней вперёд), воронка ответственного по стадиям (суммы по валютам). "
    "«Сегодня» считается в часовом поясе `tz` (IANA, например Europe/Kyiv). "
    "Чужой дашборд (`user_id`) — только admin и manager.",
    responses={403: {"description": "Чужой дашборд"}, 404: {"description": "Пользователь не найден"}},
)
async def get_dashboard(
    session: SessionDep,
    user_id: Optional[int] = None,
    tz: str = Query("UTC", max_length=64),
    stale_days: int = Query(14, ge=1, le=365),
    events_days: int = Query(7, ge=1, le=60),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_dashboard_service(session).get_dashboard(
        current_user, user_id=user_id, tz=tz, stale_days=stale_days, events_days=events_days
    )
