"""SQLAdmin-представления для lite-CRM (клиенты, контакты, воронка, сделки,
взаимодействия, запланированные события) и приглашений в компанию.

Принципы:
  * Админка видит ВСЕ компании (доступ только у is_platform_admin), поэтому в каждом
    списке есть колонка и фильтр «Компания» (workspace_id).
  * Все CRM-таблицы — tenant-таблицы с мягким удалением и аудитом. Админка по умолчанию
    ТОЛЬКО ДЛЯ ЧТЕНИЯ: создание/правка/удаление идут через API приложения, где подставляются
    workspace_id (before_flush-слушатель берёт его из session.info — в админке его нет),
    аудит (audit_user_id) и пересчёт кэша дашборда. Чтобы разрешить правку отдельного
    view, достаточно переопределить can_edit = True и задать form_columns.
  * В списках скрыты мягко удалённые строки (deleted_at IS NULL), включая счётчик страниц.
"""

from sqladmin import ModelView
from sqladmin.filters import StaticValuesFilter
from sqlalchemy import func, select

from src.models import (
    ClientModel,
    ContactModel,
    DealModel,
    InteractionModel,
    PipelineModel,
    ScheduledEventModel,
    StageModel,
    WorkspaceInviteModel,
)
from src.models.client import CLIENT_STATUSES, CLIENT_TYPES
from src.models.deal import SUPPORTED_CURRENCIES, StageKind
from src.models.interaction import InteractionType
from src.models.scheduled_event import EventStatus, EventType
from src.utils.datetime_utils import to_local

_CATEGORY = "CRM"


def _dt(attr: str):
    """Форматтер даты/времени: локальная зона, «—» для пустых значений."""
    return lambda m, a: to_local(getattr(m, attr)) if getattr(m, attr, None) else "—"


def _choices(values, labels: dict[str, str] | None = None):
    labels = labels or {}
    return [(str(v), labels.get(str(v), str(v))) for v in values]


class _ReadOnlyCrmView:
    """Общая настройка CRM-view: только чтение, без мягко удалённых строк."""

    category = _CATEGORY
    can_create = False
    can_edit = False
    can_delete = False
    can_export = True
    page_size = 50
    page_size_options = [25, 50, 100, 200]

    def list_query(self, request):
        return select(self.model).where(self.model.deleted_at.is_(None))

    def count_query(self, request):
        return select(func.count(self.pk_columns[0])).select_from(self.model).where(self.model.deleted_at.is_(None))


# ─────────────────────────────────────────────
# 🏢 Клиенты
# ─────────────────────────────────────────────
_CLIENT_TYPE_LABELS = {"company": "Компания", "person": "Частное лицо"}
_CLIENT_STATUS_LABELS = {"active": "Активный", "inactive": "Неактивный", "blacklisted": "Чёрный список"}


