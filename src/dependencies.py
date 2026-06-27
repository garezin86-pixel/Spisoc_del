"""
Фабрики зависимостей для FastAPI-роутеров.

В роутере вместо:
    repo = UserRepository(session)
    result = await some_function(repo, ...)

Пишем:
    service: UserService = Depends(get_user_service)
    result = await service.get_users()
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.redis import get_redis
from src.db import get_session
from src.repositories.groups_repository import GroupRepository
from src.repositories.other_repositories import (
    CommentRepository,
    NotificationRepository,
    StatsRepository,
)
from src.repositories.task_repository import TaskRepository
from src.repositories.users_repository import UserRepository
from src.services.auth_service import AuthService
from src.services.comments_service import CommentService
from src.services.group_service import GroupService
from src.services.task_service import TaskService
from src.services.user_service import UserService

# ── Репозитории ──────────────────────────────────────────────────────────────


def get_user_repo(session: AsyncSession = Depends(get_session)) -> UserRepository:
    return UserRepository(session)


def get_task_repo(session: AsyncSession = Depends(get_session)) -> TaskRepository:
    return TaskRepository(session)


def get_group_repo(session: AsyncSession = Depends(get_session)) -> GroupRepository:
    return GroupRepository(session)


def get_comment_repo(session: AsyncSession = Depends(get_session)) -> CommentRepository:
    return CommentRepository(session)


def get_notification_repo(
    session: AsyncSession = Depends(get_session),
) -> NotificationRepository:
    return NotificationRepository(session)


def get_stats_repo(session: AsyncSession = Depends(get_session)) -> StatsRepository:
    return StatsRepository(session)


# ── Сервисы ──────────────────────────────────────────────────────────────────


def get_auth_service(
    user_repo: UserRepository = Depends(get_user_repo),
) -> AuthService:
    redis = get_redis()
    return AuthService(user_repo, redis)


def get_user_service(
    user_repo: UserRepository = Depends(get_user_repo),
) -> UserService:
    return UserService(user_repo)


def get_task_service(
    task_repo: TaskRepository = Depends(get_task_repo),
    user_repo: UserRepository = Depends(get_user_repo),
    group_repo: GroupRepository = Depends(get_group_repo),
    session: AsyncSession = Depends(get_session),
) -> TaskService:
    return TaskService(task_repo, user_repo, group_repo, session)


def get_group_service(
    group_repo: GroupRepository = Depends(get_group_repo),
    user_repo: UserRepository = Depends(get_user_repo),
) -> GroupService:
    return GroupService(group_repo, user_repo)


def get_comment_service(
    task_repo: TaskRepository = Depends(get_task_repo),
    comment_repo: CommentRepository = Depends(get_comment_repo),
) -> CommentService:
    return CommentService(task_repo, comment_repo)
