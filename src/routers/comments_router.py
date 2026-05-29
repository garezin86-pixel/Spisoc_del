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


@router.post("/tasks/{task_id}/comment", response_model=CommentResponse)
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
    "/tasks/{task_id}/comments", response_model=PaginatedResponse[CommentResponse]
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
