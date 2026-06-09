import logging
import structlog
from datetime import datetime, timedelta, timezone

from src.bot.setup import get_bot
from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.services.reminders.messages import (
    deadline_1h_text,
    deadline_24h_text,
    group_assigned_text,
    overdue_text,
    weekly_report_text,
)
from src.services.reminders.sender import NotificationSender

logger = logging.getLogger(__name__)
event_logger = structlog.get_logger()

WINDOW = timedelta(minutes=10)


async def _log_notification(
    uow,
    *,
    user_id: int,
    notification_type: str,
    content: str,
    success: bool,
    error: str | None = None,
    task_id: int | None = None,
) -> None:
    await uow.notifications.create_log(
        user_id=user_id,
        notification_type=notification_type,
        task_id=task_id,
        content=content[:2000],
        success=success,
        error=error,
    )


async def _send_task_and_log(
    uow,
    sender: NotificationSender,
    user,
    task,
    notification_type: str,
    text: str,
) -> bool:
    success, error = await sender.send_task(
        user,
        task,
        text,
        notification_type=notification_type,
    )
    await _log_notification(
        uow,
        user_id=user.id,
        task_id=task.id,
        notification_type=notification_type,
        content=text,
        success=success,
        error=error,
    )
    return success


async def _send_plain_and_log(
    uow,
    sender: NotificationSender,
    user,
    notification_type: str,
    text: str,
) -> bool:
    success, error = await sender.send(user, text)
    await _log_notification(
        uow,
        user_id=user.id,
        notification_type=notification_type,
        content=text,
        success=success,
        error=error,
    )
    return success


async def _send_deadline_reminders(
    *,
    hours_before: int,
    notification_type: str,
    settings_field: str,
    message_factory,
) -> int:
    session_maker = get_session_maker()
    sender = NotificationSender(get_bot())
    sent = 0

    async with UnitOfWork(session_maker) as uow:
        now = datetime.now(timezone.utc)
        target = now + timedelta(hours=hours_before)
        tasks = await uow.tasks.get_tasks_by_deadline_window(
            target - WINDOW,
            target + WINDOW,
        )

        for task in tasks:
            user = task.user
            if not user or not user.telegram_id:
                continue

            settings = await uow.notification_settings.get_by_user(user.id)
            if settings and not getattr(settings, settings_field, True):
                continue

            if await uow.notifications.check_already_sent(
                user.id,
                task.id,
                notification_type,
            ):
                continue

            text = message_factory(task)
            await _send_task_and_log(uow, sender, user, task, notification_type, text)
            sent += 1

        await uow.commit()

    return sent


async def remind_deadline_24h() -> None:
    await event_logger.ainfo("reminder_job_started", type="deadline_24h")
    logger.info("Проверка дедлайнов (24 h)...")
    sent = await _send_deadline_reminders(
        hours_before=24,
        notification_type="deadline_24h",
        settings_field="notify_deadline_24h",
        message_factory=deadline_24h_text,
    )
    logger.info("deadline_24h: отправлено %d", sent)
    await event_logger.ainfo(
        "reminder_job_finished",
        type="deadline_24h",
        count=sent,
    )


async def remind_deadline_1h() -> None:
    await event_logger.ainfo("reminder_job_started", type="deadline_1h")
    logger.info("Проверка дедлайнов (1 h)...")
    sent = await _send_deadline_reminders(
        hours_before=1,
        notification_type="deadline_1h",
        settings_field="notify_deadline_1h",
        message_factory=deadline_1h_text,
    )
    logger.info("deadline_1h: отправлено %d", sent)
    await event_logger.ainfo(
        "reminder_job_finished",
        type="deadline_1h",
        count=sent,
    )


async def notify_overdue() -> None:
    await event_logger.ainfo("reminder_job_started", type="overdue")
    logger.info("Проверка просроченных задач...")
    session_maker = get_session_maker()
    sender = NotificationSender(get_bot())
    sent = 0

    async with UnitOfWork(session_maker) as uow:
        now = datetime.now(timezone.utc)
        tasks = await uow.tasks.get_overdue_tasks(now)

        for task in tasks:
            user = task.user
            if not user or not user.telegram_id:
                continue

            settings = await uow.notification_settings.get_by_user(user.id)
            if settings and not settings.notify_overdue:
                continue

            if await uow.notifications.check_already_sent(
                user.id,
                task.id,
                "overdue",
                hours_back=24,
            ):
                continue

            text = overdue_text(task)
            await _send_task_and_log(uow, sender, user, task, "overdue", text)
            sent += 1

        await uow.commit()

    logger.info("overdue: отправлено %d", sent)
    await event_logger.ainfo("reminder_job_finished", type="overdue", count=sent)


async def send_weekly_report() -> None:
    await event_logger.ainfo("reminder_job_started", type="weekly_report")
    logger.info("Отправка еженедельной сводки...")
    session_maker = get_session_maker()
    sender = NotificationSender(get_bot())
    sent = 0

    async with UnitOfWork(session_maker) as uow:
        users = await uow.notification_settings.get_users_with_weekly_report()

        for user in users:
            if not user.telegram_id:
                continue

            now = datetime.now(timezone.utc)
            week_end = now + timedelta(days=7)
            upcoming = await uow.tasks.get_tasks_by_deadline_window(
                now,
                week_end,
                user_id=user.id,
            )
            overdue = await uow.tasks.get_overdue_tasks(now, user_id=user.id)

            text = weekly_report_text(upcoming, overdue)
            await _send_plain_and_log(uow, sender, user, "weekly_report", text)
            sent += 1

        await uow.commit()

    logger.info("weekly_report: отправлено %d", sent)
    await event_logger.ainfo(
        "reminder_job_finished",
        type="weekly_report",
        count=sent,
    )


async def notify_group_assigned(user_id: int, group_id: int, group_name: str) -> None:
    logger.info(
        "Уведомление о назначении на группу: user=%s, group=%s", user_id, group_id
    )
    session_maker = get_session_maker()
    sender = NotificationSender(get_bot())

    async with UnitOfWork(session_maker) as uow:
        user = await uow.users.get_by_id(user_id)
        if not user or not user.telegram_id:
            logger.warning("User %s has no telegram_id", user_id)
            return

        settings = await uow.notification_settings.get_by_user(user.id)
        if settings and not getattr(settings, "notify_group_assigned", True):
            return

        if await uow.notifications.check_already_sent(
            user.id,
            None,
            "group_assigned",
            hours_back=1,
        ):
            return

        text = group_assigned_text(group_name)
        await _send_plain_and_log(uow, sender, user, "group_assigned", text)
        await uow.commit()
