from sqladmin import ModelView

from src.models import CommentModel


# ─────────────────────────────────────────────
# 💬 Комментарии
# ─────────────────────────────────────────────
class CommentAdmin(ModelView, model=CommentModel):
    name = "Комментарий"
    name_plural = "Комментарии"
    icon = "fa-solid fa-comment"

    column_list = [
        CommentModel.id,
        CommentModel.task_id,
        CommentModel.user_id,
        CommentModel.content,
    ]
    column_searchable_list = [CommentModel.content]
    column_sortable_list = [CommentModel.id, CommentModel.task_id, CommentModel.user_id]
    column_default_sort = [(CommentModel.id, True)]

    column_details_list = [
        CommentModel.id,
        CommentModel.task,
        CommentModel.user,
        CommentModel.content,
    ]
    form_columns = [CommentModel.task, CommentModel.user, CommentModel.content]

    column_labels = {
        "id": "ID",
        "task_id": "ID задачи",
        "user_id": "ID пользователя",
        "task": "Задача",
        "user": "Пользователь",
        "content": "Содержимое",
    }

    async def on_model_change(self, data, model, is_created, request):
        if is_created:
            admin_id = request.session.get("admin_id")
            if admin_id:
                model.user_id = admin_id
