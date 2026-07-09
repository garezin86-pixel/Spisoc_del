# src/services/attachment_service.py
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import no_access, not_found, task_not_found
from src.models.attachment_model import AttachmentModel
from src.models.user import UserModel
from src.repositories.abstract import AbstractGroupRepository, AbstractTaskRepository
from src.repositories.attachment_repository import AttachmentRepository
from src.services.active_storage import storage
from src.services.permissions import can_edit_task

logger = structlog.get_logger()


class AttachmentService:
    """
    Сервис вложений к задачам.

    Доступ к вложениям задачи проверяется через те же правила,
    что и доступ к редактированию задачи (can_edit_task) — то есть
    автор, исполнитель, члены группы и admin/manager.
    """

    def __init__(
        self,
        task_repo: AbstractTaskRepository,
        attachment_repo: AttachmentRepository,
        session: AsyncSession | None = None,
        group_repo: AbstractGroupRepository | None = None,
    ):
        self.task_repo = task_repo
        self.attachment_repo = attachment_repo
        self.session = session
        self.group_repo = group_repo

    async def _check_access(self, task_id: int, user: UserModel):
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            task_not_found()
        if not await can_edit_task(task, user, self.group_repo):
            no_access("Нет доступа к вложениям этой задачи")
        return task

    async def list_for_task(self, task_id: int, user: UserModel) -> list[AttachmentModel]:
        await self._check_access(task_id, user)
        return await self.attachment_repo.get_by_task_id(task_id)

    async def get_download_url(self, attachment_id: int, user: UserModel) -> str:
        """
        Возвращает рабочую ссылку для скачивания — используется ботом.

        Приоритет:
          1. storage_url — если файл в R2 и бакет публичный (storage_url будет https://...).
          2. presigned URL по storage_key — если бакет приватный, но файл в R2.
          3. "" — файл в локальном стораджа; бот сообщает пользователю скачать через веб-интерфейс.
             (Веб-интерфейс использует эндпоинт /api/attachments/{id}/download напрямую,
              он стримит файл через FileResponse без этого метода.)

        Примечание: веб-роутер (download_attachment) больше не вызывает этот метод —
        он сам делает FileResponse/RedirectResponse в зависимости от storage backend.
        """
        attachment = await self.attachment_repo.get_by_id(attachment_id)
        if not attachment:
            not_found("Вложение не найдено")

        await self._check_access(attachment.task_id, user)

        # R2 с публичным бакетом
        if attachment.storage_url:
            return attachment.storage_url

        # R2 с приватным бакетом
        if attachment.storage_key and storage.is_configured:
            url = await storage.get_presigned_url(attachment.storage_key)
            if url:
                return url

        # Local storage — бот не может стримить файл напрямую,
        # пусть отправит пользователя в веб-интерфейс
        return ""

    async def delete(self, attachment_id: int, user: UserModel) -> None:
        attachment = await self.attachment_repo.get_by_id(attachment_id)
        if not attachment:
            not_found("Вложение не найдено")

        await self._check_access(attachment.task_id, user)

        # Чистим R2, если файл там есть — не блокируем удаление записи при ошибке
        if attachment.storage_key and storage.is_configured:
            try:
                await storage.delete(attachment.storage_key)
            except Exception as e:  # noqa: BLE001
                await logger.awarning(
                    "r2_delete_failed_on_attachment_delete",
                    attachment_id=attachment_id,
                    error=str(e),
                )

        await self.attachment_repo.delete(attachment)
        if self.session:
            await self.session.commit()

        await logger.ainfo("attachment_deleted", attachment_id=attachment_id, user_id=user.id)
