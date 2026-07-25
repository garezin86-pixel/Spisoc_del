"""
Mock-репозитории для тестов.
Хранят данные в памяти — никакой БД не нужно.
"""

from collections import namedtuple

from src.models.comment import CommentModel
from src.models.group import GroupModel
from src.models.tag import TagModel
from src.models.task import SpisokModel, TaskStatus
from src.models.user import UserModel
from src.repositories.abstract.base_group_repository import AbstractGroupRepository
from src.repositories.abstract.base_other_repositories import (
    AbstractCommentRepository,
    AbstractNotificationRepository,
    AbstractStatsRepository,
)
from src.repositories.abstract.base_task_repository import AbstractTaskRepository
from src.repositories.abstract.base_user_repository import AbstractUserRepository
from src.schemas.stats import TasksStats as _TasksStats
from src.schemas.stats import UsersStats as _UsersStats

# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class MockUserRepository(AbstractUserRepository):
    def __init__(self, users: list[UserModel] | None = None):
        self._users: list[UserModel] = users or []
        self._next_id = max((u.id for u in self._users), default=0) + 1

    async def get_all(self) -> list[UserModel]:
        return list(self._users)

    async def get_by_id(self, user_id: int) -> UserModel | None:
        return next((u for u in self._users if u.id == user_id), None)

    async def get_user_id(self, user_id: int) -> UserModel | None:
        return await self.get_by_id(user_id)

    async def get_users_limit(self, limit: int, offset: int) -> list[UserModel]:
        return self._users[offset : offset + limit]

    async def create(self, user: UserModel) -> UserModel:
        user.id = self._next_id
        self._next_id += 1
        self._users.append(user)
        return user

    async def get_by_username(self, username: str) -> UserModel | None:
        return next((u for u in self._users if u.username == username), None)

    async def update(self, user: UserModel) -> UserModel:
        return user

    async def delete(self, user: UserModel) -> None:
        self._users = [u for u in self._users if u.id != user.id]

    async def get_by_telegram_id(self, telegram_id: int) -> UserModel | None:
        return next((u for u in self._users if u.telegram_id == telegram_id), None)

    async def set_role(self, username: str, role: str) -> None:
        user = await self.get_by_username(username)
        if user:
            user.role = role

    async def get_admin_by_username(self, username: str) -> UserModel | None:
        return next(
            (u for u in self._users if u.username == username and u.role == "admin"),
            None,
        )

    # === Новые обязательные методы из AbstractUserRepository ===
    async def execute_scalars(self, query):
        """Заглушка для моков — параметр должен называться query"""
        # Возвращаем всех пользователей или результат в зависимости от теста
        return self._users

    async def get_total_count(self, model) -> int:
        return len(self._users)

    async def select_user(self, stmt):
        """Возвращает первого пользователя (или None)"""
        return self._users[0] if self._users else None

    def select_users_offset_limit(self, offset: int, limit: int):
        """Должен возвращать Select, но в моках — список"""
        return self._users[offset : offset + limit]


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

TaskStats = namedtuple("TaskStats", ["total", "done", "backlog", "todo", "in_progress", "review"])
_CreatedStats = namedtuple("CreatedStats", ["total", "done"])