class ClientAdmin(_ReadOnlyCrmView, ModelView, model=ClientModel):
    name = "Клиент"
    name_plural = "Клиенты"
    icon = "fa-solid fa-address-book"

    column_list = [
        ClientModel.id,
        ClientModel.workspace_id,
        ClientModel.name,
        ClientModel.client_type,
        ClientModel.status,
        ClientModel.phone,
        ClientModel.email,
        ClientModel.owner_id,
        ClientModel.next_contact_at,
        ClientModel.is_demo,
    ]
    column_details_list = [
        ClientModel.id,
        ClientModel.workspace_id,
        ClientModel.name,
        ClientModel.client_type,
        ClientModel.status,
        ClientModel.phone,
        ClientModel.email,
        ClientModel.address,
        ClientModel.notes,
        ClientModel.owner_id,
        ClientModel.birth_date,
        ClientModel.gender,
        ClientModel.next_contact_at,
        ClientModel.next_contact_notified_at,
        ClientModel.is_demo,
        ClientModel.created_at,
        ClientModel.updated_at,
    ]
    column_searchable_list = [ClientModel.name, ClientModel.phone, ClientModel.email]
    column_sortable_list = [
        ClientModel.id,
        ClientModel.workspace_id,
        ClientModel.name,
        ClientModel.status,
        ClientModel.next_contact_at,
        ClientModel.created_at,
    ]
    column_default_sort = [(ClientModel.id, True)]
    column_filters = [
        StaticValuesFilter(ClientModel.client_type, _choices(CLIENT_TYPES, _CLIENT_TYPE_LABELS), title="Тип"),
        StaticValuesFilter(ClientModel.status, _choices(CLIENT_STATUSES, _CLIENT_STATUS_LABELS), title="Статус"),
        StaticValuesFilter(ClientModel.is_demo, [("true", "Демо"), ("false", "Настоящие")], title="Демо-данные"),
    ]
    column_labels = {
        "id": "ID",
        "workspace_id": "Компания (ID)",
        "name": "Название / ФИО",
        "client_type": "Тип",
        "status": "Статус",
        "phone": "Телефон",
        "email": "E-mail",
        "address": "Адрес",
        "notes": "Заметки",
        "owner_id": "Ответственный (ID)",
        "birth_date": "Дата рождения",
        "gender": "Пол",
        "next_contact_at": "Связаться снова",
        "next_contact_notified_at": "Напоминание отправлено",
        "is_demo": "Демо",
        "created_at": "Создан",
        "updated_at": "Изменён",
    }
    column_formatters = {
        "client_type": lambda m, a: _CLIENT_TYPE_LABELS.get(m.client_type, m.client_type),
        "status": lambda m, a: _CLIENT_STATUS_LABELS.get(m.status, m.status),
        "is_demo": lambda m, a: "Да" if m.is_demo else "Нет",
    }
    column_formatters_detail = {
        **column_formatters,
        "next_contact_notified_at": _dt("next_contact_notified_at"),
        "created_at": _dt("created_at"),
        "updated_at": _dt("updated_at"),
    }


# ─────────────────────────────────────────────
# 👤 Контактные лица
# ─────────────────────────────────────────────
class ContactAdmin(_ReadOnlyCrmView, ModelView, model=ContactModel):
    name = "Контакт"
    name_plural = "Контакты"
    icon = "fa-solid fa-user-tie"

    column_list = [
        ContactModel.id,
        ContactModel.workspace_id,
        ContactModel.client_id,
        ContactModel.name,
        ContactModel.position,
        ContactModel.phone,
        ContactModel.email,
    ]
    column_details_list = column_list + [ContactModel.notes, ContactModel.created_at, ContactModel.updated_at]
    column_searchable_list = [ContactModel.name, ContactModel.phone, ContactModel.email]
    column_sortable_list = [ContactModel.id, ContactModel.workspace_id, ContactModel.client_id, ContactModel.name]
    column_default_sort = [(ContactModel.id, True)]
    column_labels = {
        "id": "ID",
        "workspace_id": "Компания (ID)",
        "client_id": "Клиент (ID)",
        "name": "ФИО",
        "position": "Должность",
        "phone": "Телефон",
        "email": "E-mail",
        "notes": "Заметки",
        "created_at": "Создан",
        "updated_at": "Изменён",
    }
    column_formatters_detail = {"created_at": _dt("created_at"), "updated_at": _dt("updated_at")}


# ─────────────────────────────────────────────
# 🧭 Воронки и стадии
# ─────────────────────────────────────────────
_STAGE_KIND_LABELS = {"open": "В работе", "won": "Выиграна", "lost": "Проиграна"}


class PipelineAdmin(_ReadOnlyCrmView, ModelView, model=PipelineModel):
    name = "Воронка"
    name_plural = "Воронки"
    icon = "fa-solid fa-filter"

    column_list = [PipelineModel.id, PipelineModel.workspace_id, PipelineModel.name, PipelineModel.created_at]
    column_details_list = column_list
    column_searchable_list = [PipelineModel.name]
    column_sortable_list = [PipelineModel.id, PipelineModel.workspace_id, PipelineModel.name]
    column_default_sort = [(PipelineModel.id, False)]
    column_labels = {"id": "ID", "workspace_id": "Компания (ID)", "name": "Название", "created_at": "Создана"}
    column_formatters = {"created_at": _dt("created_at")}
    column_formatters_detail = column_formatters


