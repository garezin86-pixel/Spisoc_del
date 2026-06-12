from sqladmin import Admin
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.admin.views.admin_auth import AdminAuth
from src.admin.views.comment_admin import CommentAdmin
from src.admin.views.group_admin import GroupAdmin
from src.admin.views.notification_view import NotificationLogAdmin
from src.admin.views.task_admin import TaskAdmin
from src.admin.views.trash_admin import TrashTaskAdmin
from src.admin.views.user_admin import UserAdmin
from src.admin.views.project_admin import ProjectAdmin
from src.core.config import ADMIN_SECRET_KEY
from src.admin.views.stats_view import StatsView
from src.admin.views.status_view import StatusView
from src.admin.views.notification_stats_view import NotificationStatsView

from src.db import get_session_maker


def setup_admin(app, engine):
    app.add_middleware(SessionMiddleware, secret_key=ADMIN_SECRET_KEY)
    _session_maker: async_sessionmaker  # ← атрибут класса
    session_maker = get_session_maker()
    assert ADMIN_SECRET_KEY is not None

    admin = Admin(
        app,
        engine,
        title="Список дел — Админка",
        authentication_backend=AdminAuth(
            secret_key=ADMIN_SECRET_KEY, session_maker=session_maker
        ),
        templates_dir="src/templates",
    )

    admin.templates.env.globals["admin_urls"] = {
        "user_list": "/admin/user-model/list",
        "user_stats": "/admin/user-model/stats/",
        "user_toggle": "/admin/user-model/toggle-active/",
    }
    UserAdmin._session_maker = session_maker  # ← до регистрации
    admin.add_view(UserAdmin)
    admin.add_view(TaskAdmin)
    admin.add_view(ProjectAdmin)
    admin.add_view(GroupAdmin)
    admin.add_view(CommentAdmin)
    admin.add_view(NotificationLogAdmin)

    StatsView._session_maker = session_maker
    StatusView._session_maker = session_maker
    NotificationStatsView._session_maker = session_maker

    admin.add_base_view(NotificationStatsView)
    admin.add_base_view(StatsView)
    admin.add_base_view(StatusView)
    admin.add_view(TrashTaskAdmin)
