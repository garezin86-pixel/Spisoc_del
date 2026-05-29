# src/admin/views.py
from sqladmin import ModelView
from sqladmin.filters import OperationColumnFilter, BooleanFilter
from src.models.notification_log import NotificationLogModel


class NotificationLogAdmin(ModelView, model=NotificationLogModel):
    """Админ-панель для логов уведомлений"""

    # Названия
    name = "Лог уведомления"
    name_plural = "Логи уведомлений"
    icon = "fa-solid fa-bell"

    # Колонки для отображения
    column_list = [
        NotificationLogModel.id,
        NotificationLogModel.user,
        NotificationLogModel.notification_type,
        NotificationLogModel.task_id,
        NotificationLogModel.sent_at,
        NotificationLogModel.success,
    ]

    # Заголовки колонок
    column_labels = {
        "id": "ID",
        "user": "Пользователь",
        "user_id": "ID пользователя",
        "notification_type": "Тип уведомления",
        "task_id": "ID задачи",
        "content": "Текст уведомления",
        "sent_at": "Время отправки",
        "success": "Успешно",
        "error": "Ошибка",
    }

    # Колонки для поиска
    column_searchable_list = [
        NotificationLogModel.notification_type,
        NotificationLogModel.content,
    ]

    column_filters = [
        OperationColumnFilter(
            NotificationLogModel.notification_type,
            title="Тип уведомления",
        ),
        BooleanFilter(
            NotificationLogModel.success,
            title="Статус отправки",
        ),
        OperationColumnFilter(
            NotificationLogModel.sent_at,
            title="Дата отправки",
        ),
    ]

    # Сортировка по умолчанию
    column_default_sort = [
        (NotificationLogModel.sent_at, True)
    ]  # True - DESC (сначала новые)

    # Форматирование даты
    column_formatters = {
        NotificationLogModel.sent_at: lambda m, a: (
            m.sent_at.strftime("%d.%m.%Y %H:%M:%S") if m.sent_at else "-"
        ),
        NotificationLogModel.success: lambda m, a: "✅ Да" if m.success else "❌ Нет",
        NotificationLogModel.notification_type: lambda m, a: {
            "deadline_24h": "⏰ Напоминание за 24ч",
            "deadline_1h": "⏰ Напоминание за 1ч",
            "overdue": "⚠️ Просрочка",
            "weekly_report": "📊 Еженедельная сводка",
            "task_assigned": "📋 Назначение задачи",
            "task_updated": "✏️ Обновление задачи",
            "comment": "💬 Новый комментарий",
            "group_assigned": "👥 Назначение в группу",
            "group_task_assigned": "👥 Групповая задача",
        }.get(m.notification_type, m.notification_type),
    }

    # Можно редактировать?
    can_create = False
    can_edit = False
    can_delete = True

    # Количество записей на странице
    page_size = 50
    page_size_options = [25, 50, 100, 200]

    # Дополнительные опции
    column_details_list = [
        NotificationLogModel.id,
        NotificationLogModel.user,
        NotificationLogModel.notification_type,
        NotificationLogModel.task_id,
        NotificationLogModel.content,
        NotificationLogModel.sent_at,
        NotificationLogModel.success,
        NotificationLogModel.error,
    ]
