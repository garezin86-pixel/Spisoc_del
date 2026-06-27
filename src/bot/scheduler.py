from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.utils.reminders import (
    notify_overdue,
    remind_deadline_1h,
    remind_deadline_24h,
    send_weekly_report,
)

scheduler = AsyncIOScheduler(timezone="UTC")


def setup_scheduler() -> AsyncIOScheduler:
    scheduler.add_job(remind_deadline_24h, "interval", minutes=10)
    scheduler.add_job(remind_deadline_1h, "interval", minutes=10)
    scheduler.add_job(notify_overdue, "interval", hours=1)
    scheduler.add_job(
        send_weekly_report,
        "cron",
        day_of_week="mon",
        hour=9,
        minute=0,
    )
    return scheduler