class StageAdmin(_ReadOnlyCrmView, ModelView, model=StageModel):
    name = "Стадия"
    name_plural = "Стадии воронки"
    icon = "fa-solid fa-layer-group"

    column_list = [
        StageModel.id,
        StageModel.workspace_id,
        StageModel.pipeline_id,
        StageModel.name,
        StageModel.position,
        StageModel.kind,
        StageModel.color,
    ]
    column_details_list = column_list + [StageModel.created_at]
    column_searchable_list = [StageModel.name]
    column_sortable_list = [StageModel.id, StageModel.workspace_id, StageModel.pipeline_id, StageModel.position]
    column_default_sort = [(StageModel.pipeline_id, False), (StageModel.position, False)]
    column_filters = [
        StaticValuesFilter(StageModel.kind, _choices([k.value for k in StageKind], _STAGE_KIND_LABELS), title="Вид")
    ]
    column_labels = {
        "id": "ID",
        "workspace_id": "Компания (ID)",
        "pipeline_id": "Воронка (ID)",
        "name": "Название",
        "position": "Порядок",
        "kind": "Вид",
        "color": "Цвет",
        "created_at": "Создана",
    }
    column_formatters = {"kind": lambda m, a: _STAGE_KIND_LABELS.get(m.kind, m.kind)}
    column_formatters_detail = {**column_formatters, "created_at": _dt("created_at")}


# ─────────────────────────────────────────────
# 💰 Сделки
# ─────────────────────────────────────────────
class DealAdmin(_ReadOnlyCrmView, ModelView, model=DealModel):
    name = "Сделка"
    name_plural = "Сделки"
    icon = "fa-solid fa-handshake"

    column_list = [
        DealModel.id,
        DealModel.workspace_id,
        DealModel.title,
        DealModel.client_id,
        DealModel.stage_id,
        DealModel.amount,
        DealModel.currency,
        DealModel.owner_id,
        DealModel.expected_close_date,
    ]
    column_details_list = [
        DealModel.id,
        DealModel.workspace_id,
        DealModel.title,
        DealModel.client_id,
        DealModel.stage_id,
        DealModel.amount,
        DealModel.currency,
        DealModel.owner_id,
        DealModel.expected_close_date,
        DealModel.closed_at,
        DealModel.lost_reason,
        DealModel.notes,
        DealModel.position,
        DealModel.created_at,
        DealModel.updated_at,
    ]
    column_searchable_list = [DealModel.title]
    column_sortable_list = [
        DealModel.id,
        DealModel.workspace_id,
        DealModel.title,
        DealModel.amount,
        DealModel.expected_close_date,
        DealModel.created_at,
    ]
    column_default_sort = [(DealModel.id, True)]
    column_filters = [StaticValuesFilter(DealModel.currency, _choices(SUPPORTED_CURRENCIES), title="Валюта")]
    column_labels = {
        "id": "ID",
        "workspace_id": "Компания (ID)",
        "title": "Название",
        "client_id": "Клиент (ID)",
        "stage_id": "Стадия (ID)",
        "amount": "Сумма",
        "currency": "Валюта",
        "owner_id": "Ответственный (ID)",
        "expected_close_date": "Ожидаемое закрытие",
        "closed_at": "Закрыта",
        "lost_reason": "Причина отказа",
        "notes": "Заметки",
        "position": "Позиция в колонке",
        "created_at": "Создана",
        "updated_at": "Изменена",
    }
    column_formatters_detail = {
        "closed_at": _dt("closed_at"),
        "created_at": _dt("created_at"),
        "updated_at": _dt("updated_at"),
    }


