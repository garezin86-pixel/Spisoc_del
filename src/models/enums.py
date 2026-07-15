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


class RecurrenceRule(str, Enum):
    """Правило повторения задачи. Пока намеренно упрощено (без полного RRULE):
    покрывает 90% реальных случаев ("каждый день/неделю/месяц"), а не
    произвольные комбинации дней недели/интервалов — это сильно проще
    в реализации и достаточно для команды из нескольких человек."""

    none = "none"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
