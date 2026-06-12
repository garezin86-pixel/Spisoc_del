import asyncio
import structlog
from fastapi import Request
from sqladmin import ModelView, action
from markupsafe import Markup
from sqladmin import expose
from fastapi.responses import RedirectResponse
from zoneinfo import ZoneInfo
from typing import Any, List, Tuple, Optional
from sqlalchemy import Select, select
from sqlalchemy.orm import selectinload
from sqladmin.filters import BooleanFilter
from sqladmin.filters import ForeignKeyFilter
from sqlalchemy.orm import object_session

from src.admin.utils.url_helpers import URLS
from src.core.exceptions import incorrect_valueerror
from src.models import UserModel, SpisokModel, GroupModel
from src.services.notifications import (
    notify_comment_added,
    notify_task_assigned,
    notify_task_updated,
)
from src.utils.datetime_utils import to_local
from src.db.unit_of_work import UnitOfWork
from src.db import get_session_maker
from src.services.task_admin_service import task_admin_service
from src.core.metrics import tasks_created

LOCAL_TZ = ZoneInfo("Europe/Kiev")
logger = structlog.get_logger()


# Иконки для типов действий
_ACTION_ICONS = {
    "create": ("🟢", "#198754"),
    "update": ("🔵", "#0d6efd"),
    "delete": ("🔴", "#dc3545"),
    "restore": ("🟡", "#ffc107"),
}

# Человекочитаемые названия полей
_FIELD_LABELS = {
    "title": "Название",
    "description": "Описание",
    "is_done": "Выполнено",
    "user_id": "Исполнитель (ID)",
    "group_id": "Группа (ID)",
    "deadline": "Дедлайн",
    "deleted_at": "Удалено",
    "priority": "Приоритет",
}


def _render_audit_history(audit_entries: list) -> Markup:
    """Рендерит HTML-таблицу истории изменений для карточки задачи."""
    if not audit_entries:
        return Markup(
            '<p style="color:#6c757d; font-style:italic;">История изменений пуста</p>'
        )

    rows = []
    for entry in audit_entries:
        icon, color = _ACTION_ICONS.get(entry.action.value, ("⚪", "#6c757d"))

        # Формируем описание изменений
        changes_html = ""
        if entry.action.value == "update" and entry.old_values and entry.new_values:
            parts = []
            for key in entry.new_values:
                label = _FIELD_LABELS.get(key, key)
                old = entry.old_values.get(key, "—")
                new = entry.new_values.get(key, "—")
                parts.append(
                    f'<span style="color:#6c757d">{label}:</span> '
                    f'<span style="text-decoration:line-through;color:#dc3545">{old}</span>'
                    f' → <span style="color:#198754">{new}</span>'
                )
            changes_html = " &nbsp;|&nbsp; ".join(parts)
        elif entry.action.value == "create":
            changes_html = '<span style="color:#198754">Задача создана</span>'
        elif entry.action.value == "delete":
            changes_html = '<span style="color:#dc3545">Задача удалена (мягко)</span>'
        elif entry.action.value == "restore":
            changes_html = '<span style="color:#ffc107">Задача восстановлена</span>'

        changed_at = to_local(entry.changed_at) if entry.changed_at else "—"
        if entry.user_id and hasattr(entry, "user") and entry.user:
            user_info = entry.user.username
        elif entry.user_id:
            user_info = f"user #{entry.user_id}"
        else:
            user_info = "система"

        rows.append(f"""
            <tr>
                <td style="white-space:nowrap; padding:4px 8px;">
                    <span style="color:{color}">{icon}</span>
                    <strong>{entry.action.value}</strong>
                </td>
                <td style="padding:4px 8px; font-size:12px;">{changes_html}</td>
                <td style="white-space:nowrap; padding:4px 8px; color:#6c757d; font-size:12px;">
                    {user_info}
                </td>
                <td style="white-space:nowrap; padding:4px 8px; color:#6c757d; font-size:12px;">
                    {changed_at}
                </td>
            </tr>
        """)

    rows_html = "\n".join(rows)
    return Markup(f"""
        <div style="margin-top:8px;">
            <table style="width:100%; border-collapse:collapse; font-size:13px;">
                <thead>
                    <tr style="background:#f8f9fa; border-bottom:2px solid #dee2e6;">
                        <th style="padding:6px 8px; text-align:left;">Действие</th>
                        <th style="padding:6px 8px; text-align:left;">Изменения</th>
                        <th style="padding:6px 8px; text-align:left;">Кто</th>
                        <th style="padding:6px 8px; text-align:left;">Когда</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    """)


async def _fetch_audit_entries(task_id: int) -> list:
    return await task_admin_service.fetch_audit_entries(task_id)


def _format_audit_history(model: SpisokModel, attr: str) -> Markup:
    """Синхронная обёртка для получения audit_log записей."""
    try:
        loop = asyncio.get_event_loop()
        future = asyncio.run_coroutine_threadsafe(_fetch_audit_entries(model.id), loop)
        entries = future.result(timeout=5)
    except Exception as e:
        return Markup(
            f'<span style="color:#dc3545">Ошибка загрузки истории: {e}</span>'
        )
    return _render_audit_history(entries)


