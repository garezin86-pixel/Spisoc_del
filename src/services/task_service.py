import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.abstract import (
    AbstractTaskRepository,
    AbstractUserRepository,
    AbstractGroupRepository,
)
from src.models.task import SpisokModel
from src.models.user import UserModel, UserRole
from src.schemas.task import FilterUserGroup, SpisokAddSchema

from src.core.exceptions import (
    incorrect_request,
    not_found,
    task_not_found,
    unauthorized_user,
    user_not_found,
    no_access,
)
from src.core.constants import (
    ENTER_GROUP_ID,
    GROUP_NOT_FOUND,
    NO_ACCESS,
    TASK_NOT_FOUND,
    USER_ID_OR_GROUP_ID,
    USER_NOT_FOUND,
    YOU_CANNOT_DELETE_TASK,
)
from src.services.notifications import notify_task_assigned
from src.services.permissions import (
    can_edit_task,
    can_update_task_deadline,
    can_delete_task,
    can_reassign_task,
)
from src.core.metrics import (
    tasks_created,
    tasks_deleted,
    tasks_completed,
    tasks_hard_deleted,
    tasks_restored,
)

logger = structlog.get_logger()


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
        session: AsyncSession,
    ):
        self.task_repo = task_repo
        self.user_repo = user_repo
        self.group_repo = group_repo
        self.session = session

    async def add_task(
        self, data: SpisokAddSchema, current_user: UserModel
    ) -> SpisokModel:
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
            is_done=data.is_done,
            user_id=data.user_id,
            group_id=data.group_id,
            deadline=deadline,
            author_id=current_user.id,
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
            await notify_task_assigned(task.id)
        tasks_created.inc()
        return task

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
        current_user,
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

    async def get_task(self, task_id, current_user):
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

    async def reassign_task(self, task_id, current_user, user_id, group_id):
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

    async def update_task(self, task_id, data, current_user):
        """Обновляет поля задачи с разграничением прав на дедлайн.

        Зачем: изменять дедлайн могут только автор, admin или manager —
        исполнитель не должен произвольно сдвигать срок.

        Side-effects:
            - При переводе is_done=True (если было False) отправляет Telegram-уведомление
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
        was_done = task.is_done

        if "title" in update_data:
            task.title = update_data["title"]
        if "is_done" in update_data:
            task.is_done = update_data["is_done"]
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
        if "is_done" in update_data and update_data["is_done"] and not was_done:
            tasks_completed.inc()
            await self._notify_task_done(updated_task, current_user)
        return updated_task

    async def delete_task(self, task_id, current_user):
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

    async def get_user_stats(self, pk):
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
            "tasks": recent_tasks,
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
            if (
                not task.author
                or task.author.id == executor.id
                or not task.author.telegram_id
            ):
                return
            from src.bot.setup import get_bot

            await get_bot().send_message(
                chat_id=task.author.telegram_id,
                text=f"✅ Задача выполнена!\n\n📋 <b>{task.title}</b>\n👤 Выполнил: {executor.username}",
                parse_mode="HTML",
            )
        except Exception:
            pass

    async def filter_tasks_paginated(self, user, offset, limit, **filters):
        """Возвращает (tasks, total) с применением фильтров.

        Зачем: единый метод пагинации задач для роутера.
        Делегирует валидацию фильтров в _validate_task_filters,
        а сам запрос — в репозиторий.
        """
        await self._validate_task_filters(
            filters.get("filter_user_group"),
            filters.get("group_id"),
        )
        return await self.task_repo.get_filtered_tasks_with_total(
            user_id=user.id,
            offset=offset,
            limit=limit,
            **filters,
        )
