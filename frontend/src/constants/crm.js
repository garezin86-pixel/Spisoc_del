// Справочники и форматтеры lite-CRM (клиенты, взаимодействия, сделки).

export const INTERACTION_TYPES = [
    { key: "call", label: "Звонок", icon: "📞" },
    { key: "meeting", label: "Встреча", icon: "🤝" },
    { key: "email", label: "Письмо", icon: "✉️" },
    { key: "message", label: "Сообщение", icon: "💬" },
    { key: "note", label: "Заметка", icon: "📝" },
];

// plural(1, "клиент", "клиента", "клиентов") → "клиент"; 2 → "клиента"; 5 → "клиентов"; 21 → "клиент"
export function plural(n, one, few, many) {
    const abs = Math.abs(n) % 100;
    const last = abs % 10;
    if (abs > 10 && abs < 20) return many;
    if (last === 1) return one;
    if (last >= 2 && last <= 4) return few;
    return many;
}

// Тип клиента: компания (B2B) или частное лицо (B2C; в названии — ФИО). Ключи совпадают с бэкендом.
export const CLIENT_TYPES = [
    { key: "company", label: "Компания (B2B)", short: "B2B", icon: "🏢", nameLabel: "Название компании", namePlaceholder: "Например, ООО «Ромашка»" },
    { key: "person", label: "Человек (B2C)", short: "B2C", icon: "👤", nameLabel: "ФИО", namePlaceholder: "Например, Иванов Иван Иванович" },
];
export const clientTypeInfo = key => CLIENT_TYPES.find(t => t.key === key) ?? CLIENT_TYPES[0];

export const GENDERS = [
    { key: "male", label: "Мужской" },
    { key: "female", label: "Женский" },
];
export const genderLabel = key => GENDERS.find(g => g.key === key)?.label ?? null;

// Полных лет по дате рождения «YYYY-MM-DD» (null, если даты нет)
export function ageFromDate(dateStr, now = new Date()) {
    if (!dateStr) return null;
    const [y, m, d] = dateStr.split("-").map(Number);
    let age = now.getFullYear() - y;
    if (now.getMonth() + 1 < m || (now.getMonth() + 1 === m && now.getDate() < d)) age -= 1;
    return age >= 0 ? age : null;
}

export const INTERACTION_LABELS = Object.fromEntries(INTERACTION_TYPES.map(t => [t.key, t]));

// Цвет колонки воронки по виду стадии (open / won / lost) — используется, пока у стадии нет своего цвета
export const STAGE_KIND_COLORS = { open: "#7c6af0", won: "#22c55e", lost: "#ef4444" };

// Свой цвет стадии, если задан, иначе цвет по виду стадии
export function stageColor(stage) {
    return stage?.color || STAGE_KIND_COLORS[stage?.kind] || "#6b7280";
}

// Готовые цвета для быстрого выбора (любой другой — через палитру)
export const STAGE_COLOR_PRESETS = [
    "#7c6af0", "#3b82f6", "#06b6d4", "#22c55e", "#eab308", "#f97316", "#ef4444", "#ec4899", "#a855f7", "#6b7280",
];

// Валюты сделок. Список должен совпадать с SUPPORTED_CURRENCIES в src/models/deal.py (бэкенд отклонит остальные).
export const CURRENCIES = [
    { code: "UAH", symbol: "₴", label: "Гривна" },
    { code: "USD", symbol: "$", label: "Доллар США" },
    { code: "EUR", symbol: "€", label: "Евро" },
];
export const DEFAULT_CURRENCY = "UAH";

const moneyFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

// 15000 + "UAH" → «15 000 ₴»; 2500 + "USD" → «2 500 $». Дробная часть показывается, только если она есть.
export function formatMoney(value, currency = DEFAULT_CURRENCY) {
    if (value === null || value === undefined) return "—";
    const n = Number(value);
    try {
        return new Intl.NumberFormat("ru-RU", {
            style: "currency", currency, currencyDisplay: "narrowSymbol", minimumFractionDigits: 0, maximumFractionDigits: 2,
        }).format(n);
    } catch {
        return `${moneyFormat.format(n)} ${currency}`; // неизвестный код валюты
    }
}

// Суммы разных валют не складываются: считаем отдельно по каждой. → { UAH: 15000, USD: 2500 }
export function sumByCurrency(deals) {
    const totals = {};
    for (const d of deals) {
        if (d.amount === null || d.amount === undefined) continue;
        const code = d.currency || DEFAULT_CURRENCY;
        totals[code] = (totals[code] ?? 0) + Number(d.amount);
    }
    return totals;
}

// { UAH: 15000, USD: 2500 } → «15 000 ₴ · 2 500 $» (порядок валют как в CURRENCIES, неизвестные в конце); пусто → ""
export function formatTotals(totals) {
    const order = code => { const i = CURRENCIES.findIndex(c => c.code === code); return i === -1 ? CURRENCIES.length : i; };
    return Object.keys(totals)
        .filter(code => totals[code] > 0)
        .sort((a, b) => order(a) - order(b))
        .map(code => formatMoney(totals[code], code))
        .join(" · ");
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

// «2026-07-31T12:00:00+00:00» → «31.07.2026, 15:00» (в часовом поясе пользователя); не метка времени — как есть
export function localizeIsoDateTime(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)) return value;
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

// «Связаться снова»: просрочено ли (дата наступила или прошла) — сравнение дат без времени, в локальной зоне
export function isContactDue(dateStr) {
    if (!dateStr) return false;
    const d = new Date(`${dateStr}T00:00:00`);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return d <= today;
}

// Сегодняшняя дата в формате YYYY-MM-DD (для min у <input type="date">)
export function todayInput() {
    const d = new Date();
    const pad = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// Пустую строку формы → null (очистить поле на сервере), иначе строка без пробелов по краям
export function emptyToNull(value) {
    const v = (value ?? "").trim();
    return v === "" ? null : v;
}
