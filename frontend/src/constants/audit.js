export const AUDIT_ACTION_ICONS = { create: "✅", update: "✏️", delete: "🗑", restore: "♻️" };


export const AUDIT_ACTION_LABELS = { create: "Создана", update: "Изменена", delete: "Удалена", restore: "Восстановлена" };


export const AUDIT_FIELD_LABELS = {
    title: "Заголовок", description: "Описание", is_done: "Статус",
    deadline: "Дедлайн", user_id: "Исполнитель", group_id: "Группа",
    priority: "Приоритет", project_id: "Проект", deleted_at: "Удалена",
};

// ─── TimelineTab — глобальная лента активности ────────────────────────────
// Переиспользует бэкенд /analytics/activity (см. ActivityService) — тот же
// audit_log, что и AuditPanel по одной задаче, но по всем задачам/комментариям
// сразу, уже с готовыми человекочитаемыми лейблами полей с бэкенда.
