import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import no_access, task_not_found
from src.models.comment import CommentModel
from src.models.user import UserModel
from src.repositories.abstract import AbstractCommentRepository, AbstractTaskRepository
from src.schemas.comment import CommentCreate
from src.services.notifications import notify_comment_added
from src.services.permissions import can_edit_task

logger = structlog.get_logger()


class CommentService:
    """Сервис комментариев к задачам.

    Управляет созданием и чтением комментариев.
    Доступ к комментариям задачи проверяется через те же правила, что и доступ к задаче.
    """

    def __init__(
        self,
        task_repo: AbstractTaskRepository,
        comment_repo: AbstractCommentRepository,
        session: AsyncSession | None = None,
        group_repo=None,
    ):
        self.task_repo = task_repo
        self.comment_repo = comment_repo
        self.session = session
        self.group_repo = group_repo

    async def add_comment(
        self,
        task_id: int,
        data: CommentCreate,
        current_user: UserModel,
    ) -> CommentModel:
        """Добавляет комментарий к задаче.

        Зачем: комментарии используются для общения между автором и исполнителем
        прямо в контексте задачи без внешних мессенджеров.

        Side-effects:
            - Отправляет Telegram-уведомление автору и исполнителю задачи
              (кроме того, кто оставил комментарий). Вызывается только если
              передан session — это позволяет отключить уведомления в тестах.
            - Логирует событие comment_created.

        Raises:
            HTTPException 404: задача не найдена.
            HTTPException 403: нет доступа к задаче.
        """
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            task_not_found()

        if not await can_edit_task(task, current_user, self.group_repo):
            no_access()

        comment = CommentModel(
            content=data.content,
            task_id=task_id,
            user_id=current_user.id,
        )
        result = await self.comment_repo.create(comment)
        await logger.ainfo(
            "comment_created",
            task_id=task_id,
            user_id=current_user.id,
            comment_id=result.id,
        )

        if self.session is not None:
            await notify_comment_added(comment.id)

        return result

    async def get_by_task(
        self,
        task_id: int,
        current_user: UserModel,
    ) -> list[CommentModel]:
        """Возвращает все комментарии к задаче без пагинации.

        Зачем: используется в Telegram-боте, где комментарии показываются
        единым списком. Для API предпочтительнее get_by_task_paginated.

        Raises:
            HTTPException 404: задача не найдена.
            HTTPException 403: нет доступа к задаче.
        """
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            task_not_found()

        if not await can_edit_task(task, current_user, self.group_repo):
            no_access()

        return await self.comment_repo.get_by_task(task_id)

    async def get_by_task_paginated(self, task_id: int, offset: int, limit: int, user: UserModel):
        """Возвращает (comments, total) для задачи с пагинацией.

        Зачем: задачи могут накопить много комментариев — пагинация
        предотвращает загрузку сотен записей за один запрос.

        Комментарии сортируются по убыванию даты (новые — первые).
        Права доступа к задаче проверяются перед выдачей комментариев.

        Raises:
            HTTPException 404: задача не найдена.
        """
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            task_not_found()

        query = await self.comment_repo.select_query(task_id)
        total = await self.comment_repo.get_total_tasks(query)
        comments = await self.comment_repo.get_by_task_offset_limit(query, offset, limit)
        return comments, total
