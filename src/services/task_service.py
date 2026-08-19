from datetime import datetime, timedelta, timezone
from typing import Protocol

import structlog
from dateutil.relativedelta import relativedelta
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.constants import (
    ENTER_GROUP_ID,
    GROUP_NOT_FOUND,
    NO_ACCESS,
    TAG_NOT_FOUND,
    TASK_NOT_FOUND,
    USER_ID_OR_GROUP_ID,
    USER_NOT_FOUND,
    YOU_CANNOT_DELETE_TASK,
)
from src.core.exceptions import (
    incorrect_request,
    no_access,
    not_found,
    task_blocked,
    task_not_found,
    unauthorized_user,
    user_not_found,
)
from src.core.metrics import (
    tasks_completed,
    tasks_created,
    tasks_deleted,
    tasks_hard_deleted,
    tasks_restored,
)
from src.models.enums import RecurrenceRule
from src.models.tag import TagModel
from src.models.task import SpisokModel, TaskStatus
from src.models.user import UserModel, UserRole
from src.repositories.abstract import (
    AbstractGroupRepository,
    AbstractTaskRepository,
    AbstractUserRepository,
)
from src.repositories.task_dependency_repository import TaskDependencyRepository
from src.schemas.task import (
    BulkTaskUpdate,
    BulkTaskUpdateResult,
    FilterUserGroup,
    SpisokAddSchema,
    TaskImportIssueSchema,
    TaskImportSummary,
)
from src.schemas.task_dependency import TaskDependenciesSchema, TaskRefSchema
from src.services.notifications import notify_task_assigned
from src.services.permissions import (
    can_delete_task,
    can_edit_task,
    can_reassign_task,
    can_update_task_deadline,
)
from src.services.task_import_service import TaskImportParseError, parse_import_file

logger = structlog.get_logger()


class TagRepositoryProtocol(Protocol):
    async def get_by_id(self, tag_id: int) -> TagModel | None: ...