class AssignmentFilter:
    has_operator = False
    title = "Назначение"
    parameter_name = "assignment"

    def __init__(
        self,
        column: Optional[Any] = None,
        title: Optional[str] = None,
        parameter_name: Optional[str] = None,
    ):
        self.column = column
        if title:
            self.title = title
        if parameter_name:
            self.parameter_name = parameter_name

    async def lookups(self, request, model, run_query) -> List[Tuple[str, str]]:
        return [
            ("all", "Все"),
            ("user", "Назначено на пользователя"),
            ("group", "Назначено на группу"),
            ("none", "Не назначено"),
        ]

    async def get_filtered_query(self, query: Select, value: Any, model: Any) -> Select:
        if value == "user":
            return query.filter(model.user_id.isnot(None))
        elif value == "group":
            return query.filter(model.group_id.isnot(None))
        elif value == "none":
            return query.filter(model.user_id.is_(None), model.group_id.is_(None))
        return query


class TaskAdmin(ModelView, model=SpisokModel):
    identity = "spisok-model"
    name = "Задача"
    name_plural = "Задачи"
    icon = "fa-solid fa-list-check"

    show_deleted = False

    column_list = [
        SpisokModel.id,
        SpisokModel.title,
        SpisokModel.is_done,
        SpisokModel.author_id,
        SpisokModel.user_id,
        SpisokModel.group_id,
        SpisokModel.priority,
        SpisokModel.deadline,
    ]
    column_searchable_list = [SpisokModel.title, SpisokModel.is_done]

    column_filters = [
        AssignmentFilter(),
        ForeignKeyFilter(
            SpisokModel.user_id, UserModel.username, title="Назначено на пользователя"
        ),
        ForeignKeyFilter(
            SpisokModel.group_id, GroupModel.name, title="Назначено на группу"
        ),
        BooleanFilter(column=SpisokModel.is_done),
    ]

    column_sortable_list = [
        SpisokModel.title,
        SpisokModel.is_done,
        SpisokModel.author_id,
        SpisokModel.user_id,
        SpisokModel.group_id,
        SpisokModel.priority,
        SpisokModel.deadline,
    ]
    column_default_sort = [(SpisokModel.created_at, True)]

    form_excluded_columns = [
        SpisokModel.author_id,
        SpisokModel.author,
        SpisokModel.comments,
        SpisokModel.created_at,
        SpisokModel.updated_at,
        SpisokModel.notification_logs,
        SpisokModel.reminder_sent,
        SpisokModel.deleted_at,
    ]

    column_details_list = [
        SpisokModel.id,
        SpisokModel.title,
        SpisokModel.description,
        SpisokModel.is_done,
        SpisokModel.user,
        SpisokModel.group,
        SpisokModel.project,
        SpisokModel.author,
        SpisokModel.priority,
        SpisokModel.deadline,
        SpisokModel.created_at,
        SpisokModel.updated_at,
        SpisokModel.comments,
        "comment",
        "audit_history",  # ← история изменений
    ]

    column_labels = {
        "id": "ID",
        "title": "Название",
        "description": "Описание",
        "is_done": "Выполнено",
        "user": "Пользователь",
        "group": "Группа",
        "project": "Проект",
        "author": "Автор",
        "deadline": "Дедлайн",
        "priority": "Приоритет",
        "created_at": "Добавлено",
        "updated_at": "Изменено",
        "comments": "Комментарии",
        "name": "Название",
        "users": "Пользователи",
        "tasks": "Задачи",
        "comment": " ",
        "audit_history": "История изменений",
    }

    column_formatters = {
        SpisokModel.deadline: lambda m, a: to_local(m.deadline),
        SpisokModel.created_at: lambda m, a: to_local(m.created_at),
        SpisokModel.updated_at: lambda m, a: to_local(m.updated_at),
    }

    column_formatters_detail = {
        SpisokModel.deadline: lambda m, a: to_local(m.deadline),
        SpisokModel.created_at: lambda m, a: to_local(m.created_at),
        SpisokModel.updated_at: lambda m, a: to_local(m.updated_at),
        "comment": lambda m, a: Markup(
            f'<a href="{URLS["task"]["create"]}{m.id}" '
            f'style="display:inline-block; margin-top:8px; padding:4px 12px; '
            f"background:#0d6efd; color:#fff; border-radius:4px; "
            f'text-decoration:none; font-size:13px;">'
            f"+ Добавить комментарий</a>"
        ),
        # ── История аудита ────────────────────────────────────────────────────
        # Форматтер получает объект задачи (m) и синхронно возвращает Markup.
        # Записи audit_log подгружаются отдельным синхронным запросом через
        # run_sync, чтобы не ломать синхронный интерфейс sqladmin formatters.
    }

    form_args = {
        "user": {
            "description": "Выберите пользователя, если задача для конкретного человека"
        },
        "group": {"description": "Выберите группу, если задача для группы"},
        "priority": {"description": "Выберите приоритет задачи"},
    }

    form_widget_args = {
        "deadline": {"type": "datetime-local"},
    }

    @expose("/comment/create", methods=["GET", "POST"])
    async def create_comment(self, request):
        if request.method == "GET":
            task_id = request.query_params.get("task_id")
            return await self.templates.TemplateResponse(
                request, "admin/comment_create.html", {"task_id": task_id}
            )

        form = await request.form()
        task_id = form.get("task_id")
        content = form.get("content")
        user_id = request.session.get("admin_id")

        async with UnitOfWork(get_session_maker()) as uow:
            comment = await uow.tasks.add_comment(task_id, user_id, content)
            await notify_comment_added(comment.id)
            await logger.ainfo(
                "create_comment",
                task_id=int(task_id),
                admin_id=user_id,
                comment_id=comment.id,
            )

        return RedirectResponse(f"{URLS['task']['details']}{task_id}", status_code=303)

    async def get_object_for_edit(self, request: Request):
        model = await super().get_object_for_edit(request)
        if model and model.deadline:
            from datetime import timezone

            if model.deadline.tzinfo is not None:
                model.deadline = model.deadline.astimezone(LOCAL_TZ).replace(
                    tzinfo=None
                )
            else:
                model.deadline = (
                    model.deadline.replace(tzinfo=timezone.utc)
                    .astimezone(LOCAL_TZ)
                    .replace(tzinfo=None)
                )
        return model

    async def on_model_change(self, data, model, is_created, request):
        admin_id = request.session.get("admin_id")
        if admin_id:
            session = object_session(model)
            if session:
                session.info["audit_user_id"] = admin_id

        user = data.get("user")
        group = data.get("group")

        if user and group:
            return incorrect_valueerror(
                "Нельзя назначать задачу одновременно пользователю и группе!"
            )

        if is_created and "admin_id" in request.session:
            model.author_id = request.session["admin_id"]

        if "deadline" in data and data["deadline"] is not None:
            dl = data["deadline"]
            if dl.tzinfo is None:
                data["deadline"] = dl.replace(tzinfo=LOCAL_TZ)

        if not is_created:
            watched = [
                "title",
                "description",
                "deadline",
                "is_done",
                "user_id",
                "group_id",
            ]
            changed = {}
            for field in watched:
                old_val = getattr(model, field, None)

                if field == "user_id":
                    new_obj = data.get("user")
                    if new_obj is None:
                        new_val = None
                    elif hasattr(new_obj, "id"):
                        new_val = new_obj.id
                    else:
                        new_val = int(new_obj) if str(new_obj).isdigit() else None
                elif field == "group_id":
                    new_obj = data.get("group")
                    if new_obj is None:
                        new_val = None
                    elif hasattr(new_obj, "id"):
                        new_val = new_obj.id
                    else:
                        new_val = int(new_obj) if str(new_obj).isdigit() else None
                else:
                    new_val = data.get(field)

                if old_val != new_val:
                    changed[field] = new_val

            request.state.changed_fields = changed
            await logger.ainfo(
                "on_model_change",
                task_id=model.id,
                admin_id=admin_id,
                changed_fields=list(changed.keys()),
            )

    async def get_detail_value(self, obj: SpisokModel, prop: str):
        if prop == "audit_history":
            entries = await _fetch_audit_entries(obj.id)
            formatted = _render_audit_history(entries)
            return formatted, formatted
        return await super().get_detail_value(obj, prop)

    async def after_model_change(self, data, model, is_created, request):
        await logger.ainfo(
            "after_model_change",
            task_id=model.id,
            is_created=is_created,
        )
        if is_created:
            tasks_created.inc()  # 👈
            await notify_task_assigned(model.id)
        else:
            changed = getattr(request.state, "changed_fields", {})
            if changed:
                await notify_task_updated(model.id, changed)

    # ── Скрываем удалённые задачи из списка ───────────────────────────────
    def list_query(self, request: Request):
        """Показываем только не удалённые задачи (deleted_at IS NULL)."""
        return (
            select(SpisokModel)
            .where(SpisokModel.not_deleted_filter())
            .options(
                selectinload(SpisokModel.user),
                selectinload(SpisokModel.group),
                selectinload(SpisokModel.author),
            )
        )

    # ── Переопределяем кнопку 🗑 — делаем soft delete вместо физического ──
    async def delete_model(self, request: Request, pk: str):
        admin_id = request.session.get("admin_id")
        await task_admin_service.soft_delete(int(pk), admin_id)
        # tasks_deleted.inc()  # уже вызывается внутри task_admin_service.soft_delete 👈

    # ── Action: массовое мягкое удаление через Actions dropdown ───────────
    @action(
        name="soft-delete",
        label="Переместить в корзину",
        confirmation_message="Переместить выбранные задачи в корзину?",
        add_in_list=True,
        add_in_detail=False,
    )
    async def action_soft_delete(self, request: Request):
        pks_raw = request.query_params.get("pks", "")
        pks = [int(pk.strip()) for pk in pks_raw.split(",") if pk.strip()]
        admin_id = request.session.get("admin_id")
        await task_admin_service.bulk_soft_delete(pks, admin_id)
        return RedirectResponse(
            request.url_for("admin:list", identity="spisok-model"), status_code=302
        )
