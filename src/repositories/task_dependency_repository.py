# src/repositories/task_dependency_repository.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.task import SpisokModel, TaskStatus
from src.models.task_dependency import TaskDependencyModel


class TaskDependencyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_dependency(self, blocker_task_id: int, blocked_task_id: int) -> TaskDependencyModel | None:
        return await self.session.scalar(
            select(TaskDependencyModel).where(
                TaskDependencyModel.blocker_task_id == blocker_task_id,
                TaskDependencyModel.blocked_task_id == blocked_task_id,
            )
        )

    async def add(self, blocker_task_id: int, blocked_task_id: int) -> TaskDependencyModel:
        dep = TaskDependencyModel(blocker_task_id=blocker_task_id, blocked_task_id=blocked_task_id)
        self.session.add(dep)
        await self.session.commit()
        await self.session.refresh(dep)
        return dep

    async def remove(self, dep: TaskDependencyModel) -> None:
        await self.session.delete(dep)
        await self.session.commit()

    async def get_blockers(self, task_id: int) -> list[SpisokModel]:
        """Задачи, которые блокируют task_id (должны закрыться раньше него)."""
        result = await self.session.execute(
            select(SpisokModel)
            .join(TaskDependencyModel, TaskDependencyModel.blocker_task_id == SpisokModel.id)
            .where(TaskDependencyModel.blocked_task_id == task_id)
            .options(selectinload(SpisokModel.author), selectinload(SpisokModel.user))
        )
        return list(result.scalars().all())

    async def get_open_blockers(self, task_id: int) -> list[SpisokModel]:
        """Подмножество get_blockers, которые ещё не закрыты (status != done)."""
        blockers = await self.get_blockers(task_id)
        return [b for b in blockers if b.status != TaskStatus.done]

    async def get_blocked(self, task_id: int) -> list[SpisokModel]:
        """Задачи, которые блокирует task_id (ждут его закрытия)."""
        result = await self.session.execute(
            select(SpisokModel)
            .join(TaskDependencyModel, TaskDependencyModel.blocked_task_id == SpisokModel.id)
            .where(TaskDependencyModel.blocker_task_id == task_id)
            .options(selectinload(SpisokModel.author), selectinload(SpisokModel.user))
        )
        return list(result.scalars().all())

    async def would_create_cycle(self, blocker_task_id: int, blocked_task_id: int) -> bool:
        """
        Проверяет, не создаст ли ребро blocker->blocked цикл в графе
        зависимостей. Цикл возникнет, если blocked уже (транзитивно, через
        любую цепочку) блокирует blocker — тогда обе задачи никогда не
        смогут закрыться. Обходим граф в памяти (BFS) — для типичного
        размера команды/проекта таблица связей маленькая, тянуть её всю
        дешевле и надёжнее, чем городить рекурсивный CTE отдельно для
        Postgres и SQLite (в тестах).
        """
        result = await self.session.execute(
            select(TaskDependencyModel.blocker_task_id, TaskDependencyModel.blocked_task_id)
        )
        edges: dict[int, list[int]] = {}
        for blocker_id, blocked_id in result.all():
            edges.setdefault(blocker_id, []).append(blocked_id)

        # Ищем путь blocked_task_id -> ... -> blocker_task_id по существующим
        # рёбрам. Если он есть, добавление blocker->blocked замкнёт цикл.
        visited = {blocked_task_id}
        queue = [blocked_task_id]
        while queue:
            current = queue.pop()
            if current == blocker_task_id:
                return True
            for nxt in edges.get(current, []):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
        return False
