from fastapi import APIRouter, Depends, Request
from src.db import SessionDep
from src.models.user import UserModel
from src.schemas.comment import CommentCreate, CommentResponse
from src.core.dependencies import get_current_user
from src.core.limiter import limiter
from src.services.comments_service import CommentService
from src.repositories.task_repository import TaskRepository
from src.repositories.other_repositories import CommentRepository
from src.schemas.pagination import PaginationParams, PaginatedResponse

router = APIRouter(prefix="/comments", tags=["Comments"])


@router.post(
    "/tasks/{task_id}/comment",
    response_model=CommentResponse,
    summary="Добавить комментарий к задаче",
    description="""
Создаёт комментарий к задаче от имени текущего пользователя.

Доступ разрешён, если пользователь имеет право редактировать задачу:
является автором, исполнителем, членом группы или имеет роль admin/manager.

Защищён rate-limit: **20 запросов в минуту** с одного IP.

Side-effects:
- Отправляет Telegram-уведомление автору задачи и исполнителю о новом комментарии
  (кроме того, кто оставил комментарий).
""",
    responses={
        200: {
            "description": "Комментарий создан",
            "content": {
                "application/json": {
                    "example": {
                        "id": 10,
                        "content": "Сделано, проверяй",
                        "task_id": 42,
                        "user": {"id": 3, "username": "bob"},
                        "created_at": "05.06.2025 14:30",
                    }
                }
            },
        },
        403: {"description": "Нет доступа к задаче"},
        404: {"description": "Задача не найдена"},
        429: {"description": "Слишком много запросов"},
    },
)
@limiter.limit("20/minute")
async def create_comment(
    request: Request,
    task_id: int,
    data: CommentCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await CommentService(
        task_repo=TaskRepository(session),
        comment_repo=CommentRepository(session),
        session=session,
    ).add_comment(task_id, data, current_user)


@router.get(
    "/tasks/{task_id}/comments",
    response_model=PaginatedResponse[CommentResponse],
    summary="Список комментариев к задаче",
    description="""
Возвращает постраничный список комментариев к задаче в порядке убывания даты.

Доступ разрешён тем же правилам, что и при чтении задачи.
""",
    responses={
        200: {"description": "Список комментариев с метаданными пагинации"},
        403: {"description": "Нет доступа к задаче"},
        404: {"description": "Задача не найдена"},
    },
)
async def get_comment_task(
    task_id: int,
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
):
    service = CommentService(
        task_repo=TaskRepository(session),
        comment_repo=CommentRepository(session),
        session=session,
    )
    comments, total = await service.get_by_task_paginated(
        task_id=task_id,
        offset=pagination.offset,
        limit=pagination.size,
        user=current_user,
    )
    return PaginatedResponse.create(
        items=comments, total=total, page=pagination.page, size=pagination.size
    )
