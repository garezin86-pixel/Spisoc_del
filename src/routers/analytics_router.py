# src/routers/analytics_router.py
from fastapi import APIRouter, Depends

from src.core.dependencies import get_current_user
from src.core.exceptions import no_access
from src.db import SessionDep
from src.models.user import UserModel, UserRole
from src.repositories.task_repository import TaskRepository
from src.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get(
    "/dashboard",
    summary="Аналитика для менеджера: закрытие задач в срок по исполнителям и проектам",
)
async def get_analytics_dashboard(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    if current_user.role not in (UserRole.admin, UserRole.manager):
        no_access("Аналитика доступна только admin/manager")

    service = AnalyticsService(TaskRepository(session))
    return await service.get_dashboard()
