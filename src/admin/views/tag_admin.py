import structlog
from sqladmin import ModelView

from src.models import TagModel

logger = structlog.get_logger()


# ─────────────────────────────────────────────
# 🏷️ Теги
# ─────────────────────────────────────────────
class TagAdmin(ModelView, model=TagModel):
    name = "Тег"
    name_plural = "Теги"
    icon = "fa-solid fa-tag"

    column_list = [
        TagModel.id,
        TagModel.name,
        TagModel.color,
        "tasks_count",
    ]

    column_searchable_list = [
        TagModel.name,
    ]

    column_sortable_list = [
        TagModel.id,
        TagModel.name,
    ]

    column_default_sort = [
        (TagModel.id, False),
    ]

    column_details_list = [
        TagModel.id,
        TagModel.name,
        TagModel.color,
        TagModel.tasks,
    ]

    form_columns = [
        TagModel.name,
        TagModel.color,
    ]

    column_labels = {
        "id": "ID",
        "name": "Название",
        "color": "Цвет",
        "tasks": "Связанные задачи",
        "tasks_count": "Количество задач",
    }

    column_formatters = {
        "tasks_count": lambda m, a: len(m.tasks),
    }
