from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqladmin import ModelView, action
from sqladmin.helpers import get_object_identifier
from sqlalchemy import select
from sqlalchemy.orm import registry as _sa_registry
from sqlalchemy.orm import selectinload
from starlette.datastructures import URL

from src.admin.views.task_admin import _fetch_audit_entries, _render_audit_history
from src.core.task_labels import PRIORITY_LABELS, STATUS_LABELS
from src.models import SpisokModel
from src.models import SpisokModel as _RealModel
from src.services.task_admin_service import task_admin_service
from src.utils.datetime_utils import to_local

_proxy_registry = _sa_registry()


class _TrashModelProxy:
    pass


_proxy_registry.map_imperatively(_TrashModelProxy, _RealModel.__table__)
_TrashModelProxy.__name__ = "Trash"


class TrashTaskAdmin(ModelView, model=_TrashModelProxy):
    identity = "trash"
    name = "Корзина"
    name_plural = "Корзина"
    icon = "fa-solid fa-trash-can"
    endpoint = "trash"

    can_create = False
    can_edit = False
    can_delete = False

    details_template = "sqladmin/trash_details.html"

    def _build_url_for(self, name: str, request, obj) -> URL:
        return request.url_for(
            name,
            identity=self.identity,
            pk=get_object_identifier(obj),
        )

    column_formatters = {
        "deleted_at": lambda m, a: to_local(m.deleted_at) if getattr(m, "deleted_at", None) else "—",
        "priority": lambda m, a: PRIORITY_LABELS.get(m.priority, m.priority),
        "status": lambda m, a: STATUS_LABELS.get(m.status, m.status),
    }

    column_list = ["id", "title", "status", "deleted_at"]
    column_searchable_list = ["title"]
    column_sortable_list = ["id", "deleted_at", "title"]
    column_default_sort = [("deleted_at", True)]

    column_details_list = [
        "id",
        "title",
        "description",
        "priority",
        "status",
        "deadline",
        "created_at",
        "updated_at",
        "audit_history",
    ]

    column_labels = {
        "id": "ID",
        "title": "Название",
        "description": "Описание",
        "status": "Статус",
        "priority": "Приоритет",
        "deadline": "Дедлайн",
        "created_at": "Добавлено",
        "updated_at": "Изменено",
        "deleted_at": "Удалено",
        "audit_history": "История изменений",
    }

    column_formatters_detail = {
        "deleted_at": lambda m, a: to_local(m.deleted_at) if getattr(m, "deleted_at", None) else "—",
        "deadline": lambda m, a: to_local(m.deadline) if getattr(m, "deadline", None) else "—",
        "created_at": lambda m, a: to_local(m.created_at) if getattr(m, "created_at", None) else "—",
        "updated_at": lambda m, a: to_local(m.updated_at) if getattr(m, "updated_at", None) else "—",
        "priority": column_formatters["priority"],
        "status": column_formatters["status"],
    }

    def list_query(self, request: Request):
        return (
            select(SpisokModel)
            .where(SpisokModel.deleted_at.is_not(None))
            .options(
                selectinload(SpisokModel.user),
                selectinload(SpisokModel.group),
                selectinload(SpisokModel.author),
            )
        )

    def details_query(self, request: Request):
        pk = request.path_params["pk"]
        return (
            select(SpisokModel)
            .where(SpisokModel.id == int(pk))
            .options(
                selectinload(SpisokModel.user),
                selectinload(SpisokModel.group),
                selectinload(SpisokModel.author),
                selectinload(SpisokModel.comments),
            )
        )

    async def get_detail_value(self, obj, prop: str):
        if prop == "audit_history":
            entries = await _fetch_audit_entries(obj.id)
            formatted_history = _render_audit_history(entries)
            return formatted_history, formatted_history
        return await super().get_detail_value(obj, prop)

    @action(
        name="restore",
        label="Восстановить",
        confirmation_message="Восстановить выбранные задачи?",
        add_in_detail=True,
        add_in_list=True,
    )
    async def action_restore(self, request: Request):
        pks_raw = request.query_params.get("pks", "")
        pks = [int(pk.strip()) for pk in pks_raw.split(",") if pk.strip()]
        admin_id = request.session.get("admin_id")
        await task_admin_service.bulk_restore(pks, admin_id)  # 👈 сервис
        return RedirectResponse(request.url_for("admin:list", identity="trash"), status_code=302)

    @action(
        name="hard-delete",
        label="Удалить навсегда",
        confirmation_message="Удалить безвозвратно? Это действие нельзя отменить.",
        add_in_detail=True,
        add_in_list=True,
    )
    async def action_hard_delete(self, request: Request):
        pks_raw = request.query_params.get("pks", "")
        pks = [int(pk.strip()) for pk in pks_raw.split(",") if pk.strip()]
        admin_id = request.session.get("admin_id")
        await task_admin_service.bulk_hard_delete(pks, admin_id)  # 👈 сервис
        return RedirectResponse(request.url_for("admin:list", identity="trash"), status_code=302)
