from datetime import timezone

from src.utils.datetime_utils import to_local


def format_deadline(task, fmt: str = "%d.%m.%Y %H:%M") -> str:
    return to_local(task.deadline) if task.deadline else "—"


def deadline_24h_text(task) -> str:
    return f"⏰ Напоминание: задача «{task.title}»\nДедлайн через ~24 часа: {format_deadline(task)}"


def deadline_1h_text(task) -> str:
    return f"🔔 Задача «{task.title}» истекает через ~1 час!\nДедлайн: {format_deadline(task)}"


def overdue_text(task) -> str:
    return f"❗ Задача «{task.title}» просрочена!\nДедлайн был: {format_deadline(task)}"


def contact_due_text(client, today) -> str:
    """Напоминание ответственному: пора связаться с клиентом (дата следующего контакта наступила)."""
    lines = [f"📞 Пора связаться с клиентом «{client.name}»"]
    late = (today - client.next_contact_at).days
    lines.append(
        f"Срок: {client.next_contact_at.strftime('%d.%m.%Y')}" + (f" (просрочено на {late} дн.)" if late > 0 else "")
    )
    if client.phone:
        lines.append(f"Телефон: {client.phone}")
    return "\n".join(lines)


def event_reminder_text(event, client_name: str, now) -> str:
    """Напоминание ответственному: встреча или звонок скоро начнётся."""
    icon, label = ("🤝", "Встреча") if event.type == "meeting" else ("📞", "Звонок")
    starts_at = event.starts_at if event.starts_at.tzinfo else event.starts_at.replace(tzinfo=timezone.utc)
    minutes = max(1, round((starts_at - now).total_seconds() / 60))
    lines = [f"{icon} {label} через {minutes} мин: {event.title or client_name}"]
    if event.title:
        lines.append(f"Клиент: {client_name}")
    lines.append(
        f"Начало: {to_local(event.starts_at)}" + (f", {event.duration_minutes} мин" if event.duration_minutes else "")
    )
    return "\n".join(lines)


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
    return f"👥 Вы назначены на группу «{group_name}»\nТеперь вы будете получать задачи из этой группы."
