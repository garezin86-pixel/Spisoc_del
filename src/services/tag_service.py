# src/services/tag_service.py
from src.core.exceptions import incorrect_request, no_access, not_found, task_not_found
from src.models.tag import TagModel
from src.models.task import SpisokModel
from src.models.user import UserModel
from src.repositories.abstract import AbstractGroupRepository, AbstractTaskRepository
from src.repositories.tag_repository import TagRepository
from src.schemas.tag import TagCreate
from src.services.permissions import can_edit_task


class TagService:
    def __init__(
        self,
        tag_repo: TagRepository,
        task_repo: AbstractTaskRepository,
        group_repo: AbstractGroupRepository,
    ):
        self.tag_repo = tag_repo
        self.task_repo = task_repo
        self.group_repo = group_repo

    async def list_tags(self) -> list[TagModel]:
        """Теги общие для всей команды — видны всем авторизованным пользователям."""
        return await self.tag_repo.get_all()

    async def create_tag(self, data: TagCreate) -> TagModel:
        existing = await self.tag_repo.get_by_name(data.name)
        if existing:
            incorrect_request(f"Тег '{data.name}' уже существует")
        return await self.tag_repo.create(data.name, data.color)

    async def delete_tag(self, tag_id: int) -> dict:
        tag = await self.tag_repo.get_by_id(tag_id)
        if not tag:
            not_found("Тег не найден")
        await self.tag_repo.delete(tag)
        return {"message": f"Tag {tag_id} deleted"}

    async def set_task_tags(self, task_id: int, tag_ids: list[int], user: UserModel) -> SpisokModel:
        """Полностью заменяет набор тегов на задаче на указанный список."""
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            task_not_found()
        if not await can_edit_task(task, user, self.group_repo):
            no_access()

        tags = await self.tag_repo.get_by_ids(tag_ids)
        found_ids = {t.id for t in tags}
        missing = set(tag_ids) - found_ids
        if missing:
            not_found(f"Теги не найдены: {sorted(missing)}")

        task.tags = tags
        return await self.task_repo.update(task)