# ─────────────────────────────────────────────
# 📞 Взаимодействия
# ─────────────────────────────────────────────
_INTERACTION_LABELS = {
    "call": "Звонок",
    "meeting": "Встреча",
    "email": "Письмо",
    "message": "Сообщение",
    "note": "Заметка",
}


class InteractionAdmin(_ReadOnlyCrmView, ModelView, model=InteractionModel):
    name = "Взаимодействие"
    name_plural = "Взаимодействия"
    icon = "fa-solid fa-phone"

    column_list = [
        InteractionModel.id,
        InteractionModel.workspace_id,
        InteractionModel.client_id,
        InteractionModel.type,
        InteractionModel.occurred_at,
        InteractionModel.author_id,
        InteractionModel.summary,
    ]
    column_details_list = column_list + [
        InteractionModel.contact_id,
        InteractionModel.created_at,
        InteractionModel.updated_at,
    ]
    column_searchable_list = [InteractionModel.summary]
    column_sortable_list = [
        InteractionModel.id,
        InteractionModel.workspace_id,
        InteractionModel.client_id,
        InteractionModel.type,
        InteractionModel.occurred_at,
    ]
    column_default_sort = [(InteractionModel.occurred_at, True)]
    column_filters = [
        StaticValuesFilter(
            InteractionModel.type, _choices([t.value for t in InteractionType], _INTERACTION_LABELS), title="Тип"
        )
    ]
    column_labels = {
        "id": "ID",
        "workspace_id": "Компания (ID)",
        "client_id": "Клиент (ID)",
        "contact_id": "Контакт (ID)",
        "type": "Тип",
        "occurred_at": "Когда",
        "summary": "Содержание",
        "author_id": "Автор (ID)",
        "created_at": "Создано",
        "updated_at": "Изменено",
    }
    column_formatters = {
        "type": lambda m, a: _INTERACTION_LABELS.get(m.type, m.type),
        "occurred_at": _dt("occurred_at"),
    }
    column_formatters_detail = {
        **column_formatters,
        "created_at": _dt("created_at"),
        "updated_at": _dt("updated_at"),
    }


# ─────────────────────────────────────────────
# 📅 Запланированные встречи и звонки
# ─────────────────────────────────────────────
_EVENT_TYPE_LABELS = {"call": "Звонок", "meeting": "Встреча"}
_EVENT_STATUS_LABELS = {"planned": "Запланировано", "done": "Состоялось", "cancelled": "Отменено"}


class ScheduledEventAdmin(_ReadOnlyCrmView, ModelView, model=ScheduledEventModel):
    name = "Событие"
    name_plural = "Встречи и звонки"
    icon = "fa-solid fa-calendar-check"

    column_list = [
        ScheduledEventModel.id,
        ScheduledEventModel.workspace_id,
        ScheduledEventModel.client_id,
        ScheduledEventModel.type,
        ScheduledEventModel.title,
        ScheduledEventModel.starts_at,
        ScheduledEventModel.assignee_id,
        ScheduledEventModel.status,
    ]
    column_details_list = column_list + [
        ScheduledEventModel.contact_id,
        ScheduledEventModel.duration_minutes,
        ScheduledEventModel.notes,
        ScheduledEventModel.completed_interaction_id,
        ScheduledEventModel.reminded_at,
        ScheduledEventModel.created_by_id,
        ScheduledEventModel.created_at,
        ScheduledEventModel.updated_at,
    ]
    column_searchable_list = [ScheduledEventModel.title, ScheduledEventModel.notes]
    column_sortable_list = [
        ScheduledEventModel.id,
        ScheduledEventModel.workspace_id,
        ScheduledEventModel.client_id,
        ScheduledEventModel.starts_at,
        ScheduledEventModel.status,
    ]
    column_default_sort = [(ScheduledEventModel.starts_at, True)]
    column_filters = [
        StaticValuesFilter(
            ScheduledEventModel.type, _choices([t.value for t in EventType], _EVENT_TYPE_LABELS), title="Тип"
        ),
        StaticValuesFilter(
            ScheduledEventModel.status,
            _choices([s.value for s in EventStatus], _EVENT_STATUS_LABELS),
            title="Статус",
        ),
    ]
    column_labels = {
        "id": "ID",
        "workspace_id": "Компания (ID)",
        "client_id": "Клиент (ID)",
        "contact_id": "Контакт (ID)",
        "type": "Тип",
        "title": "Тема",
        "starts_at": "Начало",
        "duration_minutes": "Длительность, мин",
        "assignee_id": "Ответственный (ID)",
        "status": "Статус",
        "notes": "Заметки",
        "completed_interaction_id": "Взаимодействие (ID)",
        "reminded_at": "Напоминание отправлено",
        "created_by_id": "Создал (ID)",
        "created_at": "Создано",
        "updated_at": "Изменено",
    }
    column_formatters = {
        "type": lambda m, a: _EVENT_TYPE_LABELS.get(m.type, m.type),
        "status": lambda m, a: _EVENT_STATUS_LABELS.get(m.status, m.status),
        "starts_at": _dt("starts_at"),
    }
    column_formatters_detail = {
        **column_formatters,
        "reminded_at": _dt("reminded_at"),
        "created_at": _dt("created_at"),
        "updated_at": _dt("updated_at"),
    }


