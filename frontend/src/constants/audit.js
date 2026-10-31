import { localizeIsoDateTime } from "./crm";
import { PRIORITY_LABELS } from "./priority";
import { STATUS_META } from "./status";

export const AUDIT_ACTION_ICONS = { create: "✅", update: "✏️", delete: "🗑", restore: "♻️" };


export const AUDIT_ACTION_LABELS = { create: "Создана", update: "Изменена", delete: "Удалена", restore: "Восстановлена" };


export const AUDIT_FIELD_LABELS = {
    title: "Заголовок", description: "Описание", is_done: "Выполнена", status: "Статус",
    deadline: "Дедлайн", user_id: "Исполнитель", group_id: "Группа",
    priority: "Приоритет", project_id: "Проект", client_id: "Клиент",
    deleted_at: "Удалена", completed_at: "Завершена", recurrence_rule: "Повторение",
};

const RECURRENCE_LABELS = { none: "Не повторяется", daily: "Каждый день", weekly: "Каждую неделю", monthly: "Каждый месяц" };

// Человекочитаемое значение поля из журнала аудита: статусы и приоритеты — русскими названиями,
// даты ISO — в местном формате, пустое — «—», ссылки на сущности — «#id».
// lookup — {id: имя} из ответа сервера для полей-ссылок (исполнитель, группа, проект, клиент); без него — «#id».
export function formatAuditValue(field, value, lookup) {
    if (value === null || value === undefined || value === "") return "—";
    if (lookup && lookup[String(value)] !== undefined) return lookup[String(value)];
    if (field === "status") return STATUS_META[value]?.label ?? String(value);
    if (field === "priority") return PRIORITY_LABELS[value] ?? String(value);
    if (field === "recurrence_rule") return RECURRENCE_LABELS[value] ?? String(value);
    if (typeof value === "boolean") return value ? "Да" : "Нет";
    if (field.endsWith("_id") && (typeof value === "number" || /^\d+$/.test(String(value)))) return `#${value}`;
    return localizeIsoDateTime(String(value));
}

// ─── TimelineTab — глобальная лента активности ────────────────────────────
// Переиспользует бэкенд /analytics/activity (см. ActivityService) — тот же
// audit_log, что и AuditPanel по одной задаче, но по всем задачам/комментариям
// сразу, уже с готовыми человекочитаемыми лейблами полей с бэкенда.
