import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "../api";
import { INTERACTION_LABELS, formatTotals, plural, stageColor } from "../constants/crm";
import { PRIORITY_COLORS, PRIORITY_LABELS } from "../constants/priority";
import { parseBackendDate } from "../utils/date";

const REFRESH_MS = 60_000; // страховка на случай, если WebSocket молчит; запрос дешёвый — ответ кэшируется на сервере
const REFRESH_DEBOUNCE_MS = 300; // несколько событий подряд — один запрос

// Часовой пояс браузера: по нему сервер считает «сегодня» и просроченные.
const BROWSER_TZ = (() => {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; }
})();

const startOfDay = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());

function timeText(value) {
    const d = parseBackendDate(value);
    return d ? d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : "";
}

// «сегодня, 14:30» / «завтра, 09:00» / «пт, 16 окт, 11:00»
function whenText(value) {
    const d = parseBackendDate(value);
    if (!d) return "";
    const diffDays = Math.round((startOfDay(d) - startOfDay(new Date())) / 86_400_000);
    const time = timeText(value);
    if (diffDays === 0) return `сегодня, ${time}`;
    if (diffDays === 1) return `завтра, ${time}`;
    return `${d.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "short" })}, ${time}`;
}

function overdueText(value) {
    const d = parseBackendDate(value);
    return d ? d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" }) : "";
}

// [{currency, count, amount}] → «16 000 ₴ · 2 500 $»; суммы разных валют не складываются
function totalsText(totals) {
    return formatTotals(Object.fromEntries(totals.map(t => [t.currency, t.amount]))) || "—";
}

function Section({ title, total, shown, tone, empty, children }) {
    const rest = total - shown;
    return (
        <div className="card home-section">
            <div className="section-header">
                <div className="section-title" style={tone === "danger" && total > 0 ? { color: "var(--red)" } : undefined}>
                    {title}{total > 0 && <span className="home-count">{total}</span>}
                </div>
            </div>
            {total === 0 ? <div className="home-empty">{empty}</div> : (
                <div className="home-list">
                    {children}
                    {rest > 0 && <div className="home-more">и ещё {rest}</div>}
                </div>
            )}
        </div>
    );
}

function Row({ onClick, left, title, sub, right, rightTone }) {
    return (
        <button type="button" className="home-row" onClick={onClick}>
            <span className="home-row-left">{left}</span>
            <span className="home-row-main">
                <span className="home-row-title">{title}</span>
                {sub && <span className="home-row-sub">{sub}</span>}
            </span>
            {right && <span className="home-row-right" style={rightTone === "danger" ? { color: "var(--red)" } : undefined}>{right}</span>}
        </button>
    );
}

/**
 * Главная: что делать сегодня. Данные — GET /dashboard (кэш на сервере 45 с). refreshKey растёт, когда по
 * WebSocket пришло dashboard_changed: страница тихо перечитывает данные (без «мигания» загрузки).
 */
