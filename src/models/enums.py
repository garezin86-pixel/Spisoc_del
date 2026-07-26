from enum import Enum


class TaskPriority(str, Enum):
    """Приоритет задачи. Используется для сортировки и фильтрации."""

    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class TaskStatus(str, Enum):
    """Статус задачи для канбан-доски."""

    backlog = "backlog"  # Очередь
    todo = "todo"  # Новые
    in_progress = "in_progress"  # В работе
    review = "review"  # На проверке
    done = "done"  # Готово


class TemplateVisibility(str, Enum):
    private = "private"
    group = "group"
    global_ = "global"

    @classmethod
    def _missing_(cls, value):
        if value == "global":
            return cls.global_
        return None


class WebhookEvent(str, Enum):
    """
    События, на которые можно подписать исходящий вебхук.

    task_status_changed срабатывает на ЛЮБУЮ смену статуса, task_done —
    более узкое удобное событие конкретно для перехода в done (самый частый
    сценарий: "уведомить внешнюю систему, когда задача готова"). Оба
    срабатывают одновременно при переходе в done — подписчик выбирает,
    что ему удобнее слушать.
    """

    task_created = "task.created"
    task_updated = "task.updated"
    task_status_changed = "task.status_changed"
    task_done = "task.done"
    task_deleted = "task.deleted"
    comment_added = "comment.added"


class PatScope(str, Enum):
    """Область действия персонального access-токена (PAT).

    read_only  — токеном можно только читать (GET/HEAD/OPTIONS). Подходит
                 для разовых интеграций, которым нужно лишь забирать данные
                 (дашборд, экспорт в другую систему) — если такой токен
                 утечёт, им нельзя ничего изменить или удалить.
    read_write — токен может всё то же самое, что пользователь в вебе.
                 Управление самими PAT (создание/отзыв) всегда требует
                 read_write, независимо от эндпоинта — иначе read_only-токен
                 мог бы сам себе выписать полноправный токен и обойти
                 ограничение.
    """

    read_only = "read_only"
    read_write = "read_write"


class RecurrenceRule(str, Enum):
    """Правило повторения задачи. Пока намеренно упрощено (без полного RRULE):
    покрывает 90% реальных случаев ("каждый день/неделю/месяц"), а не
    произвольные комбинации дней недели/интервалов — это сильно проще
    в реализации и достаточно для команды из нескольких человек."""

    none = "none"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
