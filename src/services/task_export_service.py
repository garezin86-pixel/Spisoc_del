# src/services/task_export_service.py
import csv
import io
from datetime import datetime

from src.core.task_labels import PRIORITY_LABELS, RECURRENCE_LABELS, STATUS_LABELS
from src.models.task import TaskStatus
from src.models.user import UserModel, UserRole
from src.repositories.abstract import AbstractTaskRepository
from src.schemas.task import FilterUserGroup, TaskPriorityFilter

CSV_HEADER = [
    "ID",
    "Название",
    "Описание",
    "Статус",
    "Приоритет",
    "Автор",
    "Исполнитель",
    "Группа",
    "Проект",
    "Дедлайн",
    "Создано",
    "Теги",
    "Повторение",
]


class TaskExportService:
    """
    Экспорт задач в CSV — для отчётности (по проекту, по периоду).

    ВАЖНО про видимость: в отличие от /tasks/filter (который отдаёт видимость
    целиком на откуп параметру filter_user_group, присылаемому клиентом —
    фронтенд просто всегда сам подставляет "user" для обычных пользователей,
    но backend это никак не проверяет), здесь роль пользователя проверяется
    на сервере. Обычный пользователь (role=user) не может через прямой вызов
    API получить чужие задачи в выгрузке, даже если явно передаст другой
    filter_user_group —serverside эта попытка игнорируется и подменяется на
    "user" принудительно.
    """

    def __init__(self, task_repo: AbstractTaskRepository):
        self.task_repo = task_repo

    async def export_tasks_csv(
        self,
        current_user: UserModel,
        *,
        project_id: int | None = None,
        status: TaskStatus | None = None,
        priority: TaskPriorityFilter | None = None,
        tag_id: int | None = None,
        deadline_from: datetime | None = None,
        deadline_to: datetime | None = None,
    ) -> str:
        # Обычный пользователь всегда видит только свои задачи в экспорте,
        # независимо от того, что бы он ни попытался передать в запросе.
        filter_user_group = None if current_user.role in (UserRole.admin, UserRole.manager) else FilterUserGroup.user

        tasks = await self.task_repo.export_tasks(
            user_id=current_user.id,
            filter_user_group=filter_user_group,
            project_id=project_id,
            status=status,
            priority=priority,
            tag_id=tag_id,
            deadline_from=deadline_from,
            deadline_to=deadline_to,
        )

        buffer = io.StringIO()
        # excel предпочитает ; как разделитель при локали ru_RU — но реальный
        # запятая-разделённый CSV (стандартный) совместим шире (Google Sheets,
        # pandas, импорт в другие системы). Оставляем запятую как разделитель.
        writer = csv.writer(buffer, delimiter=",", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(CSV_HEADER)

        for task in tasks:
            writer.writerow(
                [
                    task.id,
                    task.title,
                    (task.description or "").replace("\n", " ").replace("\r", ""),
                    STATUS_LABELS.get(task.status.value if hasattr(task.status, "value") else task.status, task.status),
                    PRIORITY_LABELS.get(
                        task.priority.value if hasattr(task.priority, "value") else task.priority, task.priority
                    ),
                    task.author.username if task.author else "",
                    task.user.username if task.user else "",
                    task.group.name if task.group else "",
                    task.project.name if task.project else "",
                    task.deadline.strftime("%d.%m.%Y %H:%M") if task.deadline else "",
                    task.created_at.strftime("%d.%m.%Y %H:%M") if task.created_at else "",
                    ", ".join(t.name for t in (task.tags or [])),
                    RECURRENCE_LABELS.get(
                        task.recurrence_rule.value if hasattr(task.recurrence_rule, "value") else task.recurrence_rule,
                        "",
                    ),
                ]
            )

        # BOM — чтобы Excel на Windows не показывал кракозябры вместо кириллицы
        return "\ufeff" + buffer.getvalue()