export function HomeTab({ token, username, refreshKey, onOpenTask, onOpenClient, onOpenDeals, canManage = false, users = [], currentUserId = null }) {
    // admin/manager могут смотреть дашборд сотрудника (GET /dashboard?user_id=); null — свой
    const [viewUserId, setViewUserId] = useState(null);
    const foreign = viewUserId !== null && viewUserId !== currentUserId;
    const viewedName = foreign ? (users.find(u => u.id === viewUserId)?.username ?? `#${viewUserId}`) : username;
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(true);
    const requestRef = useRef(0);

    const load = useCallback(async () => {
        const id = ++requestRef.current;
        try {
            const target = foreign ? `&user_id=${viewUserId}` : "";
            const res = await apiRequest({ path: `/dashboard?tz=${encodeURIComponent(BROWSER_TZ)}${target}`, token });
            if (id !== requestRef.current) return; // пришёл более новый запрос
            setData(res);
            setError(null);
        } catch (e) {
            if (id === requestRef.current) setError(e.message);
        } finally {
            if (id === requestRef.current) setLoading(false);
        }
    }, [token, foreign, viewUserId]);

    useEffect(() => {
        if (!token) return undefined;
        const timer = setTimeout(load, refreshKey === 0 ? 0 : REFRESH_DEBOUNCE_MS);
        return () => clearTimeout(timer);
    }, [token, refreshKey, load]);

    useEffect(() => {
        if (!token) return undefined;
        const timer = setInterval(() => { if (!document.hidden) load(); }, REFRESH_MS);
        return () => clearInterval(timer);
    }, [token, load]);

    const switchUser = e => {
        setData(null); // пока грузится дашборд другого сотрудника, чужие цифры за свои не выдаём
        setLoading(true);
        setViewUserId(e.target.value === "" ? null : Number(e.target.value));
    };

    if (loading && !data) return <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>;
    if (!data) {
        return (
            <div className="empty-state">
                <div className="empty-icon">⚠️</div>
                {error || "Не удалось загрузить главную"}
                <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "center" }}>
                    <button className="btn-ghost" onClick={load}>Повторить</button>
                    {foreign && <button className="btn-ghost" onClick={() => { setLoading(true); setViewUserId(null); }}>Мой дашборд</button>}
                </div>
            </div>
        );
    }

    const { tasks_today: today, overdue_tasks: overdue, stale_clients: stale, upcoming_events: events, pipeline } = data;
    const openStages = (pipeline?.stages ?? []).filter(s => s.kind === "open");
    const dealsTotal = openStages.reduce((sum, s) => sum + s.count, 0);
    const summary = [
        today.total > 0 && `${today.total} ${plural(today.total, "задача", "задачи", "задач")} на сегодня`,
        overdue.total > 0 && `${overdue.total} просрочено`,
        events.total > 0 && `${events.total} ${plural(events.total, "встреча", "встречи", "встреч")} впереди`,
    ].filter(Boolean).join(" · ") || "Срочных дел нет";

    const taskRow = (t, overdueRow) => (
        <Row
            key={t.id}
            onClick={() => onOpenTask(t.title)}
            left={<span className="home-dot" style={{ background: PRIORITY_COLORS[t.priority] }} title={PRIORITY_LABELS[t.priority]} />}
            title={t.title}
            sub={t.client_name ? `👤 ${t.client_name}` : undefined}
            right={overdueRow ? overdueText(t.deadline) : timeText(t.deadline)}
            rightTone={overdueRow ? "danger" : undefined}
        />
    );

    return (
        <div className="home">
            {error && <div className="home-banner">Не удалось обновить данные: {error}</div>}

            <div className="card" style={{ background: "linear-gradient(135deg, var(--accent) 0%, var(--accent-light) 100%)", border: "none" }}>
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                    <div>
                        <div style={{ fontSize: 18, fontWeight: 700, color: "#fff" }}>
                            {foreign ? `Дашборд сотрудника ${viewedName}` : `Привет, ${username}!`}
                        </div>
                        <div style={{ fontSize: 13, color: "rgba(255,255,255,0.85)", marginTop: 4 }}>
                            {new Date().toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long" })} · {summary}
                        </div>
                    </div>
                    {canManage && users.length > 1 && (
                        <select
                            className="form-input" style={{ width: "auto", minWidth: 150 }} aria-label="Чей дашборд"
                            value={foreign ? viewUserId : ""} onChange={switchUser}
                        >
                            <option value="">Мой дашборд</option>
                            {users.filter(u => u.id !== currentUserId).map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                        </select>
                    )}
                </div>
            </div>

            {overdue.total > 0 && (
                <Section title="Просрочено" tone="danger" total={overdue.total} shown={overdue.items.length}>
                    {overdue.items.map(t => taskRow(t, true))}
                </Section>
            )}

            <Section title="Задачи на сегодня" total={today.total} shown={today.items.length} empty="На сегодня задач нет">
                {today.items.map(t => taskRow(t, false))}
            </Section>

            <Section title="Ближайшие встречи и звонки" total={events.total} shown={events.items.length} empty="Запланированных событий нет">
                {events.items.map(e => (
                    <Row
                        key={e.id}
                        onClick={() => onOpenClient(e.client_id)}
                        left={<span>{INTERACTION_LABELS[e.type]?.icon ?? "📅"}</span>}
                        title={e.title || INTERACTION_LABELS[e.type]?.label || "Событие"}
                        sub={e.client_name}
                        right={whenText(e.starts_at)}
                    />
                ))}
            </Section>

            <Section
                title={`Клиенты без контакта более ${data.stale_days} ${plural(data.stale_days, "дня", "дней", "дней")}`}
                total={stale.total} shown={stale.items.length} empty="Со всеми клиентами недавно общались"
            >
                {stale.items.map(c => (
                    <Row
                        key={c.id}
                        onClick={() => onOpenClient(c.id)}
                        left={<span>👤</span>}
                        title={c.name}
                        sub={c.last_contact_at ? "Последний контакт был" : "Контактов ещё не было"}
                        right={`${c.days_since_contact} ${plural(c.days_since_contact, "день", "дня", "дней")}`}
                    />
                ))}
            </Section>

            <div className="card home-section">
                <div className="section-header">
                    <div className="section-title">{foreign ? "Сделки в работе" : "Мои сделки в работе"}{dealsTotal > 0 && <span className="home-count">{dealsTotal}</span>}</div>
                    <button className="btn-ghost" onClick={onOpenDeals}>Воронка</button>
                </div>
                {dealsTotal === 0 ? <div className="home-empty">Открытых сделок нет</div> : (
                    <div className="home-stages">
                        {openStages.map(s => (
                            <div key={s.stage_id} className="home-stage">
                                <div className="home-stage-name"><span className="home-dot" style={{ background: stageColor(s) }} />{s.name}</div>
                                <div className="home-stage-count">{s.count}</div>
                                <div className="home-stage-sum">{totalsText(s.totals)}</div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
