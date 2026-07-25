import structlog
import wtforms
from fastapi import Request
from fastapi.responses import RedirectResponse
from markupsafe import Markup
from sqladmin import ModelView, expose
from sqlalchemy.ext.asyncio import async_sessionmaker
from wtforms.validators import EqualTo, Length, Optional

from src.admin.utils.formatters import active_badge
from src.admin.utils.url_helpers import URLS, task_urls, user_urls
from src.core.exceptions import (
    incorrect_request,
    invalid_id_response,
    user_not_found_response,
)
from src.core.metrics import users_registered
from src.models import UserModel
from src.models.user import UserRole
from src.repositories.groups_repository import GroupRepository
from src.repositories.tag_repository import TagRepository
from src.repositories.task_repository import TaskRepository
from src.repositories.users_repository import UserRepository
from src.services.task_service import TaskService

logger = structlog.get_logger()


class UserAdmin(ModelView, model=UserModel):
    name = "Пользователь"
    name_plural = "Пользователи"
    icon = "fa-solid fa-user"
    identity = "user-model"
    url_path = "user-model"

    _session_maker: async_sessionmaker

    column_list = [
        UserModel.id,
        UserModel.username,
        UserModel.role,
        UserModel.is_active,
        "toggle_btn",
        "stats_btn",
    ]
    column_searchable_list = [UserModel.username, UserModel.role]
    column_sortable_list = [
        UserModel.id,
        UserModel.username,
        UserModel.role,
        UserModel.is_active,
    ]
    column_default_sort = [(UserModel.id, False)]

    column_details_list = [
        UserModel.id,
        UserModel.username,
        UserModel.role,
        UserModel.is_active,
        UserModel.groups,
        UserModel.assigned_tasks,
        UserModel.authored_tasks,
    ]

    # ← добавили comments и groups — убирает лишние поля из формы
    form_excluded_columns = [
        UserModel.password_hash,
        UserModel.assigned_tasks,
        UserModel.authored_tasks,
        UserModel.comments,
        UserModel.groups,
        UserModel.notification_settings,  # ← добавить
        UserModel.notification_logs,
        UserModel.projects,
        UserModel.owned_projects,
    ]

    form_widget_args = {"telegram_id": {"readonly": True}}

    # ← добавили manager
    form_args = {
        "role": {
            "label": "Роль",
            "choices": [
                (UserRole.user, "Пользователь"),
                (UserRole.manager, "Менеджер"),
                (UserRole.admin, "Администратор"),
            ],
        },
    }

    column_labels = {
        "id": "ID",
        "username": "Имя пользователя",
        "role": "Роль",
        "is_active": "Активен",
        "groups": "Группы",
        "assigned_tasks": "Назначенные задачи",
        "authored_tasks": "Созданные задачи",
        "toggle_btn": "Статус",
        "stats_btn": "Статистика",
    }

    column_formatters = {
        UserModel.role: lambda m, a: {
            "admin": "Администратор",
            "manager": "Менеджер",
            "user": "Пользователь",
        }.get(str(m.role).replace("UserRole.", ""), m.role),
        "toggle_btn": lambda m, a: Markup(
            f'<a href="{URLS["user"]["toggle"]}{m.id}" '
            f'style="display:inline-block; padding:3px 10px; border-radius:4px; '
            f"font-size:12px; text-decoration:none; color:#fff; "
            f'background:{"#198754" if not m.is_active else "#dc3545"};">'
            f"{'Включить ✓' if not m.is_active else 'Отключить ✗'}</a>"
        ),
        "stats_btn": lambda m, a: Markup(
            f'<a href="{URLS["user"]["stats"]}{m.id}" '
            f'style="display:inline-block; padding:3px 10px; border-radius:4px; '
            f'font-size:12px; text-decoration:none; color:#fff; background:#0d6efd;">'
            f"📊 Статистика</a>"
        ),
    }

    column_formatters_detail = {
        UserModel.role: lambda m, a: {
            "admin": "Администратор",
            "manager": "Менеджер",
            "user": "Пользователь",
        }.get(str(m.role).replace("UserRole.", ""), str(m.role)),
    }

    form_overrides = {
        "role": wtforms.SelectField,
    }

    async def scaffold_form(self, rules=None):
        form_class = await super().scaffold_form(rules)
        form_class.password = wtforms.PasswordField("Пароль", validators=[Optional(), Length(min=6)])
        form_class.password_confirm = wtforms.PasswordField(
            "Повторите пароль",
            validators=[Optional(), EqualTo("password", message="Пароли не совпадают")],
        )
        return form_class

    async def on_model_change(self, data: dict, model: UserModel, is_created: bool, request):
        password = data.pop("password", None)
        password_confirm = data.pop("password_confirm", None)

        if password:
            if password != password_confirm:
                incorrect_request("Пароли не совпадают")
            from src.core.security import hash_password

            data["password_hash"] = hash_password(password)
        elif is_created:
            raise ValueError("Пароль обязателен при создании пользователя")

    async def after_model_change(self, data: dict, model: UserModel, is_created: bool, request):
        await logger.ainfo(
            "user_created" if is_created else "user_updated",
            user_id=model.id,
            admin_id=request.session.get("admin_id"),
        )
        if is_created:
            users_registered.inc()  # 👈

    async def delete_model(self, request: Request, pk: str):
        result = await super().delete_model(request, pk)
        await logger.ainfo(
            "user_deleted",
            user_id=int(pk),
            admin_id=request.session.get("admin_id"),
        )
        return result

    @expose("/toggle-active/{pk}")
    async def toggle_active(self, request: Request):
        pk = request.path_params.get("pk")
        if not pk or not pk.isdigit():
            return invalid_id_response()
        pk = int(pk)
        async with self._session_maker() as session:
            repo = UserRepository(session)
            user = await repo.get_by_id(pk)
            if user:
                user.is_active = not user.is_active
                await session.commit()
        return RedirectResponse(URLS["user"]["list"], status_code=303)

    @expose("/stats/{pk}")
    async def user_stats(self, request: Request):
        pk = request.path_params.get("pk")
        if not pk or not pk.isdigit():
            return invalid_id_response()
        pk = int(pk)
        async with self._session_maker() as session:
            user_repo = UserRepository(session)
            user = await user_repo.get_by_id(pk)
            if not user:
                user_not_found_response()
            task_service = TaskService(
                task_repo=TaskRepository(session),
                user_repo=UserRepository(session),
                group_repo=GroupRepository(session),
                tag_repo=TagRepository(session),
                session=session,  # передаём для возможных дополнительных запросов внутри сервиса
            )
            stats = await task_service.get_user_stats(pk)
        return await self.templates.TemplateResponse(
            request,
            "admin/user_stats.html",
            {
                "request": request,
                "urls": user_urls(request, pk),
                "task_urls": task_urls(request),
                "user": user,
                "active_badge": active_badge(user),
                **stats,
            },
        )
