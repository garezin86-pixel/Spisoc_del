# src/repositories/checklist_repository.py
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.checklist import TaskChecklistItemModel


class ChecklistRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_task(self, task_id: int) -> list[TaskChecklistItemModel]:
        result = await self.session.execute(
            select(TaskChecklistItemModel)
            .where(TaskChecklistItemModel.task_id == task_id)
            .order_by(TaskChecklistItemModel.order_index)
        )
        return list(result.scalars().all())

    async def get_by_id(self, item_id: int) -> TaskChecklistItemModel | None:
        result = await self.session.execute(select(TaskChecklistItemModel).where(TaskChecklistItemModel.id == item_id))
        return result.scalar_one_or_none()

    async def create(self, task_id: int, title: str, order_index: int) -> TaskChecklistItemModel:
        item = TaskChecklistItemModel(task_id=task_id, title=title, order_index=order_index)
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def next_order_index(self, task_id: int) -> int:
        items = await self.get_by_task(task_id)
        if not items:
            return 0
        return max(i.order_index for i in items) + 1

    async def update(self, item: TaskChecklistItemModel) -> TaskChecklistItemModel:
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete(self, item: TaskChecklistItemModel) -> None:
        await self.session.delete(item)
        await self.session.commit()

    async def reorder(self, task_id: int, ordering: dict[int, int]) -> list[TaskChecklistItemModel]:
        """Массово обновляет order_index для набора {item_id: new_order_index}.

        Затрагивает только пункты, реально принадлежащие указанной задаче —
        чужой item_id из другой задачи молча игнорируется, а не приводит
        к ошибке или (что хуже) к переупорядочиванию не той задачи.
        """
        items = await self.get_by_task(task_id)
        by_id = {i.id: i for i in items}
        for item_id, new_index in ordering.items():
            if item_id in by_id:
                by_id[item_id].order_index = new_index
        await self.session.commit()
        return await self.get_by_task(task_id)

    async def delete_all_for_task(self, task_id: int) -> None:
        await self.session.execute(delete(TaskChecklistItemModel).where(TaskChecklistItemModel.task_id == task_id))
        await self.session.commit()
