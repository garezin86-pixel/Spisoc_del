# src/routers/notifications_router.py
from fastapi import APIRouter, Depends, HTTPException

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.other_repositories import NotificationRepository
from src.schemas.notification import NotificationItem, UnreadCount
from src.schemas.pagination import PaginatedResponse, PaginationParams
from src.utils.html_strip import strip_html

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _to_item(log) -> NotificationItem:
    return NotificationItem(
        id=log.id,
        notification_type=log.notification_type,
        task_id=log.task_id,
        task_title=log.task.title if log.task else None,
        content=strip_html(log.content),
        sent_at=log.sent_at,
        is_read=log.is_read,
        success=log.success,
    )


@router.get(
    "",
    response_model=PaginatedResponse[NotificationItem],
    summary="Список уведомлений текущего пользователя (для колокольчика)",
)
async def list_notifications(
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
):
    repo = NotificationRepository(session)
    logs, total = await repo.get_for_user(current_user.id, offset=pagination.offset, limit=pagination.size)
    items = [_to_item(log) for log in logs]
    return PaginatedResponse.create(items=items, total=total, page=pagination.page, size=pagination.size)


@router.get(
    "/unread-count",
    response_model=UnreadCount,
    summary="Количество непрочитанных уведомлений — для бейджа на колокольчике",
)
async def get_unread_count(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    repo = NotificationRepository(session)
    count = await repo.count_unread(current_user.id)
    return UnreadCount(count=count)


@router.post(
    "/{notification_id}/read",
    summary="Отметить одно уведомление прочитанным",
)
async def mark_notification_read(
    notification_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    repo = NotificationRepository(session)
    ok = await repo.mark_read(notification_id, current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    return {"ok": True}


@router.post(
    "/read-all",
    summary="Отметить все уведомления прочитанными",
)
async def mark_all_notifications_read(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    repo = NotificationRepository(session)
    count = await repo.mark_all_read(current_user.id)
    return {"marked": count}
