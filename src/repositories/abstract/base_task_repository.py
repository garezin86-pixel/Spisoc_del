from abc import ABC, abstractmethod
from datetime import datetime

from src.models.comment import CommentModel
from src.models.task import SpisokModel, TaskStatus


class AbstractTaskRepository(ABC):
    @abstractmethod
    async def get_all(self) -> list[SpisokModel]:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, task_id: int) -> SpisokModel | None:
        raise NotImplementedError

    @abstractmethod
    async def create(self, task: SpisokModel) -> SpisokModel:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, task: SpisokModel) -> None:
        raise NotImplementedError

    @abstractmethod
    async def update(self, task: SpisokModel) -> SpisokModel:
        raise NotImplementedError

    @abstractmethod
    async def get_tasks_limit(self, query, limit: int, offset: int) -> list[SpisokModel]:
        raise NotImplementedError

    @abstractmethod
    async def get_assigned_tasks(self, pk: int):
        raise NotImplementedError

    @abstractmethod
    async def get_created_tasks_stats(self, pk: int):
        raise NotImplementedError

    @abstractmethod
    async def get_last_appointed_tasks(self, pk: int) -> list[SpisokModel]:
        raise NotImplementedError

    @abstractmethod
    async def add_comment(self, task_id: int, user_id: int, content: str) -> CommentModel:
        raise NotImplementedError

    @abstractmethod
    async def get_user_tasks(self, user_id: int) -> list[SpisokModel]:
        raise NotImplementedError

    @abstractmethod
    async def get_user_tasks_by_status(
        self,
        *,
        user_id: int,
        status: TaskStatus | None = None,
    ) -> list[SpisokModel]:
        raise NotImplementedError

    @abstractmethod
    async def filter_tasks_paginated_total(self, base_query):
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    async def get_filtered_tasks_total(
        self,
        *,
        user_id: int,
        filter_user_group=None,
        group_id: int | None = None,
        filter_type=None,
    ) -> int:
        raise NotImplementedError

    @abstractmethod
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
    ):
        raise NotImplementedError

    @abstractmethod
    async def get_tasks_for_reminder(self, start_time: datetime, end_time: datetime):
        raise NotImplementedError

    @abstractmethod
    async def get_tasks_by_deadline_window(self, start: datetime, end: datetime, user_id: int | None = None):
        raise NotImplementedError

    @abstractmethod
    async def get_overdue_tasks(self, now: datetime, user_id: int | None = None):
        raise NotImplementedError

    @abstractmethod
    async def get_tasks_by_user(self, user_id: int):
        raise NotImplementedError

    @abstractmethod
    async def get_task(self, task_id: int) -> SpisokModel | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id_include_deleted(self, task_id: int):
        raise NotImplementedError

    @abstractmethod
    async def get_deleted_tasks_paginated(
        self,
        *,
        user_id: int,
        is_admin: bool,
        offset: int,
        limit: int,
        search: str | None = None,
    ) -> tuple[list[SpisokModel], int]:
        raise NotImplementedError

    @abstractmethod
    async def hard_delete(self, task: SpisokModel) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_kanban_tasks(
        self,
        *,
        user_id: int,
        project_id: int | None = None,
        only_mine: bool = False,
        only_author: bool = False,
    ) -> list[SpisokModel]:
        raise NotImplementedError

    @abstractmethod
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
        deadline_from: datetime | None = None,
        deadline_to: datetime | None = None,
        max_rows: int = 10_000,
    ) -> list[SpisokModel]:
        raise NotImplementedError

    @abstractmethod
    async def get_tasks_for_analytics(self) -> list[SpisokModel]:
        raise NotImplementedError