# ─────────────────────────────────────────────
# ✉️ Приглашения в компанию (без мягкого удаления)
# ─────────────────────────────────────────────
class WorkspaceInviteAdmin(ModelView, model=WorkspaceInviteModel):
    """Токены приглашений. Токен — секрет: в списке не показываем целиком, создавать
    можно только из приложения (админ компании). Отозвать приглашение платформенный
    админ может, выставив revoked_at в приложении или в БД; здесь — только просмотр."""

    name = "Приглашение"
    name_plural = "Приглашения"
    icon = "fa-solid fa-envelope-open-text"
    category = "Компании"

    can_create = False
    can_edit = False
    can_delete = False

    column_list = [
        WorkspaceInviteModel.id,
        WorkspaceInviteModel.workspace_id,
        "token_preview",
        WorkspaceInviteModel.created_by_id,
        WorkspaceInviteModel.created_at,
        WorkspaceInviteModel.expires_at,
        WorkspaceInviteModel.revoked_at,
        "state",
    ]
    column_details_list = [
        WorkspaceInviteModel.id,
        WorkspaceInviteModel.workspace_id,
        "token_preview",
        WorkspaceInviteModel.created_by_id,
        WorkspaceInviteModel.created_at,
        WorkspaceInviteModel.expires_at,
        WorkspaceInviteModel.revoked_at,
        "state",
    ]
    column_sortable_list = [
        WorkspaceInviteModel.id,
        WorkspaceInviteModel.workspace_id,
        WorkspaceInviteModel.created_at,
        WorkspaceInviteModel.expires_at,
    ]
    column_default_sort = [(WorkspaceInviteModel.id, True)]
    column_labels = {
        "id": "ID",
        "workspace_id": "Компания (ID)",
        "token_preview": "Токен",
        "created_by_id": "Создал (ID)",
        "created_at": "Создано",
        "expires_at": "Действует до",
        "revoked_at": "Отозвано",
        "state": "Состояние",
    }

    @staticmethod
    def _state(m: WorkspaceInviteModel) -> str:
        from datetime import datetime, timezone

        if m.revoked_at is not None:
            return "Отозвано"
        exp = m.expires_at
        if exp is not None and exp.tzinfo is None:  # SQLite отдаёт naive-время, PostgreSQL — aware
            exp = exp.replace(tzinfo=timezone.utc)
        if exp is not None and exp <= datetime.now(timezone.utc):
            return "Истекло"
        return "Действует"

    column_formatters = {
        "token_preview": lambda m, a: f"{m.token[:6]}…",
        "state": lambda m, a: WorkspaceInviteAdmin._state(m),
        "created_at": _dt("created_at"),
        "expires_at": _dt("expires_at"),
        "revoked_at": _dt("revoked_at"),
    }
    column_formatters_detail = column_formatters