class MockTaskRepository(AbstractTaskRepository):
    def __init__(self, tasks: list[SpisokModel] | None = None):
        self._tasks: list[SpisokModel] = tasks or []
        self._comments: list[CommentModel] = []
        self._next_task_id = max((t.id for t in self._tasks), default=0) + 1
        self._next_comment_id = 1

    # === Основные методы ===
    async def get_all(self) -> list[SpisokModel]:
        return list(self._tasks)

    async def get_by_id(self, task_id: int) -> SpisokModel | None:
        return next((t for t in self._tasks if t.id == task_id), None)

    async def create(self, task: SpisokModel) -> SpisokModel:
        task.id = self._next_task_id
        self._next_task_id += 1
        self._tasks.append(task)
        return task

    async def delete(self, task: SpisokModel) -> None:
        self._tasks = [t for t in self._tasks if t.id != task.id]

    async def update(self, task: SpisokModel) -> SpisokModel:
        return task

    # === Новые методы пагинации ===
    async def filter_tasks_paginated_total(self, base_query, **kwargs) -> int:
        """Название параметра должно быть base_query!"""
        return len(self._tasks)

    async def filter_tasks_paginated(self, query, limit: int = 20, offset: int = 0, **kwargs):
        return self._tasks[offset : offset + limit]

    # Старые методы (для совместимости)
    async def get_tasks_limit(self, query, limit: int, offset: int) -> list[SpisokModel]:
        return self._tasks[offset : offset + limit]

    async def get_user_tasks(self, user_id: int) -> list[SpisokModel]:
        return [t for t in self._tasks if t.user_id == user_id]

    async def get_user_tasks_by_status(
        self,
        *,
        user_id: int,
        status: TaskStatus | None = None,
    ):
        tasks = [t for t in self._tasks if t.user_id == user_id]

        if status is not None:
            tasks = [t for t in tasks if t.status == status]

        return tasks

    # Остальные методы...
    async def get_assigned_tasks(self, pk: int):
        tasks = [t for t in self._tasks if t.user_id == pk]

        return TaskStats(
            total=len(tasks),
            done=len([t for t in tasks if t.status == TaskStatus.done]),
            backlog=len([t for t in tasks if t.status == TaskStatus.backlog]),
            todo=len([t for t in tasks if t.status == TaskStatus.todo]),
            in_progress=len([t for t in tasks if t.status == TaskStatus.in_progress]),
            review=len([t for t in tasks if t.status == TaskStatus.review]),
        )

    async def get_created_tasks_stats(self, pk: int):
        author_tasks = [t for t in self._tasks if t.author_id == pk]
        done = sum(1 for t in author_tasks if t.status and t.status.value == "done")
        return _CreatedStats(total=len(author_tasks), done=done)

    async def get_last_appointed_tasks(self, pk: int) -> list[SpisokModel]:
        user_tasks = [t for t in self._tasks if t.user_id == pk]
        return sorted(user_tasks, key=lambda t: getattr(t, "created_at", 0), reverse=True)[:10]

    async def add_comment(self, task_id: int, user_id: int, content: str) -> CommentModel:
        comment = CommentModel(
            id=self._next_comment_id,
            task_id=task_id,
            user_id=user_id,
            content=content,
        )
        self._next_comment_id += 1
        self._comments.append(comment)
        return comment

    async def get_filtered_tasks(
        self,
        *,
        user_id: int,
        offset: int,
        limit: int,
        filter_user_group=None,
        group_id: int | None = None,
        filter_type=None,
    ) -> list[SpisokModel]:
        return self._tasks[offset : offset + limit]

    async def get_filtered_tasks_total(
        self,
        *,
        user_id: int,
        filter_user_group=None,
        group_id: int | None = None,
        filter_type=None,
    ) -> int:
        return len(self._tasks)

    async def get_filtered_tasks_with_total(
        self,
        *,
        user_id: int,
        offset: int,
        limit: int,
        filter_user_group=None,
        group_id: int | None = None,
        project_id: int | None = None,
        filter_type=None,
        is_done: bool | None = None,
    ):
        return self._tasks[offset : offset + limit], len(self._tasks)

    async def get_tasks_for_reminder(self, start_time, end_time) -> list[SpisokModel]:
        return list(self._tasks)

    async def get_tasks_by_deadline_window(self, start, end, user_id: int | None = None) -> list[SpisokModel]:
        tasks = self._tasks
        if user_id is not None:
            tasks = [task for task in tasks if task.user_id == user_id]
        return list(tasks)

    async def get_overdue_tasks(self, now, user_id: int | None = None):
        tasks = self._tasks
        if user_id is not None:
            tasks = [task for task in tasks if task.user_id == user_id]
        return list(tasks)

    async def get_tasks_by_user(self, user_id: int):
        return await self.get_user_tasks(user_id)

    async def get_task(self, task_id: int):
        return await self.get_by_id(task_id)

    async def get_by_id_include_deleted(self, task_id: int) -> SpisokModel | None:
        return next((t for t in self._tasks if t.id == task_id), None)

    async def get_deleted_tasks_paginated(
        self,
        *,
        user_id: int,
        is_admin: bool,
        offset: int = 0,
        limit: int = 20,
        search: str | None = None,
    ) -> tuple[list[SpisokModel], int]:
        deleted = [t for t in self._tasks if getattr(t, "deleted_at", None) is not None]
        return deleted[offset : offset + limit], len(deleted)

    async def hard_delete(self, task: SpisokModel) -> None:
        self._tasks = [t for t in self._tasks if t.id != task.id]

    async def get_kanban_tasks(
        self,
        *,
        user_id: int,
        project_id: int | None = None,
        only_mine: bool = False,
        only_author: bool = False,
    ) -> list[SpisokModel]:
        tasks = self._tasks.copy()

        if project_id is not None:
            tasks = [t for t in tasks if t.project_id == project_id]

        if only_mine:
            tasks = [t for t in tasks if t.user_id == user_id]

        if only_author:
            tasks = [t for t in tasks if t.author_id == user_id]

        return tasks

    # === Экспорт и аналитика ===
    async def export_tasks(
        self,
        *,
        user_id: int,
        filter_user_group=None,
        group_id: int | None = None,
        project_id: int | None = None,
        status=None,
        priority: str | None = None,
        tag_id: int | None = None,
        deadline_from=None,
        deadline_to=None,
        max_rows: int = 10_000,
    ) -> list[SpisokModel]:
        """
        Упрощённая версия для юнит-тестов: без ролевой фильтрации
        (filter_user_group игнорируется — TaskExportService сам решает,
        передавать его или нет, это тестируется отдельно через реальный
        TaskRepository в tests/test_task_export.py, не через мок).
        """
        tasks = self._tasks.copy()

        if project_id is not None:
            tasks = [t for t in tasks if t.project_id == project_id]
        if status is not None:
            tasks = [t for t in tasks if t.status == status]
        if priority is not None:
            tasks = [t for t in tasks if getattr(t, "priority", None) == priority]
        if tag_id is not None:
            tasks = [
                t for t in tasks if any(getattr(tag, "id", None) == tag_id for tag in getattr(t, "tags", []) or [])
            ]
        if deadline_from is not None:
            tasks = [t for t in tasks if t.deadline and t.deadline >= deadline_from]
        if deadline_to is not None:
            tasks = [t for t in tasks if t.deadline and t.deadline <= deadline_to]

        return tasks[:max_rows]

    async def get_tasks_for_analytics(self) -> list[SpisokModel]:
        """
        Упрощённая версия для юнит-тестов: как и в реальном TaskRepository,
        отдаёт только задачи, у которых есть и deadline, и completed_at —
        сама агрегация считается в AnalyticsService, не здесь. Подробное
        тестирование расчётов — через реальный TaskRepository в
        tests/test_analytics_service.py, не через мок.
        """
        return [t for t in self._tasks if getattr(t, "deadline", None) and getattr(t, "completed_at", None)]

    # === Импорт CSV/Excel и массовые действия (bulk actions) ===
    async def bulk_create(self, tasks: list[SpisokModel]) -> list[SpisokModel]:
        for task in tasks:
            task.id = self._next_task_id
            self._next_task_id += 1
            self._tasks.append(task)
        return tasks

    async def get_by_ids(self, task_ids: list[int]) -> list[SpisokModel]:
        wanted = set(task_ids)
        return [t for t in self._tasks if t.id in wanted]

    async def bulk_update(self, tasks: list[SpisokModel]) -> list[SpisokModel]:
        """Как и update() — задачи в моке хранятся по ссылке и уже изменены
        к моменту вызова, поэтому реального персиста не требуется."""
        return tasks


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------


