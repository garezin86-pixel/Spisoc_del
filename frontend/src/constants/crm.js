// Справочники и форматтеры lite-CRM (клиенты, взаимодействия, сделки).

export const INTERACTION_TYPES = [
    { key: "call", label: "Звонок", icon: "📞" },
    { key: "meeting", label: "Встреча", icon: "🤝" },
    { key: "email", label: "Письмо", icon: "✉️" },
    { key: "message", label: "Сообщение", icon: "💬" },
    { key: "note", label: "Заметка", icon: "📝" },
];

export const INTERACTION_LABELS = Object.fromEntries(INTERACTION_TYPES.map(t => [t.key, t]));

// Цвет колонки воронки по виду стадии (open / won / lost)
export const STAGE_KIND_COLORS = { open: "#7c6af0", won: "#22c55e", lost: "#ef4444" };

const moneyFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

export function formatMoney(value) {
    if (value === null || value === undefined) return "—";
    return moneyFormat.format(Number(value));
}

export function formatDateTime(value) {
    if (!value) return "—";
    return new Date(value).toLocaleString("ru-RU", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function formatDate(value) {
    if (!value) return "—";
    // "2026-12-01" (дата без времени) разбираем как локальную, чтобы не съезжал день
    const d = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : new Date(value);
    return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" });
}

// <input type="datetime-local"> → ISO для API (пусто → undefined: сервер подставит «сейчас»)
export function localInputToIso(value) {
    return value ? new Date(value).toISOString() : undefined;
}

// ISO → значение для <input type="datetime-local"> в локальной зоне
export function isoToLocalInput(value) {
    if (!value) return "";
    const d = new Date(value);
    const pad = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// Пустую строку формы → null (очистить поле на сервере), иначе строка без пробелов по краям
export function emptyToNull(value) {
    const v = (value ?? "").trim();
    return v === "" ? null : v;
}
