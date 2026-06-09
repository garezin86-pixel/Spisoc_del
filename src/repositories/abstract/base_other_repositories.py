from abc import ABC, abstractmethod
from typing import Optional
from src.models.comment import CommentModel
from src.models.notification_log import NotificationLogModel
from src.models.task import SpisokModel
from src.schemas.stats import UsersStats


class AbstractCommentRepository(ABC):
    @abstractmethod
    async def create(self, comment: CommentModel) -> CommentModel:
        raise NotImplementedError

    @abstractmethod
    async def get_by_task(self, task_id: int) -> list[CommentModel]:
        raise NotImplementedError

    @abstractmethod
    async def select_query(self, task_id: int):
        raise NotImplementedError

    @abstractmethod
    async def get_total_tasks(self, query):
        raise NotImplementedError

    @abstractmethod
    async def get_by_task_offset_limit(self, query, offset, limit):
        raise NotImplementedError


class AbstractNotificationRepository(ABC):
    @abstractmethod
    async def get_comment_with_relations(self, comment_id: int) -> CommentModel | None:
        raise NotImplementedError

    @abstractmethod
    async def get_task_with_relations(self, task_id: int) -> SpisokModel | None:
        raise NotImplementedError

    @abstractmethod
    async def create_log(
        self,
        user_id: int,
        notification_type: str,
        content: str,
        task_id: Optional[int] = None,
        success: bool = True,
        error: Optional[str] = None,
    ) -> NotificationLogModel | None:
        raise NotImplementedError

    @abstractmethod
    async def check_already_sent(
        self,
        user_id: int,
        task_id: Optional[int],
        notification_type: str,
        hours_back: Optional[int] = None,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def get_admin_statistics(
        self,
        days: int = 7,
        top_users_limit: int = 10,
    ) -> dict:
        raise NotImplementedError


class AbstractStatsRepository(ABC):
    @abstractmethod
    async def get_users_stats(self) -> UsersStats:
        raise NotImplementedError

    @abstractmethod
    async def get_tasks_stats(self):
        raise NotImplementedError

    @abstractmethod
    async def get_groups_count(self) -> int:
        raise NotImplementedError

    @abstractmethod
    async def get_comments_count(self) -> int:
        raise NotImplementedError

    @abstractmethod
    async def check_connection(self) -> None:
        raise NotImplementedError