class TaskService:
    """Сервис управления задачами.

    Центральная точка бизнес-логики задач: создание, обновление, удаление,
    фильтрация, корзина. Все проверки прав доступа делегируются в модуль permissions.
    """

    def __init__(
        self,
        task_repo: AbstractTaskRepository,
        user_repo: AbstractUserRepository,
        group_repo: AbstractGroupRepository,
        tag_repo: TagRepositoryProtocol,
        session: AsyncSession,
    ):
        self.task_repo = task_repo
        self.user_repo = user_repo
        self.group_repo = group_repo
        self.tag_repo = tag_repo
        self.session = session

    async def add_task(self, data: SpisokAddSchema, current_user: UserModel) -> SpisokModel:
        """Создаёт задачу и запускает уведомление исполнителю.

        Зачем: при создании задачи нужно проверить, что пользователь/группа
        существуют, и сразу отправить уведомление — чтобы исполнитель узнал
        о новой задаче не из интерфейса, а мгновенно через Telegram.

        Side-effects:
            - Вызывает notify_task_assigned (await, не фоново) — доставляет
              Telegram-уведомление до возврата ответа.
            - Инкрементирует Prometheus-счётчик tasks_created.
            - Пишет audit-лог (через session.info["audit_user_id"]).

        Raises:
            HTTPException 400: user_id и group_id переданы одновременно.
            HTTPException 404: пользователь или группа не найдены.
        """
        if data.user_id is not None and data.group_id is not None:
            incorrect_request(USER_ID_OR_GROUP_ID)

        if data.user_id is not None:
            user = await self.user_repo.get_by_id(data.user_id)
            if not user:
                user_not_found()

        if data.group_id is not None:
            group = await self.group_repo.get_by_id(data.group_id)
            if not group:
                not_found(GROUP_NOT_FOUND)

        deadline = None
        if data.deadline is not None:
            deadline = data.deadline.replace(second=0, microsecond=0)

        task = SpisokModel(
            title=data.title,
            description=data.description,
            user_id=data.user_id,
            group_id=data.group_id,
            deadline=deadline,
            author_id=current_user.id,
            project_id=data.project_id,
            status=data.status,
            priority=data.priority,
            recurrence_rule=data.recurrence_rule,
            # Редкий, но возможный случай: задачу создают сразу со status=done
            # (например, задним числом фиксируют уже сделанную работу).
            completed_at=(datetime.now(timezone.utc) if data.status == TaskStatus.done else None),
        )
        task = await self.task_repo.create(task)
        await logger.ainfo(
            "task_created",
            task_id=task.id,
            user_id=current_user.id,
            assigned_user_id=task.user_id,
            group_id=task.group_id,
        )

        if self.session is not None:
            import asyncio

            asyncio.create_task(notify_task_assigned(task.id))
        tasks_created.inc()
        return task

    @staticmethod
    def _next_deadline(current_deadline: datetime | None, rule: RecurrenceRule) -> datetime | None:
        """Вычисляет дедлайн следующего повторения.

        Если у исходной задачи не было дедлайна — у следующего повторения
        тоже не будет (интервал отсчитывается не от "текущего момента",
        а сохраняет прежнее отсутствие дедлайна, чтобы не навязывать срок
        задачам, где его изначально не было).
        """
        if current_deadline is None:
            return None
        base = current_deadline
        if rule == RecurrenceRule.daily:
            return base + timedelta(days=1)
        if rule == RecurrenceRule.weekly:
            return base + timedelta(weeks=1)
        if rule == RecurrenceRule.monthly:
            return base + relativedelta(months=1)
        return None

    async def _spawn_next_recurrence(self, completed_task: SpisokModel) -> SpisokModel | None:
        """Создаёт следующее повторение задачи после завершения текущего.

        Зачем: избавляет от необходимости вручную пересоздавать регулярные
        задачи ("каждый понедельник — созвон"). Срабатывает синхронно в
        момент перевода в done — не требует отдельной scheduled-джобы и
        рисков двойного порождения при её повторном запуске.

        Копируется: title, description, priority, user_id, group_id,
        project_id, recurrence_rule (правило продолжает действовать дальше).
        НЕ копируется: status (всегда todo для нового повторения).
        """
        if completed_task.recurrence_rule == RecurrenceRule.none:
            return None

        next_deadline = self._next_deadline(completed_task.deadline, completed_task.recurrence_rule)

        next_task = SpisokModel(
            title=completed_task.title,
            description=completed_task.description,
            user_id=completed_task.user_id,
            group_id=completed_task.group_id,
            author_id=completed_task.author_id,
            project_id=completed_task.project_id,
            priority=completed_task.priority,
            status=TaskStatus.todo,
            deadline=next_deadline,
            recurrence_rule=completed_task.recurrence_rule,
        )
        next_task = await self.task_repo.create(next_task)
        await logger.ainfo(
            "recurrence_spawned",
            source_task_id=completed_task.id,
            new_task_id=next_task.id,
            rule=completed_task.recurrence_rule.value,
        )

        if self.session is not None:
            import asyncio

            asyncio.create_task(notify_task_assigned(next_task.id))

        return next_task

    async def _validate_task_filters(self, filter_user_group, group_id) -> None:
        """Валидирует комбинацию фильтров перед запросом к БД.

        Зачем: filter_user_group=group без group_id привёл бы к некорректному
        SQL-запросу (WHERE group_id = NULL вместо конкретного ID).
        """
        if filter_user_group == FilterUserGroup.group:
            if not group_id:
                incorrect_request(ENTER_GROUP_ID)
            group = await self.group_repo.get_by_id(group_id)
            if not group:
                not_found(GROUP_NOT_FOUND)

    async def filter_tasks(
        self,
        current_user: UserModel,
        filter_user_group,
        group_id,
        filter_type,
        is_done,
        limit,
        offset,
    ):
        """Возвращает задачи без подсчёта total (устаревший метод).

        Зачем: оставлен для обратной совместимости. В API используется
        filter_tasks_paginated, который возвращает (tasks, total).
        """
        await self._validate_task_filters(filter_user_group, group_id)
        return await self.task_repo.get_filtered_tasks(
            user_id=current_user.id,
            offset=offset,
            limit=limit,
            filter_user_group=filter_user_group,
            group_id=group_id,
            filter_type=filter_type,
            is_done=is_done,
        )

    async def get_task(self, task_id: int, current_user: UserModel) -> SpisokModel:
        """Возвращает задачу с проверкой прав доступа.

        Зачем: пользователь не должен видеть чужие задачи — только те,
        к которым у него есть отношение (автор, исполнитель, группа, роль).

        Raises:
            HTTPException 404: задача не найдена (или soft-deleted).
            HTTPException 403: нет доступа.
        """
        task = await self.task_repo.get_by_id(task_id)
        if task is None:
            task_not_found(TASK_NOT_FOUND)
        if not await can_edit_task(task, current_user, self.group_repo):
            await logger.awarning("no_access", user_id=current_user.id, task_id=task_id)
            no_access(NO_ACCESS)
        return task

    async def reassign_task(
        self,
        task_id: int,
        current_user: UserModel,
        user_id: int | None,
        group_id: int | None,
    ) -> SpisokModel:
        """Переназначает задачу другому пользователю или группе.

        Зачем: при переназначении нужно обнулить предыдущего исполнителя/группу,
        чтобы задача не висела сразу на двух.

        Side-effects:
            - Обнуляет противоположное поле (user_id или group_id).
            - Пишет audit-лог.
            - Роутер вешает в фон notify_task_assigned после возврата.

        Raises:
            HTTPException 400: переданы оба или ни одного из параметров.
            HTTPException 403: нет прав на переназначение.
            HTTPException 404: задача, пользователь или группа не найдены.
        """
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            task_not_found()
        if not can_reassign_task(task, current_user):
            await logger.awarning("no_access", user_id=current_user.id, task_id=task_id)
            no_access()
        if user_id is not None and group_id is not None:
            incorrect_request(USER_ID_OR_GROUP_ID)
        if user_id is None and group_id is None:
            incorrect_request(USER_ID_OR_GROUP_ID)
        if user_id is not None:
            if not await self.user_repo.get_by_id(user_id):
                not_found(USER_NOT_FOUND)
            task.user_id = user_id
            task.group_id = None
        if group_id is not None:
            if not await self.group_repo.get_by_id(group_id):
                not_found(GROUP_NOT_FOUND)
            task.group_id = group_id
            task.user_id = None
        updated_task = await self.task_repo.update(task)
        await logger.ainfo(
            "task_updated",
            task_id=updated_task.id,
            changed_fields=["user_id"] if user_id is not None else ["group_id"],
        )
        return updated_task

    async def update_task(self, task_id: int, data, current_user: UserModel) -> SpisokModel:
        """Обновляет поля задачи с разграничением прав на дедлайн.

        Зачем: изменять дедлайн могут только автор, admin или manager —
        исполнитель не должен произвольно сдвигать срок.

        Side-effects:
            - При переходе в статус done (если он не был done) отправляет Telegram-уведомление
              автору задачи через _notify_task_done.
            - Инкрементирует Prometheus-счётчик tasks_completed при выполнении.
            - Пишет audit-лог.

        Raises:
            HTTPException 403: нет доступа к задаче или нет прав менять дедлайн.
            HTTPException 404: задача не найдена.
        """
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            task_not_found(TASK_NOT_FOUND)
        if not await can_edit_task(task, current_user, self.group_repo):
            await logger.awarning("no_access", user_id=current_user.id, task_id=task_id)
            no_access(NO_ACCESS)

        update_data = data.model_dump(exclude_unset=True)
        was_status = task.status

        if update_data.get("status") == TaskStatus.done and was_status != TaskStatus.done:
            await self._ensure_no_open_blockers(task_id)

        # Простые поля — обновляем через setattr (легко расширять)
        simple_fields = {
            "title",
            "description",
            "priority",
            "status",
            "recurrence_rule",
        }
        for field in simple_fields:
            if field in update_data:
                setattr(task, field, update_data[field])

        # completed_at — точная отметка перехода в done, для аналитики
        # "закрыто в срок". Обновляем ДО task_repo.update(), чтобы попало
        # в тот же commit. При переоткрытии (done -> другой статус) чистим.
        if "status" in update_data:
            if update_data["status"] == TaskStatus.done and was_status != TaskStatus.done:
                task.completed_at = datetime.now(timezone.utc)
            elif update_data["status"] != TaskStatus.done and was_status == TaskStatus.done:
                task.completed_at = None

        # Дедлайн — требует проверки прав и нормализации секунд
        if "deadline" in update_data:
            if update_data["deadline"] is None:
                task.deadline = None
            else:
                if not await can_update_task_deadline(task, current_user):
                    await logger.awarning(
                        "no_access",
                        user_id=current_user.id,
                        task_id=task_id,
                    )
                    no_access(NO_ACCESS)
                task.deadline = update_data["deadline"].replace(second=0, microsecond=0)

        updated_task = await self.task_repo.update(task)
        await logger.ainfo(
            "task_updated",
            task_id=updated_task.id,
            changed_fields=list(update_data.keys()),
        )
        if "status" in update_data and update_data["status"] == TaskStatus.done and was_status != TaskStatus.done:
            tasks_completed.inc()
            await self._notify_task_done(updated_task, current_user)
            await self._spawn_next_recurrence(updated_task)
        return updated_task

    async def delete_task(self, task_id: int, current_user: UserModel) -> dict:
        """Мягко удаляет задачу (soft delete): выставляет deleted_at.

        Зачем: задача не удаляется физически — она переходит в корзину,
        откуда её можно восстановить или удалить окончательно.

        Side-effects:
            - Вызывает task.soft_delete(session), который выставляет deleted_at = now().
            - Пишет audit-лог через session.info["audit_user_id"].
            - Инкрементирует Prometheus-счётчик tasks_deleted.

        Raises:
            HTTPException 403: не автор, не admin и не manager.
            HTTPException 404: задача не найдена.
        """
        task = await self.task_repo.get_by_id(task_id)
        if task is None:
            task_not_found(TASK_NOT_FOUND)
        if not can_delete_task(task, current_user):
            await logger.awarning("no_access", user_id=current_user.id, task_id=task_id)
            unauthorized_user(YOU_CANNOT_DELETE_TASK)
        if self.session is not None:
            self.session.info["audit_user_id"] = current_user.id
        task.soft_delete(self.session)
        tasks_deleted.inc()
        await self.session.commit()
        await logger.ainfo("task_deleted", task_id=task_id, user_id=current_user.id)
        return {"message": f"Task {task_id} deleted"}

    async def restore_task(self, task_id: int, current_user: UserModel) -> SpisokModel:
        """Восстанавливает задачу из корзины: обнуляет deleted_at.

        Зачем: позволяет отменить случайное удаление без потери данных.

        Side-effects:
            - Вызывает task.restore(session), который сбрасывает deleted_at = NULL.
            - Пишет audit-лог.
            - Инкрементирует Prometheus-счётчик tasks_restored.

        Raises:
            HTTPException 403: нет прав на восстановление.
            HTTPException 404: задача не найдена (в том числе не в корзине).
        """
        task = await self.task_repo.get_by_id_include_deleted(task_id)
        if task is None:
            task_not_found(TASK_NOT_FOUND)
        if not can_delete_task(task, current_user):
            await logger.awarning("no_access", user_id=current_user.id, task_id=task_id)
            unauthorized_user(YOU_CANNOT_DELETE_TASK)
        if self.session is not None:
            self.session.info["audit_user_id"] = current_user.id
        task.restore(self.session)
        tasks_restored.inc()
        await self.session.commit()
        await logger.ainfo("task_restored", task_id=task_id, user_id=current_user.id)
        return task

    # ── Корзина ───────────────────────────────────────────────────────────────

    async def get_deleted_tasks(
        self,
        user: UserModel,
        offset: int,
        limit: int,
        search: str | None = None,
    ) -> tuple[list[SpisokModel], int]:
        """Возвращает удалённые задачи с учётом прав доступа.

        Зачем: admin/manager видят корзину всех пользователей,
        обычный пользователь — только свои задачи (автор или исполнитель).
        """
        is_admin = user.role in (UserRole.admin, UserRole.manager)
        return await self.task_repo.get_deleted_tasks_paginated(
            user_id=user.id,
            is_admin=is_admin,
            offset=offset,
            limit=limit,
            search=search,
        )

    async def hard_delete_task(self, task_id: int, current_user: UserModel) -> None:
        """Физически удаляет задачу из БД без возможности восстановления.

        Зачем: нужен когда данные должны быть полностью удалены
        (GDPR, cleanup устаревших записей).

        Side-effects:
            - Каскадно удаляет все комментарии к задаче (ON DELETE CASCADE в БД).
            - Пишет audit-лог с пометкой hard_delete=True.
            - Инкрементирует Prometheus-счётчик tasks_hard_deleted.

        Raises:
            HTTPException 403: нет прав.
            HTTPException 404: задача не найдена (включая уже удалённые).
        """
        task = await self.task_repo.get_by_id_include_deleted(task_id)
        if task is None:
            task_not_found(TASK_NOT_FOUND)
        if not can_delete_task(task, current_user):
            await logger.awarning("no_access", user_id=current_user.id, task_id=task_id)
            unauthorized_user(YOU_CANNOT_DELETE_TASK)
        if self.session is not None:
            self.session.info["audit_user_id"] = current_user.id
        await self.task_repo.hard_delete(task)
        tasks_hard_deleted.inc()
        await self.session.commit()

    # ── Вспомогательные ───────────────────────────────────────────────────────

    async def get_user_stats(self, pk: int) -> dict:
        """Возвращает агрегированную статистику задач пользователя.

        Зачем: используется в Telegram-боте и admin-панели для отображения
        дашборда пользователя без отдельного API-эндпоинта.
        """
        stats = await self.task_repo.get_assigned_tasks(pk)

        authored = await self.task_repo.get_created_tasks_stats(pk)
        recent_tasks = await self.task_repo.get_last_appointed_tasks(pk)
        total = stats.total or 0
        done = stats.done or 0
        return {
            "total": total,
            "done": done,
            "pending": stats.pending or 0,
            "percent": round((done / total * 100) if total > 0 else 0),
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status.value if t.status else "backlog",
                    "priority": t.priority,
                    "deadline": t.deadline.strftime("%d.%m.%Y") if t.deadline else None,
                    "created_at": (t.created_at.strftime("%d.%m.%Y") if t.created_at else None),
                }
                for t in recent_tasks
            ],
            "a_total": authored.total or 0,
            "a_done": authored.done or 0,
        }

    @staticmethod
    async def _notify_task_done(task, executor):
        """Уведомляет автора задачи о её выполнении.

        Зачем: автор должен знать, что исполнитель завершил работу.
        Не уведомляем, если автор и исполнитель — один человек.

        Side-effects:
            - Отправляет Telegram-сообщение. Ошибки отправки подавляются
              (pass в except), чтобы не ломать основной поток обновления задачи.
        """
        try:
            if not task.author or task.author.id == executor.id or not task.author.telegram_id:
                return
            from src.bot.setup import get_bot

            await get_bot().send_message(
                chat_id=task.author.telegram_id,
                text=f"✅ Задача выполнена!\n\n📋 <b>{task.title}</b>\n👤 Выполнил: {executor.username}",
                parse_mode="HTML",
            )
        except Exception:
            pass

    async def filter_tasks_paginated(
        self, user: UserModel, offset: int, limit: int, **filters
    ) -> tuple[list[SpisokModel], int]:
        """Возвращает (tasks, total) с применением фильтров.

        Зачем: единый метод пагинации задач для роутера.
        Делегирует валидацию фильтров в _validate_task_filters,
        а сам запрос — в репозиторий.

        target_user_id — если передан (страница профиля другого пользователя),
        фильтруем по НЕМУ, а не по текущему авторизованному user. Видимость
        задач в приложении общая для всей команды (см. filter_tasks в
        tasks_router), так что смотреть чужие задачи может кто угодно.
        """
        target_user_id = filters.pop("target_user_id", None)
        await self._validate_task_filters(
            filters.get("filter_user_group"),
            filters.get("group_id"),
        )
        return await self.task_repo.get_filtered_tasks_with_total(
            user_id=target_user_id or user.id,
            offset=offset,
            limit=limit,
            **filters,
        )

    # ── Канбан ────────────────────────────────────────────────────────────────

    async def get_kanban(
        self,
        current_user: UserModel,
        project_id: int | None = None,
        only_mine: bool = False,
        only_author: bool = False,
    ) -> dict:
        """Возвращает задачи, сгруппированные по статусам для канбан-доски.

        Один запрос к БД вместо пяти — важно для производительности.
        Если project_id задан — только задачи этого проекта.
        """
        tasks = await self.task_repo.get_kanban_tasks(
            user_id=current_user.id,
            project_id=project_id,
            only_mine=only_mine,
            only_author=only_author,
        )
        grouped: dict[str, list] = {
            "backlog": [],
            "todo": [],
            "in_progress": [],
            "review": [],
            "done": [],
        }
        for task in tasks:
            key = task.status.value if task.status else "todo"
            if key in grouped:
                grouped[key].append(task)
        return grouped

    # ── Календарь дедлайнов ──────────────────────────────────────────────────

    async def get_calendar_tasks(
        self,
        current_user: UserModel,
        date_from: datetime,
        date_to: datetime,
        project_id: int | None = None,
        only_mine: bool = False,
        only_author: bool = False,
    ) -> list[SpisokModel]:
        """Задачи с дедлайном в диапазоне [date_from, date_to) для месячного вида календаря."""
        return await self.task_repo.get_calendar_tasks(
            user_id=current_user.id,
            date_from=date_from,
            date_to=date_to,
            project_id=project_id,
            only_mine=only_mine,
            only_author=only_author,
        )

    async def update_task_status(
        self,
        task_id: int,
        new_status: TaskStatus,
        current_user: UserModel,
    ) -> SpisokModel:
        """Атомарная смена статуса задачи (перемещение между колонками канбана).

        Отдельный эндпоинт от update_task — потому что это именно
        канбан-операция, не частичное редактирование задачи.
        Обновляет completed_at при переходе в done/из done (см. update_task).
        """
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            task_not_found(TASK_NOT_FOUND)
        if not await can_edit_task(task, current_user, self.group_repo):
            await logger.awarning("no_access", user_id=current_user.id, task_id=task_id)
            no_access(NO_ACCESS)

        old_status = task.status

        if new_status == TaskStatus.done and old_status != TaskStatus.done:
            await self._ensure_no_open_blockers(task_id)

        task.status = new_status

        # Та же логика completed_at, что и в update_task — см. комментарий там
        if new_status == TaskStatus.done and old_status != TaskStatus.done:
            task.completed_at = datetime.now(timezone.utc)
        elif new_status != TaskStatus.done and old_status == TaskStatus.done:
            task.completed_at = None

        if self.session is not None:
            self.session.info["audit_user_id"] = current_user.id

        updated_task = await self.task_repo.update(task)

        await logger.ainfo(
            "task_status_changed",
            task_id=task_id,
            from_status=old_status,
            to_status=new_status,
            user_id=current_user.id,
        )
        if new_status == TaskStatus.done and old_status != TaskStatus.done:
            tasks_completed.inc()
            await self._notify_task_done(updated_task, current_user)
            await self._spawn_next_recurrence(updated_task)
        return updated_task

    async def _get_open_blockers(self, task_id: int) -> list[SpisokModel]:
        return await TaskDependencyRepository(self.session).get_open_blockers(task_id)

    async def _ensure_no_open_blockers(self, task_id: int) -> None:
        """Бросает 409, если у задачи есть незакрытые блокеры — вызывается перед любым переходом в done."""
        open_blockers = await self._get_open_blockers(task_id)
        if open_blockers:
            names = ", ".join(f"#{b.id} «{b.title}»" for b in open_blockers)
            task_blocked(f"Сначала закройте задачи, которые блокируют эту: {names}")

    async def add_dependency(self, task_id: int, blocker_task_id: int, current_user: UserModel) -> None:
        """
        Отмечает, что задача blocker_task_id должна закрыться раньше task_id
        ("task_id заблокирована blocker_task_id"). Проверяет права на обе
        задачи (нельзя без доступа к чужой задаче объявить её блокером своей —
        это создавало бы шум в чужом списке "заблокированных") и отсутствие
        цикла в графе зависимостей.
        """
        if task_id == blocker_task_id:
            incorrect_request("Задача не может блокировать сама себя")

        task = await self.task_repo.get_by_id(task_id)
        if not task:
            task_not_found(TASK_NOT_FOUND)
        blocker = await self.task_repo.get_by_id(blocker_task_id)
        if not blocker:
            task_not_found(TASK_NOT_FOUND)

        if not await can_edit_task(task, current_user, self.group_repo) or not await can_edit_task(
            blocker, current_user, self.group_repo
        ):
            await logger.awarning("no_access", user_id=current_user.id, task_id=task_id)
            no_access(NO_ACCESS)

        dep_repo = TaskDependencyRepository(self.session)
        if await dep_repo.get_dependency(blocker_task_id, task_id):
            incorrect_request("Такая зависимость уже добавлена")
        if await dep_repo.would_create_cycle(blocker_task_id, task_id):
            incorrect_request(
                f"Нельзя добавить: задача #{blocker_task_id} уже прямо или "
                f"косвенно зависит от #{task_id} — получился бы цикл, который "
                "никогда не удастся закрыть"
            )

        await dep_repo.add(blocker_task_id, task_id)
        await logger.ainfo("task_dependency_added", blocker_task_id=blocker_task_id, blocked_task_id=task_id)

    async def remove_dependency(self, task_id: int, blocker_task_id: int, current_user: UserModel) -> None:
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            task_not_found(TASK_NOT_FOUND)
        if not await can_edit_task(task, current_user, self.group_repo):
            no_access(NO_ACCESS)

        dep_repo = TaskDependencyRepository(self.session)
        dep = await dep_repo.get_dependency(blocker_task_id, task_id)
        if not dep:
            not_found("Такая зависимость не найдена")
        await dep_repo.remove(dep)
        await logger.ainfo("task_dependency_removed", blocker_task_id=blocker_task_id, blocked_task_id=task_id)

    async def get_dependencies(self, task_id: int, current_user: UserModel) -> TaskDependenciesSchema:
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            task_not_found(TASK_NOT_FOUND)
        if not await can_edit_task(task, current_user, self.group_repo):
            no_access(NO_ACCESS)

        dep_repo = TaskDependencyRepository(self.session)
        blockers = await dep_repo.get_blockers(task_id)
        blocked = await dep_repo.get_blocked(task_id)
        return TaskDependenciesSchema(
            blockers=[TaskRefSchema.model_validate(b) for b in blockers],
            blocked=[TaskRefSchema.model_validate(b) for b in blocked],
        )

    async def import_tasks(
        self,
        *,
        filename: str,
        content: bytes,
        current_user: UserModel,
        project_id: int | None = None,
    ) -> TaskImportSummary:
        """Пачечное создание задач из CSV/Excel — зеркально к export_tasks_csv.

        В отличие от add_task(), здесь НЕ проверяется "дедлайн не в прошлом" —
        типичный сценарий импорта это перенос исторических данных из другого
        трекера, где просроченные дедлайны — нормальное явление, а не ошибка.

        project_id, как и в add_task(), не проверяется на существование —
        поведение согласовано с текущим add_task(), где project_id тоже не
        валидируется через репозиторий проектов.

        Raises:
            HTTPException 400: неверный формат файла, нет колонки с названием,
                файл повреждён/пуст, либо строк больше лимита.
        """
        try:
            parsed = parse_import_file(filename, content)
        except TaskImportParseError as exc:
            incorrect_request(str(exc))

        tasks = [
            SpisokModel(
                title=row.title,
                author_id=current_user.id,
                project_id=project_id,
                deadline=row.deadline,
                priority=row.priority,
                status=TaskStatus.todo,
                recurrence_rule=RecurrenceRule.none,
            )
            for row in parsed.rows
        ]

        created = await self.task_repo.bulk_create(tasks)

        tasks_created.inc(len(created))
        await logger.ainfo(
            "tasks_imported",
            count=len(created),
            user_id=current_user.id,
            errors=len(parsed.errors),
            warnings=len(parsed.warnings),
        )

        return TaskImportSummary(
            created=len(created),
            errors=[TaskImportIssueSchema(row=e.row_number, message=e.message) for e in parsed.errors],
            warnings=[TaskImportIssueSchema(row=w.row_number, message=w.message) for w in parsed.warnings],
        )

    async def bulk_update_tasks(
        self,
        data: BulkTaskUpdate,
        current_user: UserModel,
    ) -> BulkTaskUpdateResult:
        """Массово меняет статус/приоритет/тег/исполнителя у пачки задач.

        Права проверяются НА КАЖДУЮ задачу отдельно (can_edit_task для
        status/priority/tag_id, can_reassign_task для user_id) — задачи без
        доступа не прерывают всю операцию, а попадают в result.skipped.
        Так же обрабатываются id, которых не существует или которые удалены.

        tag_id ДОБАВЛЯЕТ тег к существующим (не заменяет список тегов задачи).

        completed_at и tasks_completed обновляются по тем же правилам, что и в
        update_task() — переход в done проставляет метку и инкрементирует счётчик,
        выход из done её сбрасывает.

        Raises:
            HTTPException 404: ни одна из переданных задач не найдена, либо
                указан несуществующий tag_id или user_id.
        """
        tasks = await self.task_repo.get_by_ids(data.task_ids)

        found_ids = {t.id for t in tasks}
        skipped: list[int] = [tid for tid in data.task_ids if tid not in found_ids]

        if not tasks:
            task_not_found(TASK_NOT_FOUND)

        tag_model = None
        if data.tag_id is not None:
            tag_model = await self.tag_repo.get_by_id(data.tag_id)
            if tag_model is None:
                not_found(TAG_NOT_FOUND)

        needs_edit_check = data.status is not None or data.priority is not None or data.tag_id is not None
        needs_reassign_check = data.user_id is not None

        if data.user_id is not None and not await self.user_repo.get_by_id(data.user_id):
            not_found(USER_NOT_FOUND)

        to_persist: list[SpisokModel] = []
        became_done_count = 0

        for task in tasks:
            if needs_edit_check and not await can_edit_task(task, current_user, self.group_repo):
                skipped.append(task.id)
                continue
            if needs_reassign_check and not can_reassign_task(task, current_user):
                skipped.append(task.id)
                continue

            was_status = task.status

            if (
                data.status == TaskStatus.done
                and was_status != TaskStatus.done
                and await self._get_open_blockers(task.id)
            ):
                # В массовой операции не роняем весь запрос из-за одной
                # заблокированной задачи — как и с правами доступа выше,
                # такую задачу просто пропускаем (попадёт в skipped).
                skipped.append(task.id)
                continue

            if data.status is not None:
                task.status = data.status
                if data.status == TaskStatus.done and was_status != TaskStatus.done:
                    task.completed_at = datetime.now(timezone.utc)
                    became_done_count += 1
                elif data.status != TaskStatus.done and was_status == TaskStatus.done:
                    task.completed_at = None

            if data.priority is not None:
                task.priority = data.priority

            if tag_model is not None and tag_model not in task.tags:
                task.tags.append(tag_model)

            if data.user_id is not None:
                task.user_id = data.user_id
                task.group_id = None

            to_persist.append(task)

        updated = await self.task_repo.bulk_update(to_persist)

        if became_done_count:
            tasks_completed.inc(became_done_count)

        await logger.ainfo(
            "tasks_bulk_updated",
            user_id=current_user.id,
            requested=len(data.task_ids),
            updated=len(updated),
            skipped=len(skipped),
        )

        return BulkTaskUpdateResult(updated=len(updated), skipped=skipped)
