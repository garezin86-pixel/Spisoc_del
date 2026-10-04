import structlog
from fastapi import Request
from sqladmin import ModelView

from src.core.ws_manager import ws_manager
from src.models.workspace import WorkspaceModel

logger = structlog.get_logger()


class WorkspaceAdmin(ModelView, model=WorkspaceModel):
    """Компании. Единственное место, где компанию можно отключить/включить.

    Отключённая компания (is_active=False): её пользователи не могут войти,
    токены и PAT перестают работать, Telegram-бот им не отвечает, открытые
    WebSocket-соединения закрываются, напоминания и вебхуки не отправляются.
    Данные при этом не удаляются — компанию можно включить обратно.

    Создание — только через регистрацию (POST /auth/register), удаление
    отключено: каскадно сносит все данные компании, для этого есть БД.
    """

    name = "Компания"
    name_plural = "Компании"
    icon = "fa-solid fa-building"

    can_create = False
    can_delete = False

    column_list = [WorkspaceModel.id, WorkspaceModel.name, WorkspaceModel.slug, WorkspaceModel.is_active]
    column_details_list = [
        WorkspaceModel.id,
        WorkspaceModel.name,
        WorkspaceModel.slug,
        WorkspaceModel.is_active,
        WorkspaceModel.created_at,
    ]
    column_searchable_list = [WorkspaceModel.name, WorkspaceModel.slug]
    column_sortable_list = [WorkspaceModel.id, WorkspaceModel.name, WorkspaceModel.is_active]
    column_default_sort = [(WorkspaceModel.id, False)]
    form_columns = [WorkspaceModel.name, WorkspaceModel.is_active]

    column_labels = {
        "id": "ID",
        "name": "Название",
        "slug": "Идентификатор",
        "is_active": "Активна",
        "created_at": "Создана",
    }
    column_formatters = {WorkspaceModel.is_active: lambda m, a: "Да" if m.is_active else "Нет"}

    async def after_model_change(self, data: dict, model: WorkspaceModel, is_created: bool, request: Request) -> None:
        if model.is_active:
            return
        closed = await ws_manager.disconnect_workspace(model.id)
        await logger.awarning(
            "workspace_disabled",
            workspace_id=model.id,
            ws_closed=closed,
            admin_id=request.session.get("admin_id"),
        )