class MockGroupRepository(AbstractGroupRepository):
    def __init__(self, groups: list[GroupModel] | None = None):
        self._groups: list[GroupModel] = groups or []
        self._next_id = max((g.id for g in self._groups), default=0) + 1

    # === Основные методы ===
    async def get_all(self) -> list[GroupModel]:
        return list(self._groups)

    async def get_by_id(self, group_id: int) -> GroupModel | None:
        return next((g for g in self._groups if g.id == group_id), None)

    async def get_by_id_users_in_group(self, group_id: int) -> GroupModel | None:
        return await self.get_by_id(group_id)

    async def get_id_group_for_name(self, name: str) -> GroupModel | None:
        return next((g for g in self._groups if g.name == name), None)

    async def create(self, group: GroupModel) -> GroupModel:
        group.id = self._next_id
        self._next_id += 1
        if not hasattr(group, "users") or group.users is None:
            group.users = []
        self._groups.append(group)
        return group

    async def add_user_in_group(self, group: GroupModel, user: UserModel) -> UserModel:
        if not hasattr(group, "users") or group.users is None:
            group.users = []
        group.users.append(user)
        return user

    async def delete_user_group(self, group: GroupModel, user: UserModel) -> UserModel:
        if hasattr(group, "users") and group.users:
            group.users = [u for u in group.users if u.id != user.id]
        return user

    async def delete_group(self, group: GroupModel) -> GroupModel:
        self._groups = [g for g in self._groups if g.id != group.id]
        return group

    async def get_group_users(self, group_id: int) -> list[UserModel]:
        group = await self.get_by_id(group_id)
        return group.users if group and hasattr(group, "users") else []

    async def get_user_groups(self, user_id: int) -> list[GroupModel]:
        return [g for g in self._groups if hasattr(g, "users") and any(u.id == user_id for u in g.users)]

    # === Методы пагинации — ТОЧНО по сигнатуре Abstract ===
    async def get_groups_paginated_total(self, query):
        """query игнорируем в моках"""
        return len(self._groups)

    async def get_groups_offset_limit(self, query, offset: int, limit: int):
        """query игнорируем в моках"""
        return self._groups[offset : offset + limit]

    def get_groups_paginated_for_user(self, query, user_id: int):
        """Синхронный метод, возвращающий Select"""
        from sqlalchemy import select

        from src.models.group import GroupModel

        return select(GroupModel)  # dummy

    async def get_user_group(self, group_id):
        return await self.get_by_id(group_id)

    async def get_groups_paginated_for_access(
        self,
        *,
        user_id: int,
        unrestricted: bool,
        offset: int,
        limit: int,
    ):
        groups = self._groups
        if not unrestricted:
            groups = [
                group for group in groups if hasattr(group, "users") and any(user.id == user_id for user in group.users)
            ]
        return groups[offset : offset + limit], len(groups)

    async def get_group_users_with_telegram(self, group_id: int, exclude_user_id: int | None = None):
        users = await self.get_group_users(group_id)
        if exclude_user_id is not None:
            users = [user for user in users if user.id != exclude_user_id]
        return [user for user in users if getattr(user, "telegram_id", None)]


