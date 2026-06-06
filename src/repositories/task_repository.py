from datetime import date, datetime, time
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, func, case, and_

from src.models.comment import CommentModel
from src.models.task import SpisokModel
from src.repositories.abstract.base_task_repository import AbstractTaskRepository


class TaskRepository(AbstractTaskRepository):
    """Репозиторий задач.

    Отвечает за все SQL-запросы к таблице spisok_del.
    Не содержит бизнес-логики — только запросы и маппинг результатов.
    Soft-delete фильтруется через SpisokModel.not_deleted_filter() —
    удалённые задачи невидимы для большинства методов, кроме явно включающих deleted.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self) -> list[SpisokModel]:
        """Возвращает все задачи включая soft-deleted. Используется только в тестах."""
        result = await self.session.execute(select(SpisokModel))
        return list(result.scalars().all())

    async def get_by_id(self, task_id: int) -> SpisokModel | None:
        """Возвращает задачу по ID, исключая soft-deleted.

        Зачем: стандартный метод чтения — удалённые задачи должны быть
        прозрачно скрыты для большинства операций.
        Жадно загружает author и user чтобы избежать N+1 при сериализации.
        """
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
        """Возвращает задачу по ID, включая soft-deleted.

        Зачем: нужен для операций с корзиной (восстановление, hard delete),
        когда задача уже помечена как удалённая.
        """
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
        """Сохраняет новую задачу и обновляет объект из БД (refresh).

        Зачем: refresh нужен чтобы получить серверно-генерируемые поля
        (id, created_at) без дополнительного SELECT.
        """
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def delete(self, task: SpisokModel) -> None:
        """Физически удаляет задачу из БД (hard delete без audit-лога).

        Зачем: используется во вспомогательных сценариях. Для hard delete
        с audit-логом используется метод hard_delete через TaskAdminService.
        """
        await self.session.delete(task)
        await self.session.commit()

    async def hard_delete(self, task: SpisokModel) -> None:
        """Физически удаляет задачу без коммита.

        Зачем: коммит делается в сервисе после записи audit-лога —
        чтобы удаление и аудит были в одной транзакции.
        """
        await self.session.delete(task)

    async def update(self, task: SpisokModel) -> SpisokModel:
        """Фиксирует изменения задачи и рефрешит объект.

        Зачем: изменения в полях SQLAlchemy-объекта автоматически отслеживаются
        через unit-of-work. Commit + refresh синхронизирует updated_at.
        """
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def get_tasks_limit(
        self, query, limit: int, offset: int
    ) -> list[SpisokModel]:
        """Применяет LIMIT/OFFSET к готовому запросу и возвращает результат.

        Зачем: вынесен отдельно, чтобы один и тот же query можно было
        использовать для COUNT (total) и для SELECT с пагинацией.
        """
        result = await self.session.execute(query.limit(limit).offset(offset))
        return list(result.scalars().all())

    async def get_assigned_tasks(self, pk: int):
        """Возвращает агрегат (total, done, pending) задач, назначенных пользователю.

        Зачем: один запрос вместо трёх отдельных COUNT — для дашборда пользователя.
        """
        result = await self.session.execute(
            select(
                func.count(SpisokModel.id).label("total"),
                func.sum(case((SpisokModel.is_done.is_(True), 1), else_=0)).label("done"),
                func.sum(case((SpisokModel.is_done.is_(False), 1), else_=0)).label("pending"),
            ).where(SpisokModel.user_id == pk)
        )
        return result.one()

    async def get_created_tasks_stats(self, pk: int):
        """Возвращает агрегат (total, done) задач, созданных пользователем.

        Зачем: отдельно от назначенных, т.к. автор ≠ исполнитель.
        """
        result = await self.session.execute(
            select(
                func.count(SpisokModel.id).label("total"),
                func.sum(case((SpisokModel.is_done.is_(True), 1), else_=0)).label("done"),
            ).where(SpisokModel.author_id == pk)
        )
        return result.one()

    async def get_last_appointed_tasks(self, pk: int) -> list[SpisokModel]:
        """Возвращает 10 последних задач, назначенных пользователю.

        Зачем: для раздела «последние задачи» в профиле пользователя.
        """
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
        """Создаёт комментарий к задаче напрямую через репозиторий.

        Зачем: устаревший метод для совместимости. Новый код использует CommentRepository.
        """
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
        """Возвращает все задачи пользователя, отсортированные по дате создания."""
        result = await self.session.execute(
            select(SpisokModel)
            .where(SpisokModel.user_id == user_id)
            .order_by(SpisokModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_user_tasks_by_status(
        self, user_id: int, is_done: bool
    ) -> list[SpisokModel]:
        """Возвращает задачи пользователя, отфильтрованные по статусу выполнения."""
        result = await self.session.execute(
            select(SpisokModel)
            .where(
                SpisokModel.user_id == user_id,
                SpisokModel.is_done == is_done,
            )
            .order_by(SpisokModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def filter_tasks_paginated_total(self, base_query) -> int:
        """Считает общее количество строк в запросе через COUNT(*) над subquery.

        Зачем: позволяет получить total для пагинации без повторного SELECT всех записей.
        """
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
        filter_type=None,
        is_done: Optional[bool] = None,
    ):
        """Строит базовый SELECT-запрос с применением фильтров.

        Зачем: отделяет построение запроса от его выполнения — один и тот же
        метод используется для COUNT (total) и для SELECT с LIMIT/OFFSET.
        Все фильтры применяются через WHERE-условия, не в Python.
        """
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
            query = query.where(SpisokModel.is_done == is_done)

        return query.where(SpisokModel.not_deleted_filter())

    def _build_trash_query(self, user_id: int, search: str | None = None):
        """Строит запрос для корзины: только soft-deleted задачи текущего пользователя.

        Зачем: обычный пользователь должен видеть только свои удалённые задачи,
        чтобы не раскрывать удалённые задачи других пользователей.
        """
        query = (
            select(SpisokModel)
            .options(
                selectinload(SpisokModel.author),
                selectinload(SpisokModel.user),
            )
            .where(SpisokModel.deleted_at.is_not(None))
            .where(
                (SpisokModel.author_id == user_id) | (SpisokModel.user_id == user_id)
            )
        )
        if search:
            query = query.where(SpisokModel.title.ilike(f"%{search}%"))
        return query.order_by(SpisokModel.deleted_at.desc())

    def _build_trash_query_admin(self, search: str | None = None):
        """Строит запрос для корзины admin/manager: все soft-deleted задачи системы."""
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
        """Возвращает (tasks, total) из корзины с учётом прав.

        Зачем: единая точка входа для эндпоинта /trash,
        которая автоматически выбирает нужный запрос на основе роли.
        """
        query = (
            self._build_trash_query_admin(search)
            if is_admin
            else self._build_trash_query(user_id, search)
        )
        total = await self.filter_tasks_paginated_total(query)
        tasks = await self.get_tasks_limit(query, limit, offset)
        return tasks, total

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
        """Возвращает задачи с фильтрами без total (устаревший вариант).

        Зачем: оставлен для обратной совместимости. В новом коде используется
        get_filtered_tasks_with_total.
        """
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
        """Считает количество задач по фильтрам без загрузки строк."""
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
        filter_type=None,
        is_done: Optional[bool] = None,
    ) -> tuple[list[SpisokModel], int]:
        """Возвращает (tasks, total) — основной метод фильтрации для API.

        Зачем: объединяет COUNT и SELECT в два запроса к одному query,
        что эффективнее чем строить запрос дважды отдельно.
        """
        query = self._build_filtered_tasks_query(
            user_id=user_id,
            filter_user_group=filter_user_group,
            group_id=group_id,
            filter_type=filter_type,
            is_done=is_done,
        )
        total = await self.filter_tasks_paginated_total(query)
        tasks = await self.get_tasks_limit(query, limit, offset)
        return tasks, total

    async def get_tasks_for_reminder(self, start_time: datetime, end_time: datetime):
        """Возвращает задачи с дедлайном в заданном временном окне для напоминаний.

        Зачем: используется планировщиком (APScheduler) для выборки задач,
        о которых нужно отправить напоминание. Фильтрует уже выполненные
        и задачи без исполнителя (некому отправлять).
        """
        query = select(SpisokModel).where(
            SpisokModel.deadline.between(start_time, end_time),
            SpisokModel.reminder_sent.is_(False),
            SpisokModel.is_done.is_(False),
            SpisokModel.user_id.isnot(None),
        )
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_tasks_by_deadline_window(
        self, start: datetime, end: datetime, user_id: Optional[int] = None
    ):
        """Возвращает задачи с дедлайном в диапазоне [start, end].

        Зачем: используется для напоминаний за 24ч и 1ч до дедлайна.
        Опциональная фильтрация по user_id — для тестирования отдельного пользователя.
        """
        query = select(SpisokModel).where(
            and_(
                SpisokModel.deadline >= start,
                SpisokModel.deadline <= end,
                SpisokModel.is_done.is_(False),
            )
        )
        if user_id is not None:
            query = query.where(SpisokModel.user_id == user_id)
        query = query.order_by(SpisokModel.deadline.asc())
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_overdue_tasks(self, now: datetime, user_id: Optional[int] = None):
        """Возвращает просроченные невыполненные задачи.

        Зачем: используется планировщиком для отправки уведомлений
        о просроченных задачах каждый час.
        """
        query = select(SpisokModel).where(
            and_(SpisokModel.deadline < now, SpisokModel.is_done.is_(False))
        )
        if user_id is not None:
            query = query.where(SpisokModel.user_id == user_id)
        query = query.order_by(SpisokModel.deadline.asc())
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_tasks_by_user(self, user_id: int):
        """Возвращает все задачи пользователя без фильтров."""
        query = select(SpisokModel).where(SpisokModel.user_id == user_id)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_task(self, task_id: int) -> Optional[SpisokModel]:
        """Возвращает задачу по ID без eager-загрузки связей.

        Зачем: лёгкий вариант get_by_id для случаев, когда relations не нужны.
        """
        query = select(SpisokModel).where(SpisokModel.id == task_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
