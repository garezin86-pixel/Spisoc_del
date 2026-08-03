from sqladmin import ModelView

from src.models import ProjectModel
from src.utils.datetime_utils import to_local


# ─────────────────────────────────────────────
# 👥 Проекты
# ─────────────────────────────────────────────
class ProjectAdmin(ModelView, model=ProjectModel):
    name = "Проект"
    name_plural = "Проекты"
    icon = "fa-solid fa-diagram-project"

    column_list = [
        ProjectModel.id,
        ProjectModel.name,
        ProjectModel.owner,
        ProjectModel.created_at,
    ]
    column_searchable_list = [ProjectModel.name]
    column_sortable_list = [
        ProjectModel.id,
        ProjectModel.name,
        ProjectModel.created_at,
    ]
    column_default_sort = [(ProjectModel.id, False)]

    column_details_list = [
        ProjectModel.id,
        ProjectModel.name,
        ProjectModel.description,
        ProjectModel.tasks,
        ProjectModel.owner,
        ProjectModel.created_at,
        ProjectModel.updated_at,
        ProjectModel.members,
        ProjectModel.group,
    ]
    form_columns = [
        ProjectModel.name,
        ProjectModel.description,
        ProjectModel.owner,
        ProjectModel.members,
        ProjectModel.group,
    ]
    column_labels = {
        "id": "ID",
        "name": "Название",
        "description": "Описание",
        "tasks": "Задачи",
        "owner": "Владелец",
        "members": "Участники",
        "group": "Группа",
        "created_at": "Создано",
        "updated_at": "Обновлено",
    }

    column_formatters = {
        ProjectModel.created_at: lambda m, a: to_local(m.created_at),
        ProjectModel.updated_at: lambda m, a: to_local(m.updated_at),
    }

    column_formatters_detail = {
        ProjectModel.created_at: lambda m, a: to_local(m.created_at),
        ProjectModel.updated_at: lambda m, a: to_local(m.updated_at),
    }
