# src/routers/analytics_router.py
from fastapi import APIRouter, Depends, Query

from src.core.dependencies import get_current_user
from src.core.exceptions import no_access
from src.db import SessionDep
from src.models.user import UserModel, UserRole
from src.repositories.audit_repository import AuditRepository
from src.repositories.task_repository import TaskRepository
from src.schemas.activity import ActivityFeedItem
from src.schemas.pagination import PaginatedResponse, PaginationParams
from src.services.activity_service import ActivityService
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


@router.get(
    "/activity",
    response_model=PaginatedResponse[ActivityFeedItem],
    summary="Глобальная лента активности (Timeline) — последние изменения задач и комментариев",
)
async def get_activity_feed(
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
    user_id: int | None = Query(
        None,
        description="Сузить ленту до событий конкретного пользователя (страница профиля)",
    ),
):
    service = ActivityService(AuditRepository(session), session)
    items, total = await service.get_feed(offset=pagination.offset, limit=pagination.size, user_id=user_id)
    return PaginatedResponse.create(items=items, total=total, page=pagination.page, size=pagination.size)
