from markupsafe import Markup
from sqladmin import ModelView
from sqladmin.filters import ForeignKeyFilter
from wtforms import SelectField

from src.models.template import TaskTemplateModel, TaskTemplateItemModel
from src.models.task import TaskPriority
from src.utils.datetime_utils import to_local

PRIORITY_LABELS = {
    "low": "⚪ Низкий",
    "medium": "🔵 Средний",
    "high": "🟠 Высокий",
    "critical": "🔴 Критический",
}


def _render_items(model, attr) -> Markup:  # type: ignore[override]
    """Рендерит список задач шаблона в виде HTML-таблицы."""
    items = sorted(model.items, key=lambda x: x.order_index) if model.items else []
    if not items:
        return Markup(
            '<span style="color:#6c757d; font-style:italic;">Нет задач</span>'
        )

    rows = []
    for item in items:
        priority_label = PRIORITY_LABELS.get(
            item.priority.value if hasattr(item.priority, "value") else item.priority,
            str(item.priority),
        )
        rows.append(
            f"<tr>"
            f'<td style="padding:4px 8px; color:#6c757d; font-size:12px;">{item.order_index + 1}</td>'
            f'<td style="padding:4px 8px; font-size:13px;">{item.title}</td>'
            f'<td style="padding:4px 8px; font-size:12px;">{priority_label}</td>'
            f"</tr>"
        )

    rows_html = "\n".join(rows)
    return Markup(f"""
        <table style="width:100%; border-collapse:collapse; font-size:13px; margin-top:4px;">
            <thead>
                <tr style="background:#f8f9fa; border-bottom:2px solid #dee2e6;">
                    <th style="padding:6px 8px; text-align:left; width:40px;">#</th>
                    <th style="padding:6px 8px; text-align:left;">Название</th>
                    <th style="padding:6px 8px; text-align:left; width:140px;">Приоритет</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        """)


class TaskTemplateAdmin(ModelView, model=TaskTemplateModel):
    identity = "task-template"
    name = "Шаблон задач"
    name_plural = "Шаблоны проектов"
    icon = "fa-solid fa-file-lines"

    column_list = [
        TaskTemplateModel.id,
        TaskTemplateModel.title,
        TaskTemplateModel.owner,
        TaskTemplateModel.created_at,
        "items_count",
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
        TaskTemplateModel.created_at,
        "items_detail",
    ]

    column_labels = {
        "id": "ID",
        "title": "Название",
        "description": "Описание",
        "owner": "Владелец",
        "owner_id": "Владелец (ID)",
        "created_at": "Создан",
        "items": "Задачи",
        "items_count": "Кол-во задач",
        "items_detail": "Задачи шаблона",
    }

    column_formatters = {
        TaskTemplateModel.created_at: lambda m, a: to_local(m.created_at),
        "items_count": lambda m, a: Markup(
            f'<span style="display:inline-block; min-width:24px; padding:2px 8px; '
            f'background:#0d6efd; color:#fff; border-radius:12px; font-size:12px; text-align:center;">'
            f"{len(m.items)}</span>"
        ),
    }

    column_formatters_detail = {
        TaskTemplateModel.created_at: lambda m, a: to_local(m.created_at),
        "items_detail": _render_items,
    }

    # Форма — редактируем только название и описание шаблона.
    # Задачи (items) — через отдельный view TaskTemplateItemAdmin ниже.
    form_columns = [
        TaskTemplateModel.title,
        TaskTemplateModel.description,
        TaskTemplateModel.owner,
    ]

    form_args = {
        "owner": {"label": "Владелец"},
        "title": {"label": "Название"},
        "description": {"label": "Описание"},
    }


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

    column_details_list = [
        TaskTemplateItemModel.id,
        TaskTemplateItemModel.template,
        TaskTemplateItemModel.title,
        TaskTemplateItemModel.priority,
        TaskTemplateItemModel.order_index,
    ]

    column_labels = {
        "id": "ID",
        "template": "Шаблон",
        "template_id": "Шаблон (ID)",
        "title": "Название",
        "priority": "Приоритет",
        "order_index": "Порядок",
    }

    column_filters = [
        ForeignKeyFilter(
            TaskTemplateItemModel.template_id,
            TaskTemplateModel.title,
            title="Задачи к шаблонам",
        )
    ]

    column_formatters = {
        "priority": lambda m, a: PRIORITY_LABELS.get(
            m.priority.value if hasattr(m.priority, "value") else m.priority,
            str(m.priority),
        ),
    }

    column_formatters_detail: dict = column_formatters  # type: ignore[assignment]

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
