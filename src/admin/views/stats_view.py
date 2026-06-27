from fastapi import Request
from sqladmin import BaseView, expose
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.repositories.other_repositories import StatsRepository


class StatsView(BaseView):
    name = "📊 Статистика"
    icon = "fa fa-chart-bar"

    _session_maker: async_sessionmaker  # атрибут класса

    @expose("/stats", methods=["GET"])
    async def stats_page(self, request: Request):
        async with self._session_maker() as session:
            repo = StatsRepository(session)

            users_stats = await repo.get_users_stats()
            tasks_stats = await repo.get_tasks_stats()
            total_groups = await repo.get_groups_count()
            total_comments = await repo.get_comments_count()

        total_tasks = tasks_stats.total_tasks or 0
        done_tasks = tasks_stats.done_tasks or 0
        completion_rate = round((done_tasks / total_tasks * 100) if total_tasks > 0 else 0)

        return await self.templates.TemplateResponse(
            request,
            "admin/general_statistics.html",
            {
                "request": request,
                "total_users": users_stats.total_users or 0,
                "active_users": users_stats.active_users or 0,
                "admin_users": users_stats.admin_users or 0,
                "total_tasks": total_tasks,
                "done_tasks": done_tasks,
                "pending_tasks": tasks_stats.pending_tasks or 0,
                "completion_rate": completion_rate,
                "total_groups": total_groups,
                "total_comments": total_comments,
            },
        )
