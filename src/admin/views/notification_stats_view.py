# src/admin/views/notification_stats_view.py
from fastapi import Request
from sqladmin import BaseView, expose
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.repositories.other_repositories import NotificationRepository


class NotificationStatsView(BaseView):
    name = "🔔 Уведомления"
    icon = "fa fa-bell"

    _session_maker: async_sessionmaker

    @expose("/notification-stats", methods=["GET"])
    async def notification_stats_page(self, request: Request):
        async with self._session_maker() as session:
            repo = NotificationRepository(session)
            stats = await repo.get_admin_statistics()

        return await self.templates.TemplateResponse(
            request,
            "admin/notification_statistics.html",
            {
                "request": request,
                **stats,
            },
        )
