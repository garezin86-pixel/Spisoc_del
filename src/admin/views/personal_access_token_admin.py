import structlog
from sqladmin import ModelView

from src.models import PersonalAccessTokenModel
from src.models.enums import PatScope
from src.utils.datetime_utils import to_local_datetime

logger = structlog.get_logger()

PAT_SCOPE_LABELS = {
    PatScope.read_only.value: "Только чтение",
    PatScope.read_write.value: "Чтение и запись",
}


# ─────────────────────────────────────────────
# 👥 Персональные токены
# ─────────────────────────────────────────────
class PersonalAccessTokenAdmin(ModelView, model=PersonalAccessTokenModel):
    name = "Персональный токен"
    name_plural = "Персональные токены"
    icon = "fa-solid fa-key"

    can_create = False
    can_edit = False
    can_delete = True

    column_list = [
        PersonalAccessTokenModel.id,
        PersonalAccessTokenModel.name,
        PersonalAccessTokenModel.user,
        PersonalAccessTokenModel.scope,
        PersonalAccessTokenModel.token_prefix,
        PersonalAccessTokenModel.created_at,
        PersonalAccessTokenModel.last_used_at,
    ]
    column_searchable_list = [
        PersonalAccessTokenModel.name,
        PersonalAccessTokenModel.token_prefix,
    ]
    column_sortable_list = [
        PersonalAccessTokenModel.id,
        PersonalAccessTokenModel.name,
        PersonalAccessTokenModel.user,
        PersonalAccessTokenModel.created_at,
    ]
    column_default_sort = [(PersonalAccessTokenModel.id, False)]

    column_details_list = [
        PersonalAccessTokenModel.id,
        PersonalAccessTokenModel.name,
        PersonalAccessTokenModel.user,
        PersonalAccessTokenModel.token_prefix,
        PersonalAccessTokenModel.scope,
        PersonalAccessTokenModel.created_at,
        PersonalAccessTokenModel.expires_at,
        PersonalAccessTokenModel.last_used_at,
    ]

    column_labels = {
        "id": "ID",
        "name": "Название",
        "user": "Пользователь",
        "token_prefix": "Префикс токена",
        "scope": "Область доступа",
        "created_at": "Создан",
        "expires_at": "Истекает",
        "last_used_at": "Последнее использование",
    }

    column_formatters = {
        PersonalAccessTokenModel.created_at: lambda m, a: to_local_datetime(m.created_at),
        PersonalAccessTokenModel.last_used_at: lambda m, a: to_local_datetime(m.last_used_at),
        PersonalAccessTokenModel.scope: lambda m, a: PAT_SCOPE_LABELS.get(m.scope, m.scope),
    }

    column_formatters_detail = {
        PersonalAccessTokenModel.created_at: lambda m, a: to_local_datetime(m.created_at),
        PersonalAccessTokenModel.expires_at: lambda m, a: to_local_datetime(m.expires_at),
        PersonalAccessTokenModel.last_used_at: lambda m, a: to_local_datetime(m.last_used_at),
        PersonalAccessTokenModel.scope: lambda m, a: PAT_SCOPE_LABELS.get(m.scope, m.scope),
    }

    async def after_model_change(self, data, model, is_created, request):
        await logger.ainfo(
            ("personal_access_token_created" if is_created else "personal_access_token_updated"),
            pat_id=model.id,
            admin_id=request.session.get("admin_id"),
        )