# ---------------------------------------------------------------------------
# Tag
# ---------------------------------------------------------------------------


class MockTagRepository:
    """Без Abstract-обёртки — реальный TagRepository (src/repositories/tag_repository.py)
    тоже без ABC, поэтому здесь не от кого наследоваться."""

    def __init__(self, tags: list[TagModel] | None = None):
        self._tags: list[TagModel] = tags or []
        self._next_tag_id = max((t.id for t in self._tags), default=0) + 1

    async def get_all(self) -> list[TagModel]:
        return list(self._tags)

    async def get_by_id(self, tag_id: int) -> TagModel | None:
        return next((t for t in self._tags if t.id == tag_id), None)

    async def get_by_ids(self, tag_ids: list[int]) -> list[TagModel]:
        wanted = set(tag_ids)
        return [t for t in self._tags if t.id in wanted]

    async def get_by_name(self, name: str) -> TagModel | None:
        target = name.lower()
        return next((t for t in self._tags if t.name.lower() == target), None)

    async def create(self, name: str, color: str) -> TagModel:
        tag = TagModel(id=self._next_tag_id, name=name, color=color)
        self._next_tag_id += 1
        self._tags.append(tag)
        return tag

    async def get_or_create(self, name: str, color: str) -> TagModel:
        existing = await self.get_by_name(name)
        if existing:
            return existing
        return await self.create(name, color)

    async def delete(self, tag: TagModel) -> None:
        self._tags = [t for t in self._tags if t.id != tag.id]


