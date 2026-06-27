import platform
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Request
from sqladmin import BaseView, expose
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.repositories.other_repositories import StatsRepository


class StatusView(BaseView):
    name = "🔄 Статус"
    icon = "fa fa-cog"

    _session_maker: async_sessionmaker

    @expose("/status", methods=["GET"])
    async def status_page(self, request: Request):
        try:
            import psutil

            psutil_available = True
        except ImportError:
            psutil = None  # 👈 явно None, линтер доволен
            psutil_available = False

        if psutil_available:
            import psutil

            system_info = {
                "os": platform.system(),
                "os_version": platform.release(),
                "python_version": platform.python_version(),
                "cpu_count": psutil.cpu_count(),
                "memory_total": round(psutil.virtual_memory().total / (1024**3), 2),
                "memory_used": round(psutil.virtual_memory().used / (1024**3), 2),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_total": round(psutil.disk_usage("/").total / (1024**3), 2),
                "disk_used": round(psutil.disk_usage("/").used / (1024**3), 2),
                "disk_percent": psutil.disk_usage("/").percent,
            }
        else:
            system_info = {
                "os": platform.system(),
                "os_version": platform.release(),
                "python_version": platform.python_version(),
                "cpu_count": "N/A",
                "memory_total": "N/A",
                "memory_used": "N/A",
                "memory_percent": 0,
                "disk_total": "N/A",
                "disk_used": "N/A",
                "disk_percent": 0,
            }

        db_status = "✅ Подключена"
        try:
            async with self._session_maker() as session:
                repo = StatsRepository(session)
                await repo.check_connection()
        except Exception as e:
            db_status = f"❌ Ошибка: {str(e)}"

        bot_status = "❌ Не запущен"  # ← добавили обратно
        try:
            from src.bot.setup import get_bot

            bot = get_bot()
            bot_status = "✅ Запущен" if bot else "❌ Не запущен"
        except Exception as e:
            bot_status = f"❌ Ошибка: {str(e)}"

        return await self.templates.TemplateResponse(
            request,
            "admin/status_system_admin.html",
            {
                "request": request,
                "system_info": system_info,
                "db_status": db_status,
                "bot_status": bot_status,
                "datetime_now": datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%d.%m.%Y %H:%M:%S"),
            },
        )
