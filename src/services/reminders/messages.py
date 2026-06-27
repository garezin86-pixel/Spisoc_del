from src.utils.datetime_utils import to_local


def format_deadline(task, fmt: str = "%d.%m.%Y %H:%M") -> str:
    return to_local(task.deadline) if task.deadline else "—"


def deadline_24h_text(task) -> str:
    return (
        f"⏰ Напоминание: задача «{task.title}»\n"
        f"Дедлайн через ~24 часа: {format_deadline(task)}"
    )


def deadline_1h_text(task) -> str:
    return (
        f"🔔 Задача «{task.title}» истекает через ~1 час!\n"
        f"Дедлайн: {format_deadline(task)}"
    )


def overdue_text(task) -> str:
    return f"❗ Задача «{task.title}» просрочена!\nДедлайн был: {format_deadline(task)}"


def weekly_report_text(upcoming, overdue) -> str:
    lines = ["📋 Ваш еженедельный отчёт:\n"]

    if overdue:
        lines.append(f"⚠️ Просрочено: {len(overdue)}")
        for task in overdue[:5]:
            lines.append(f"  • {task.title}")
        if len(overdue) > 5:
            lines.append(f"  … и ещё {len(overdue) - 5}")

    if upcoming:
        lines.append(f"\n📅 На этой неделе: {len(upcoming)}")
        for task in upcoming[:5]:
            lines.append(f"  • {task.title} ({format_deadline(task, '%d.%m')})")
        if len(upcoming) > 5:
            lines.append(f"  … и ещё {len(upcoming) - 5}")

    if not overdue and not upcoming:
        lines.append("✅ Нет задач на ближайшую неделю. Отличная работа!")

    return "\n".join(lines)


def group_assigned_text(group_name: str) -> str:
    return (
        f"👥 Вы назначены на группу «{group_name}»\n"
        "Теперь вы будете получать задачи из этой группы."
    )