# ---------------------------------------------------------------------------
# Comment
# ---------------------------------------------------------------------------


class MockCommentRepository(AbstractCommentRepository):
    def __init__(self, comments: list[CommentModel] | None = None):
        self._comments: list[CommentModel] = comments or []
        self._next_id = max((c.id for c in self._comments), default=0) + 1

    async def create(self, comment: CommentModel) -> CommentModel:
        comment.id = self._next_id
        self._next_id += 1
        self._comments.append(comment)
        return comment

    async def get_by_task(self, task_id: int) -> list[CommentModel]:
        return [c for c in self._comments if c.task_id == task_id]

    async def select_query(self, task_id: int):
        return task_id

    async def get_total_tasks(self, query):
        return len([c for c in self._comments if c.task_id == query])

    async def get_by_task_offset_limit(self, query, offset, limit):
        comments = [c for c in self._comments if c.task_id == query]
        return comments[offset : offset + limit]


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------


class MockNotificationRepository(AbstractNotificationRepository):
    def __init__(
        self,
        comments: list[CommentModel] | None = None,
        tasks: list[SpisokModel] | None = None,
    ):
        self._comments: list[CommentModel] = comments or []
        self._tasks: list[SpisokModel] = tasks or []

    async def get_comment_with_relations(self, comment_id: int) -> CommentModel | None:
        return next((c for c in self._comments if c.id == comment_id), None)

    async def get_task_with_relations(self, task_id: int) -> SpisokModel | None:
        return next((t for t in self._tasks if t.id == task_id), None)

    async def create_log(
        self,
        user_id: int,
        notification_type: str,
        content: str,
        task_id: int | None = None,
        success: bool = True,
        error: str | None = None,
    ):
        return None

    async def check_already_sent(
        self,
        user_id: int,
        task_id: int | None,
        notification_type: str,
        hours_back: int | None = None,
    ) -> bool:
        return False

    async def get_admin_statistics(
        self,
        days: int = 7,
        top_users_limit: int = 10,
    ) -> dict:
        return {
            "total": 0,
            "total_success": 0,
            "type_stats": [],
            "daily_stats": [],
            "top_users": [],
        }


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

# _UsersStats = namedtuple("UsersStats", ["total_users", "active_users", "admin_users"])
# _TasksStats = namedtuple("TasksStats", ["total_tasks", "done_tasks", "pending_tasks"])


class MockStatsRepository(AbstractStatsRepository):
    def __init__(
        self,
        users: list[UserModel] | None = None,
        tasks: list[SpisokModel] | None = None,
        groups: list[GroupModel] | None = None,
        comments: list[CommentModel] | None = None,
    ):
        self._users = users or []
        self._tasks = tasks or []
        self._groups = groups or []
        self._comments = comments or []

    async def get_users_stats(self) -> _UsersStats:
        return _UsersStats(
            total_users=len(self._users),
            active_users=sum(1 for u in self._users if u.is_active),
            admin_users=sum(1 for u in self._users if u.role == "admin"),
        )

    async def get_tasks_stats(self) -> _TasksStats:
        return _TasksStats(
            total_tasks=len(self._tasks),
            done_tasks=sum(1 for t in self._tasks if t.status and t.status.value == "done"),
            pending_tasks=sum(1 for t in self._tasks if not t.status or t.status.value != "done"),
        )

    async def get_groups_count(self) -> int:
        return len(self._groups)

    async def get_comments_count(self) -> int:
        return len(self._comments)

    async def check_connection(self) -> None:
        pass  # всегда "доступна"
