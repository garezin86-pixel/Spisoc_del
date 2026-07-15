# src/services/checklist_service.py
from src.core.exceptions import no_access, not_found, task_not_found
from src.models.checklist import TaskChecklistItemModel
from src.models.user import UserModel
from src.repositories.abstract import AbstractGroupRepository, AbstractTaskRepository
from src.repositories.checklist_repository import ChecklistRepository
from src.schemas.checklist import ChecklistItemCreate, ChecklistItemUpdate
from src.services.permissions import can_edit_task


class ChecklistService:
    """Сервис управления пунктами чек-листа задачи.

    Права доступа зеркалят права на саму задачу (can_edit_task) — тот, кто
    может редактировать задачу, может редактировать и её чек-лист. Отдельной
    модели прав для чек-листа нет, чтобы не плодить сущности ради банальных
    вложенных пунктов.
    """

    def __init__(
        self,
        checklist_repo: ChecklistRepository,
        task_repo: AbstractTaskRepository,
        group_repo: AbstractGroupRepository,
    ):
        self.checklist_repo = checklist_repo
        self.task_repo = task_repo
        self.group_repo = group_repo

    async def _get_task_with_access(self, task_id: int, user: UserModel):
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            task_not_found()
        if not await can_edit_task(task, user, self.group_repo):
            no_access()
        return task

    async def list_items(self, task_id: int, user: UserModel) -> list[TaskChecklistItemModel]:
        await self._get_task_with_access(task_id, user)
        return await self.checklist_repo.get_by_task(task_id)

    async def add_item(self, task_id: int, data: ChecklistItemCreate, user: UserModel) -> TaskChecklistItemModel:
        await self._get_task_with_access(task_id, user)
        order_index = data.order_index
        if order_index is None:
            order_index = await self.checklist_repo.next_order_index(task_id)
        return await self.checklist_repo.create(task_id, data.title, order_index)

    async def _get_item_with_access(self, task_id: int, item_id: int, user: UserModel) -> TaskChecklistItemModel:
        await self._get_task_with_access(task_id, user)
        item = await self.checklist_repo.get_by_id(item_id)
        if not item or item.task_id != task_id:
            not_found("Пункт чек-листа не найден")
        return item

    async def update_item(
        self, task_id: int, item_id: int, data: ChecklistItemUpdate, user: UserModel
    ) -> TaskChecklistItemModel:
        item = await self._get_item_with_access(task_id, item_id, user)
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(item, field, value)
        return await self.checklist_repo.update(item)

    async def delete_item(self, task_id: int, item_id: int, user: UserModel) -> dict:
        item = await self._get_item_with_access(task_id, item_id, user)
        await self.checklist_repo.delete(item)
        return {"message": f"Checklist item {item_id} deleted"}

    async def reorder(self, task_id: int, ordering: dict[int, int], user: UserModel) -> list[TaskChecklistItemModel]:
        await self._get_task_with_access(task_id, user)
        return await self.checklist_repo.reorder(task_id, ordering)
