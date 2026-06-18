from datetime import date, datetime, time
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, func, case, and_

from src.models.comment import CommentModel
from src.models.task import SpisokModel, TaskStatus
from src.repositories.abstract.base_task_repository import AbstractTaskRepository


class TaskRepository(AbstractTaskRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self) -> list[SpisokModel]:
        result = await self.session.execute(select(SpisokModel))
        return list(result.scalars().all())

    async def get_by_id(self, task_id: int) -> SpisokModel | None:
        result = await self.session.execute(
            select(SpisokModel)
            .options(
                selectinload(SpisokModel.author),
                selectinload(SpisokModel.user),
            )
            .where(SpisokModel.id == task_id)
            .where(SpisokModel.not_deleted_filter())
        )
        return result.scalar_one_or_none()

    async def get_by_id_include_deleted(self, task_id: int) -> SpisokModel | None:
        result = await self.session.execute(
            select(SpisokModel)
            .options(
                selectinload(SpisokModel.author),
                selectinload(SpisokModel.user),
            )
            .where(SpisokModel.id == task_id)
        )
        return result.scalar_one_or_none()

    async def create(self, task: SpisokModel) -> SpisokModel:
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def delete(self, task: SpisokModel) -> None:
        await self.session.delete(task)
        await self.session.commit()

    async def hard_delete(self, task: SpisokModel) -> None:
        """Физическое удаление из БД без возможности восстановления."""
        await self.session.delete(task)

    async def update(self, task: SpisokModel) -> SpisokModel:
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def get_tasks_limit(
        self, query, limit: int, offset: int
    ) -> list[SpisokModel]:
        result = await self.session.execute(query.limit(limit).offset(offset))
        return list(result.scalars().all())

    async def get_assigned_tasks(self, pk: int):
        result = await self.session.execute(
            select(
                func.count(SpisokModel.id).label("total"),
                func.sum(
                    case((SpisokModel.status == TaskStatus.done, 1), else_=0)
                ).label("done"),
                func.sum(
                    case(
                        (
                            SpisokModel.status.in_(
                                [
                                    TaskStatus.todo,
                                    TaskStatus.in_progress,
                                    TaskStatus.review,
                                ]
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("pending"),
            ).where(SpisokModel.user_id == pk)
        )
        return result.one()

    async def get_created_tasks_stats(self, pk: int):
        result = await self.session.execute(
            select(
                func.count(SpisokModel.id).label("total"),
                func.sum(
                    case((SpisokModel.status == TaskStatus.done, 1), else_=0)
                ).label("done"),
            ).where(SpisokModel.author_id == pk)
        )
        return result.one()

    async def get_last_appointed_tasks(self, pk: int) -> list[SpisokModel]:
        result = await self.session.execute(
            select(SpisokModel)
            .where(SpisokModel.user_id == pk)
            .order_by(SpisokModel.created_at.desc())
            .limit(10)
        )
        return list(result.scalars().all())

    async def add_comment(
        self, task_id: int, user_id: int, content: str
    ) -> CommentModel:
        comment = CommentModel(
            task_id=int(task_id),
            user_id=int(user_id),
            content=content,
        )
        self.session.add(comment)
        await self.session.commit()
        await self.session.refresh(comment)
        return comment

    async def get_user_tasks(self, user_id: int) -> list[SpisokModel]:
        result = await self.session.execute(
            select(SpisokModel)
            .where(SpisokModel.user_id == user_id)
            .order_by(SpisokModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_user_tasks_by_status(
        self, user_id: int, done: bool
    ) -> list[SpisokModel]:
        status_filter = (
            SpisokModel.status == TaskStatus.done
            if done
            else SpisokModel.status != TaskStatus.done
        )
        result = await self.session.execute(
            select(SpisokModel)
            .where(SpisokModel.user_id == user_id, status_filter)
            .order_by(SpisokModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def filter_tasks_paginated_total(self, base_query) -> int:
        total = await self.session.scalar(
            select(func.count()).select_from(base_query.subquery())
        )
        return total if total is not None else 0

    def _build_filtered_tasks_query(
        self,
        *,
        user_id: int,
        filter_user_group=None,
        group_id: Optional[int] = None,
        project_id: Optional[int] = None,
        filter_type=None,
        is_done: Optional[bool] = None,
        priority: str | None = None,
        status=None,
    ):
        query = select(SpisokModel).options(selectinload(SpisokModel.author))

        filter_user_group_value = getattr(filter_user_group, "value", filter_user_group)
        filter_type_value = getattr(filter_type, "value", filter_type)

        if filter_user_group_value == "user":
            query = query.where(SpisokModel.user_id == user_id)
        elif filter_user_group_value == "group":
            query = query.where(SpisokModel.group_id == group_id)
        elif filter_user_group_value == "free":
            query = query.where(
                SpisokModel.user_id.is_(None),
                SpisokModel.group_id.is_(None),
            )
        elif filter_user_group_value == "author":
            query = query.where(SpisokModel.author_id == user_id)

        start_today = datetime.combine(date.today(), time.min)
        end_today = datetime.combine(date.today(), time.max)

        if filter_type_value == "today":
            query = query.where(
                SpisokModel.deadline.is_not(None),
                SpisokModel.deadline >= start_today,
                SpisokModel.deadline <= end_today,
            )
        elif filter_type_value == "overdue":
            query = query.where(
                SpisokModel.deadline.is_not(None),
                SpisokModel.deadline < start_today,
            )
        elif filter_type_value == "planned":
            query = query.where(
                SpisokModel.deadline.is_not(None),
                SpisokModel.deadline > end_today,
            )
        elif filter_type_value == "deadline_null":
            query = query.where(SpisokModel.deadline.is_(None))

        if is_done is not None:
            if is_done:
                query = query.where(SpisokModel.status == TaskStatus.done)
            else:
                query = query.where(SpisokModel.status != TaskStatus.done)

        if status is not None:
            status_value = getattr(status, "value", status)
            query = query.where(SpisokModel.status == status_value)

        if priority is not None:
            priority_value = getattr(priority, "value", priority)
            query = query.where(SpisokModel.priority == priority_value)

        if project_id is not None:
            query = query.where(SpisokModel.project_id == project_id)

        return query.where(SpisokModel.not_deleted_filter())

    # ── Корзина ───────────────────────────────────────────────────────────────

    def _build_trash_query(self, user_id: int, search: str | None = None):
        """
        Базовый запрос для корзины: только удалённые задачи,
        к которым у пользователя есть доступ (автор или исполнитель).
        Admin/manager видят все удалённые задачи.
        """
        query = (
            select(SpisokModel)
            .options(
                selectinload(SpisokModel.author),
                selectinload(SpisokModel.user),
            )
            .where(SpisokModel.deleted_at.is_not(None))
            # Пользователь видит только свои удалённые задачи
            .where(
                (SpisokModel.author_id == user_id) | (SpisokModel.user_id == user_id)
            )
        )
        if search:
            query = query.where(SpisokModel.title.ilike(f"%{search}%"))
        return query.order_by(SpisokModel.deleted_at.desc())

    def _build_trash_query_admin(self, search: str | None = None):
        """Admin/manager видят все удалённые задачи."""
        query = (
            select(SpisokModel)
            .options(
                selectinload(SpisokModel.author),
                selectinload(SpisokModel.user),
            )
            .where(SpisokModel.deleted_at.is_not(None))
        )
        if search:
            query = query.where(SpisokModel.title.ilike(f"%{search}%"))
        return query.order_by(SpisokModel.deleted_at.desc())

    async def get_deleted_tasks_paginated(
        self,
        *,
        user_id: int,
        is_admin: bool,
        offset: int,
        limit: int,
        search: str | None = None,
    ):
        query = (
            self._build_trash_query_admin(search)
            if is_admin
            else self._build_trash_query(user_id, search)
        )
        total = await self.filter_tasks_paginated_total(query)
        tasks = await self.get_tasks_limit(query, limit, offset)
        return tasks, total

    # ── Остальные методы ──────────────────────────────────────────────────────

    async def get_filtered_tasks(
        self,
        *,
        user_id: int,
        offset: int,
        limit: int,
        filter_user_group=None,
        group_id: Optional[int] = None,
        filter_type=None,
        is_done: Optional[bool] = None,
    ) -> list[SpisokModel]:
        query = self._build_filtered_tasks_query(
            user_id=user_id,
            filter_user_group=filter_user_group,
            group_id=group_id,
            filter_type=filter_type,
            is_done=is_done,
        )
        return await self.get_tasks_limit(query, limit, offset)

    async def get_filtered_tasks_total(
        self,
        *,
        user_id: int,
        filter_user_group=None,
        group_id: Optional[int] = None,
        filter_type=None,
        is_done: Optional[bool] = None,
    ) -> int:
        query = self._build_filtered_tasks_query(
            user_id=user_id,
            filter_user_group=filter_user_group,
            group_id=group_id,
            filter_type=filter_type,
            is_done=is_done,
        )
        return await self.filter_tasks_paginated_total(query)

    async def get_filtered_tasks_with_total(
        self,
        *,
        user_id: int,
        offset: int,
        limit: int,
        filter_user_group=None,
        group_id: Optional[int] = None,
        project_id: Optional[int] = None,
        filter_type=None,
        is_done: Optional[bool] = None,
        priority: str | None = None,
        status=None,
    ) -> tuple[list[SpisokModel], int]:
        query = self._build_filtered_tasks_query(
            user_id=user_id,
            filter_user_group=filter_user_group,
            group_id=group_id,
            project_id=project_id,
            filter_type=filter_type,
            is_done=is_done,
            priority=priority,
            status=status,
        )
        total = await self.filter_tasks_paginated_total(query)
        tasks = await self.get_tasks_limit(query, limit, offset)
        return tasks, total

    async def get_tasks_for_reminder(self, start_time: datetime, end_time: datetime):
        query = select(SpisokModel).where(
            SpisokModel.deadline.between(start_time, end_time),
            SpisokModel.reminder_sent.is_(False),
            SpisokModel.status != TaskStatus.done,
            SpisokModel.user_id.isnot(None),
        )
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_tasks_by_deadline_window(
        self, start: datetime, end: datetime, user_id: Optional[int] = None
    ):
        query = select(SpisokModel).where(
            and_(
                SpisokModel.deadline >= start,
                SpisokModel.deadline <= end,
                SpisokModel.status != TaskStatus.done,
            )
        )
        if user_id is not None:
            query = query.where(SpisokModel.user_id == user_id)
        query = query.order_by(SpisokModel.deadline.asc())
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_overdue_tasks(self, now: datetime, user_id: Optional[int] = None):
        query = select(SpisokModel).where(
            and_(SpisokModel.deadline < now, SpisokModel.status != TaskStatus.done)
        )
        if user_id is not None:
            query = query.where(SpisokModel.user_id == user_id)
        query = query.order_by(SpisokModel.deadline.asc())
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_tasks_by_user(self, user_id: int):
        query = select(SpisokModel).where(SpisokModel.user_id == user_id)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_task(self, task_id: int) -> Optional[SpisokModel]:
        query = select(SpisokModel).where(SpisokModel.id == task_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    # ── Канбан ────────────────────────────────────────────────────────────────

    async def get_kanban_tasks(
        self,
        *,
        user_id: int,
        project_id: int | None = None,
        only_mine: bool = False,
        only_author: bool = False,
    ) -> list[SpisokModel]:
        """
        Возвращает все не-удалённые задачи для канбан-доски.
        Если project_id задан — только задачи этого проекта.
        Если only_mine=True — только задачи где user_id совпадает.
        """
        query = (
            select(SpisokModel)
            .options(
                selectinload(SpisokModel.author),
                selectinload(SpisokModel.user),
                selectinload(SpisokModel.group),
            )
            .where(SpisokModel.not_deleted_filter())
        )

        if project_id is not None:
            query = query.where(SpisokModel.project_id == project_id)
        elif only_mine:
            query = query.where(SpisokModel.user_id == user_id)
        elif only_author:
            query = query.where(SpisokModel.author_id == user_id)
        else:
            # Показываем задачи где пользователь — автор или исполнитель
            query = query.where(
                (SpisokModel.author_id == user_id) | (SpisokModel.user_id == user_id)
            )

        query = query.order_by(SpisokModel.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())
