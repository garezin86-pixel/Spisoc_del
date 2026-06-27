import structlog
from sqladmin import ModelView

from src.models import GroupModel

logger = structlog.get_logger()


# ─────────────────────────────────────────────
# 👥 Группы
# ─────────────────────────────────────────────
class GroupAdmin(ModelView, model=GroupModel):
    name = "Группа"
    name_plural = "Группы"
    icon = "fa-solid fa-users"

    column_list = [GroupModel.id, GroupModel.name, GroupModel.users]
    column_searchable_list = [GroupModel.name]
    column_sortable_list = [GroupModel.id, GroupModel.name]
    column_default_sort = [(GroupModel.id, False)]

    column_details_list = [
        GroupModel.id,
        GroupModel.name,
        GroupModel.users,
        GroupModel.tasks,
    ]
    form_columns = [GroupModel.name, GroupModel.users]

    column_labels = {
        "id": "ID",
        "name": "Название",
        "users": "Пользователи",
        "tasks": "Задачи",
    }

    async def on_model_change(self, data, model, is_created, request):
        """Запоминаем старых участников ДО сохранения."""
        request.state.old_user_ids = {u.id for u in model.users} if model.users else set()

    async def after_model_change(self, data, model, is_created, request):
        """Уведомляем НОВЫХ участников ПОСЛЕ сохранения."""
        import asyncio

        from src.utils.reminders import notify_group_assigned

        old_ids = getattr(request.state, "old_user_ids", set())
        new_ids = {u.id for u in model.users} if model.users else set()
        added_ids = new_ids - old_ids

        await logger.ainfo(
            "group_created" if is_created else "group_updated",
            group_id=model.id,
            admin_id=request.session.get("admin_id"),
        )

        for user_id in added_ids:
            asyncio.create_task(notify_group_assigned(user_id, model.id, model.name))
