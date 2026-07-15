# src/services/analytics_service.py
from collections import defaultdict

from src.repositories.abstract import AbstractTaskRepository


class AnalyticsService:
    """
    Простая бизнес-аналитика для менеджера/админа — поверх тех же данных,
    что уже есть в БД, без Grafana. Если понадобится больше — эти же цифры
    можно будет параллельно экспортировать в Prometheus как gauge-метрики,
    но пока это просто SQL-агрегаты (точнее, агрегаты в Python — см.
    комментарий в TaskRepository.get_tasks_for_analytics).
    """

    def __init__(self, task_repo: AbstractTaskRepository):
        self.task_repo = task_repo

    async def get_dashboard(self) -> dict:
        tasks = await self.task_repo.get_tasks_for_analytics()

        return {
            "executor_completion": self._executor_completion_stats(tasks),
            "project_overdue": self._project_overdue_stats(tasks),
        }

    @staticmethod
    def _executor_completion_stats(tasks) -> list[dict]:
        """Для каждого исполнителя: % задач, закрытых в срок (completed_at <= deadline)."""
        by_executor: dict[int, dict] = defaultdict(lambda: {"total": 0, "on_time": 0, "username": None})

        for task in tasks:
            if not task.user:
                continue  # задача без исполнителя — не относим ни к кому
            bucket = by_executor[task.user.id]
            bucket["username"] = task.user.username
            bucket["total"] += 1
            if task.completed_at <= task.deadline:
                bucket["on_time"] += 1

        result = []
        for user_id, bucket in by_executor.items():
            total = bucket["total"]
            on_time = bucket["on_time"]
            result.append(
                {
                    "user_id": user_id,
                    "username": bucket["username"],
                    "total_completed": total,
                    "on_time": on_time,
                    "late": total - on_time,
                    "on_time_rate": round(on_time / total * 100, 1) if total > 0 else 0,
                }
            )

        # Сортируем по проценту "в срок" по убыванию — лучшие исполнители сверху
        result.sort(key=lambda r: r["on_time_rate"], reverse=True)
        return result

    @staticmethod
    def _project_overdue_stats(tasks) -> list[dict]:
        """Для каждого проекта: средняя просрочка (в днях) среди задач, закрытых с опозданием.

        Проекты, где все задачи закрывались в срок, тоже попадают в
        результат — со средней просрочкой 0 и явным индикатором, чтобы
        менеджер видел "здесь всё хорошо", а не отсутствие данных.
        """
        by_project: dict[int, dict] = defaultdict(
            lambda: {"total": 0, "late": 0, "total_overdue_days": 0.0, "name": None}
        )

        for task in tasks:
            if not task.project:
                continue  # задача вне проекта — не относим ни к одному проекту
            bucket = by_project[task.project.id]
            bucket["name"] = task.project.name
            bucket["total"] += 1
            if task.completed_at > task.deadline:
                overdue_days = (task.completed_at - task.deadline).total_seconds() / 86400
                bucket["late"] += 1
                bucket["total_overdue_days"] += overdue_days

        result = []
        for project_id, bucket in by_project.items():
            late = bucket["late"]
            avg_overdue = round(bucket["total_overdue_days"] / late, 1) if late > 0 else 0.0
            result.append(
                {
                    "project_id": project_id,
                    "project_name": bucket["name"],
                    "total_completed": bucket["total"],
                    "completed_late": late,
                    "avg_overdue_days": avg_overdue,
                }
            )

        # Сортируем по средней просрочке по убыванию — самые проблемные проекты сверху
        result.sort(key=lambda r: r["avg_overdue_days"], reverse=True)
        return result
