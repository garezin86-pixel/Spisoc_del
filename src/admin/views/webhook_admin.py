import structlog
from sqladmin import ModelView

from src.models import WebhookModel
from src.utils.datetime_utils import to_local_datetime

logger = structlog.get_logger()


class WebhookAdmin(ModelView, model=WebhookModel):
    name = "Вебхук"
    name_plural = "Вебхуки"
    icon = "fa-solid fa-bolt"

    can_create = False
    can_edit = False
    can_delete = True

    column_list = [
        WebhookModel.id,
        WebhookModel.user,
        WebhookModel.url,
        WebhookModel.secret_prefix,
        WebhookModel.is_active,
        "created_at",
        "last_triggered_at",
    ]

    column_searchable_list = [
        WebhookModel.url,
        WebhookModel.secret_prefix,
    ]

    column_sortable_list = [
        WebhookModel.id,
        WebhookModel.user,
        WebhookModel.url,
        WebhookModel.created_at,
    ]

    column_default_sort = [(WebhookModel.id, False)]

    column_details_list = [
        WebhookModel.id,
        WebhookModel.user,
        WebhookModel.url,
        WebhookModel.secret_prefix,
        WebhookModel.events,
        WebhookModel.is_active,
        "created_at",
        "last_triggered_at",
        WebhookModel.last_status_code,
        WebhookModel.last_error,
        WebhookModel.failure_count,
    ]

    column_labels = {
        "id": "ID",
        "user": "Пользователь",
        "url": "URL",
        "secret_prefix": "Префикс секрета",
        "events": "События",
        "is_active": "Активен",
        "created_at": "Создан",
        "last_triggered_at": "Последний вызов",
        "last_status_code": "HTTP-код",
        "last_error": "Последняя ошибка",
        "failure_count": "Ошибок подряд",
    }

    column_formatters = {
        WebhookModel.created_at: lambda m, a: to_local_datetime(m.created_at),
        WebhookModel.last_triggered_at: lambda m, a: to_local_datetime(m.last_triggered_at),
        WebhookModel.is_active: lambda m, a: "Да" if m.is_active else "Нет",
    }

    column_formatters_detail = {
        WebhookModel.created_at: lambda m, a: to_local_datetime(m.created_at),
        WebhookModel.last_triggered_at: lambda m, a: to_local_datetime(m.last_triggered_at),
        WebhookModel.is_active: lambda m, a: "Да" if m.is_active else "Нет",
    }
