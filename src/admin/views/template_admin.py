from markupsafe import Markup
from sqladmin.filters import ForeignKeyFilter
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqladmin import ModelView, expose
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import RedirectResponse
from wtforms import SelectField

from src.admin.utils.url_helpers import URLS
from src.models.template import TaskTemplateModel, TaskTemplateItemModel
from src.models.project import ProjectModel
from src.models.task import TaskPriority, TaskStatus, SpisokModel
from src.utils.datetime_utils import to_local

PRIORITY_LABELS = {
    "low": "⚪ Низкий",
    "medium": "🔵 Средний",
    "high": "🟠 Высокий",
    "critical": "🔴 Критический",
}

PRIORITY_COLORS = {
    "low": "#6c757d",
    "medium": "#0d6efd",
    "high": "#fd7e14",
    "critical": "#dc3545",
}

VISIBILITY_TEMPLATE = {
    "private": "🔒 Приватный",
    "group": "👥 Для группы",
    "global": "🌐 Глобальный",
}


def _priority_val(item) -> str:
    return (
        item.priority.value if hasattr(item.priority, "value") else str(item.priority)
    )


def _render_items(model, attr) -> Markup:  # type: ignore[override]
    items = sorted(model.items, key=lambda x: x.order_index) if model.items else []
    if not items:
        return Markup(
            '<span style="color:#6c757d; font-style:italic;">Нет задач</span>'
        )

    rows = "".join(
        f"<tr>"
        f'<td style="padding:4px 8px;color:#6c757d;font-size:12px;">{i + 1}</td>'
        f'<td style="padding:4px 8px;font-size:13px;">{item.title}</td>'
        f'<td style="padding:4px 8px;font-size:12px;color:{PRIORITY_COLORS.get(_priority_val(item), "#333")};">'
        f"{PRIORITY_LABELS.get(_priority_val(item), _priority_val(item))}</td>"
        f"</tr>"
        for i, item in enumerate(items)
    )
    return Markup(
        f'<table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:4px;">'
        f'<thead><tr style="background:#f8f9fa;border-bottom:2px solid #dee2e6;">'
        f'<th style="padding:6px 8px;text-align:left;width:40px;">#</th>'
        f'<th style="padding:6px 8px;text-align:left;">Название</th>'
        f'<th style="padding:6px 8px;text-align:left;width:140px;">Приоритет</th>'
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


class TaskTemplateAdmin(ModelView, model=TaskTemplateModel):
    _session_maker: async_sessionmaker
    identity = "task-template"
    name = "Шаблон проекта"
    name_plural = "Шаблоны проектов"
    icon = "fa-solid fa-file-lines"

    column_list = [
        TaskTemplateModel.id,
        TaskTemplateModel.title,
        TaskTemplateModel.owner,
        TaskTemplateModel.visibility,
        TaskTemplateModel.created_at,
        "items_count",
        "apply_link",
    ]

    column_searchable_list = [TaskTemplateModel.title]
    column_sortable_list = [
        TaskTemplateModel.id,
        TaskTemplateModel.title,
        TaskTemplateModel.created_at,
    ]
    column_default_sort = [(TaskTemplateModel.created_at, True)]

    column_details_list = [
        TaskTemplateModel.id,
        TaskTemplateModel.title,
        TaskTemplateModel.description,
        TaskTemplateModel.owner,
        TaskTemplateModel.visibility,
        TaskTemplateModel.created_at,
        "items_detail",
        "apply_link",
    ]

    column_labels = {
        "id": "ID",
        "title": "Название",
        "description": "Описание",
        "owner": "Владелец",
        "owner_id": "Владелец (ID)",
        "visibility": "Область Видимости",
        "created_at": "Создан",
        "items": "Задачи",
        "items_count": "Кол-во задач",
        "items_detail": "Задачи шаблона",
        "apply_link": "Применить",
    }

    column_formatters = {
        TaskTemplateModel.created_at: lambda m, a: to_local(m.created_at),
        "items_count": lambda m, a: Markup(
            f'<span style="display:inline-block;min-width:24px;padding:2px 8px;'
            f'background:#0d6efd;color:#fff;border-radius:12px;font-size:12px;text-align:center;">'
            f"{len(m.items)}</span>"
        ),
        "apply_link": lambda m, a: Markup(
            f'<a href="{URLS["template"]["apply"]}{m.id}" '
            f'style="padding:4px 12px;background:#198754;color:#fff;border-radius:6px;'
            f'font-size:12px;text-decoration:none;white-space:nowrap;">▶ Применить</a>'
        ),
        "visibility": lambda m, a: VISIBILITY_TEMPLATE.get(
            m.visibility.value if hasattr(m.visibility, "value") else str(m.visibility),
            str(m.visibility),
        ),
    }

    column_formatters_detail = {
        TaskTemplateModel.created_at: lambda m, a: to_local(m.created_at),
        "items_detail": _render_items,
        "apply_link": lambda m, a: Markup(
            f'<a href="{URLS["template"]["apply"]}{m.id}" '
            f'style="padding:6px 16px;background:#198754;color:#fff;border-radius:8px;'
            f'font-size:13px;text-decoration:none;">▶ Применить шаблон к проекту</a>'
        ),
    }

    form_columns = [
        TaskTemplateModel.title,
        TaskTemplateModel.description,
        TaskTemplateModel.owner,
        TaskTemplateModel.visibility,
        TaskTemplateModel.group,
    ]

    form_overrides = {"visibility": SelectField}

    form_args = {
        "owner": {"label": "Владелец"},
        "title": {"label": "Название"},
        "description": {"label": "Описание"},
        "visibility": {
            "label": "Видимость",
            "choices": list(VISIBILITY_TEMPLATE.items()),
            "coerce": str,
        },
        "group": {"label": "Группа (для visibility=group)"},
    }

    @expose("/apply/{pk}")
    async def apply_template(self, request: Request):
        """
        GET /apply/{pk}              — показать форму выбора проекта
        GET /apply/{pk}?confirm=1&project_id=X — применить шаблон

        sqladmin @expose поддерживает только GET, поэтому форма
        использует method="get" вместо "post".
        """
        pk = request.path_params.get("pk")
        if not pk or not str(pk).isdigit():
            return RedirectResponse(URLS["template"]["list"], status_code=303)
        pk = int(pk)

        success = None
        success_project = None
        error = None

        async with self._session_maker() as session:
            # Загружаем шаблон
            result = await session.execute(
                select(TaskTemplateModel).where(TaskTemplateModel.id == pk)
            )
            template = result.unique().scalar_one_or_none()
            if not template:
                return RedirectResponse(URLS["template"]["list"], status_code=303)

            # Загружаем проекты
            proj_result = await session.execute(select(ProjectModel))
            projects = list(proj_result.scalars().all())

            items = sorted(template.items, key=lambda x: x.order_index)

            # Применяем шаблон если передан confirm=1&project_id=X
            confirm = request.query_params.get("confirm")
            project_id_q = request.query_params.get("project_id")

            if confirm == "1" and project_id_q and str(project_id_q).isdigit():
                project_id = int(str(project_id_q))
                project = next((p for p in projects if p.id == project_id), None)

                if not items:
                    error = "Шаблон не содержит задач"
                elif not project:
                    error = "Проект не найден"
                else:
                    try:
                        created = []
                        for item in items:
                            task = SpisokModel(
                                title=item.title,
                                priority=item.priority,
                                status=TaskStatus.todo,
                                project_id=project_id,
                                author_id=template.owner_id,
                                user_id=template.owner_id,
                            )
                            session.add(task)
                            created.append(task)
                        await session.commit()
                        success = len(created)
                        success_project = project.name
                    except Exception as e:
                        await session.rollback()
                        error = str(e)

        items_ctx = [
            {
                "title": item.title,
                "priority_label": PRIORITY_LABELS.get(
                    _priority_val(item), _priority_val(item)
                ),
                "priority_color": PRIORITY_COLORS.get(_priority_val(item), "#333"),
            }
            for item in items
        ]

        return await self.templates.TemplateResponse(
            request,
            "admin/template_apply.html",
            {
                "request": request,
                "template": template,
                "items": items_ctx,
                "projects": projects,
                "apply_url": f'{URLS["template"]["apply"]}{pk}',
                "urls": {"list": URLS["template"]["list"]},
                "success": success,
                "success_project": success_project,
                "error": error,
            },
        )


class TaskTemplateItemAdmin(ModelView, model=TaskTemplateItemModel):
    identity = "task-template-item"
    name = "Задача шаблона"
    name_plural = "Задачи шаблонов"
    icon = "fa-solid fa-list"

    column_list = [
        TaskTemplateItemModel.id,
        TaskTemplateItemModel.template,
        TaskTemplateItemModel.title,
        TaskTemplateItemModel.priority,
        TaskTemplateItemModel.order_index,
    ]

    column_searchable_list = [TaskTemplateItemModel.title]
    column_sortable_list = [
        TaskTemplateItemModel.id,
        TaskTemplateItemModel.title,
        TaskTemplateItemModel.priority,
        TaskTemplateItemModel.order_index,
    ]
    column_default_sort = [
        (TaskTemplateItemModel.template_id, False),
        (TaskTemplateItemModel.order_index, False),
    ]

    column_filters = [
        ForeignKeyFilter(
            TaskTemplateItemModel.template_id,
            TaskTemplateModel.title,
            title="Задачи шаблона",
        )
    ]

    column_labels = {
        "id": "ID",
        "template": "Шаблон",
        "template_id": "Шаблон (ID)",
        "title": "Название",
        "priority": "Приоритет",
        "order_index": "Порядок",
    }

    column_formatters = {
        "priority": lambda m, a: PRIORITY_LABELS.get(
            _priority_val(m), _priority_val(m)
        ),
    }
    column_formatters_detail = column_formatters

    form_columns = [
        TaskTemplateItemModel.template,
        TaskTemplateItemModel.title,
        TaskTemplateItemModel.priority,
        TaskTemplateItemModel.order_index,
    ]

    form_overrides = {"priority": SelectField}

    form_args = {
        "priority": {
            "label": "Приоритет",
            "choices": list(PRIORITY_LABELS.items()),
            "coerce": lambda x: TaskPriority(x),
        },
        "order_index": {"label": "Порядок (0 = первый)"},
        "title": {"label": "Название задачи"},
        "template": {"label": "Шаблон"},
    }
