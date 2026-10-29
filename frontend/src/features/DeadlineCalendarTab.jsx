import { useState, useEffect, useCallback, useMemo } from "react";
import { apiRequest } from "../api";
import { EventFormModal } from "../components/EventFormModal";
import { Icon } from "../components/Icon";
import { CAL_WEEKDAYS } from "../constants/calendar";
import { CMDK_TASK_STATUS_LABELS } from "../constants/commandPalette";
import { EVENT_STATUS_LABELS, INTERACTION_LABELS, emptyToNull, formatEventWhen } from "../constants/crm";
import { ICONS } from "../constants/icons";
import { userName, useUsersMap } from "../hooks/useUsersMap";
import { PRIORITY_COLORS, PRIORITY_LABELS } from "../constants/priority";
import { parseBackendDate, formatDeadline } from "../utils/date";

export function DeadlineCalendarTab({ token, onOpenTask, onOpenClient, currentUserId, canManage }) {
    const today = new Date();
    const { users, usersById } = useUsersMap(token);
    const [cursor, setCursor] = useState(new Date(today.getFullYear(), today.getMonth(), 1));
    const [tasks, setTasks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [projectId, setProjectId] = useState("");
    const [onlyMine, setOnlyMine] = useState(false);
    const [onlyAuthor, setOnlyAuthor] = useState(false);
    const [projects, setProjects] = useState([]);
    const [selectedDay, setSelectedDay] = useState(null); // "YYYY-MM-DD" | null
    // Слой запланированных встреч и звонков (GET /events): отдельный запрос, свои переключатели
    const [events, setEvents] = useState([]);
    const [showTasks, setShowTasks] = useState(true);
    const [showEvents, setShowEvents] = useState(true);
    const [onlyMyEvents, setOnlyMyEvents] = useState(false);
    const [eventModal, setEventModal] = useState(null); // null | { event?, day? }
    const [completing, setCompleting] = useState(null); // { id, summary }
    const [eventBusy, setEventBusy] = useState(false);

    useEffect(() => {
        if (!token) return;
        apiRequest({ path: "/projects?page=1&size=50", token })
            .then(data => setProjects(Array.isArray(data) ? data : (data.items ?? [])))
            .catch(() => { });
    }, [token]);

    // Диапазон запроса — весь видимый месяц (плюс с запасом захватывает соседние
    // дни, попадающие в сетку календаря, чтобы точки на них тоже показывались).
    const monthStart = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const monthEnd = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
    const gridStart = new Date(monthStart);
    // Понедельник как первый день недели
    const startOffset = (monthStart.getDay() + 6) % 7;
    gridStart.setDate(gridStart.getDate() - startOffset);
    const gridEnd = new Date(gridStart);
    gridEnd.setDate(gridEnd.getDate() + 42); // 6 недель сетки — с запасом

    const loadTasks = useCallback(async (from, to, pid, mine, author) => {
        setLoading(true);
        setError(null);
        try {
            const params = new URLSearchParams();
            params.set("date_from", from.toISOString());
            params.set("date_to", to.toISOString());
            if (pid) params.set("project_id", pid);
            if (mine) params.set("only_mine", "true");
            if (author) params.set("only_author", "true");
            const data = await apiRequest({ path: `/tasks/calendar?${params}`, token });
            setTasks(Array.isArray(data) ? data : []);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => {
        if (!token) return;
        loadTasks(gridStart, gridEnd, projectId, onlyMine, onlyAuthor);
        setSelectedDay(null);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token, cursor, projectId, onlyMine, onlyAuthor, loadTasks]);

    const loadEvents = useCallback(async (from, to, mine) => {
        try {
            const params = new URLSearchParams({ from: from.toISOString(), to: to.toISOString(), size: "500" });
            if (mine && currentUserId) params.set("assignee_id", currentUserId);
            const data = await apiRequest({ path: `/events?${params}`, token });
            setEvents(data?.items ?? []);
        } catch (e) {
            setError(e.message);
        }
    }, [token, currentUserId]);

    useEffect(() => {
        if (!token) return;
        if (!showEvents) { setEvents([]); return; }
        loadEvents(gridStart, gridEnd, onlyMyEvents);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token, cursor, showEvents, onlyMyEvents, loadEvents]);

    const dayKey = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

    // Группируем задачи по дню дедлайна (в локальном времени пользователя)
    const tasksByDay = useMemo(() => {
        const map = {};
        for (const t of tasks) {
            const d = parseBackendDate(t.deadline);
            if (!d) continue;
            const key = dayKey(d);
            if (!map[key]) map[key] = [];
            map[key].push(t);
        }
        return map;
    }, [tasks]);

    const eventsByDay = useMemo(() => {
        const map = {};
        for (const ev of events) {
            const d = new Date(ev.starts_at);
            if (isNaN(d.getTime())) continue;
            const key = dayKey(d);
            (map[key] ||= []).push(ev);
        }
        return map;
    }, [events]);

    const cells = useMemo(() => {
        const arr = [];
        const d = new Date(gridStart);
        for (let i = 0; i < 42; i++) {
            arr.push(new Date(d));
            d.setDate(d.getDate() + 1);
        }
        return arr;
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [cursor]);

    const todayKey = dayKey(today);
    const selectedTasks = selectedDay && showTasks ? (tasksByDay[selectedDay] ?? []) : [];
    const selectedEvents = selectedDay && showEvents ? (eventsByDay[selectedDay] ?? []) : [];

    const canActOn = ev => canManage || ev.assignee_id === currentUserId;
    const runEventAction = async action => {
        setEventBusy(true);
        setError(null);
        try {
            await action();
            await loadEvents(gridStart, gridEnd, onlyMyEvents);
        } catch (e) {
            setError(e.message);
        } finally {
            setEventBusy(false);
        }
    };
    const completeEvent = ev => runEventAction(async () => {
        await apiRequest({ path: `/events/${ev.id}/complete`, method: "POST", token, body: { summary: emptyToNull(completing?.summary ?? "") } });
        setCompleting(null);
    });
    const cancelEvent = ev => runEventAction(() => apiRequest({ path: `/events/${ev.id}`, method: "PATCH", token, body: { status: "cancelled" } }));

    const monthLabel = cursor.toLocaleDateString("ru-RU", { month: "long", year: "numeric" });

    return (
        <div className="cl-page">
            <div className="cl-head">
                <div>
                    <h1 className="cl-title">Календарь</h1>
                    <div className="cl-sub">Сроки задач, встречи и звонки</div>
                </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => setCursor(c => new Date(c.getFullYear(), c.getMonth() - 1, 1))}>
                            <Icon d={ICONS.chevronL} />
                        </button>
                        <div className="section-title" style={{ minWidth: 180, textTransform: "capitalize" }}>
                            <Icon d={ICONS.calendar} /> {monthLabel}
                        </div>
                        <button className="btn btn-ghost btn-sm" onClick={() => setCursor(c => new Date(c.getFullYear(), c.getMonth() + 1, 1))}>
                            <Icon d={ICONS.chevronR} />
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={() => setCursor(new Date(today.getFullYear(), today.getMonth(), 1))}>
                            Сегодня
                        </button>
                    </div>
            </div>
                    <div className="cl-filters">
                        <select className="form-input dl-select" aria-label="Проект" value={projectId} onChange={e => setProjectId(e.target.value)}>
                            <option value="">Все проекты</option>
                            {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                        </select>
                        <label className="cl-check">
                            <input type="checkbox" checked={showTasks} onChange={e => setShowTasks(e.target.checked)} />
                            Задачи
                        </label>
                        <label className="cl-check">
                            <input type="checkbox" checked={showEvents} onChange={e => setShowEvents(e.target.checked)} />
                            Встречи и звонки
                        </label>
                        {showEvents && (
                            <label className="cl-check">
                                <input type="checkbox" checked={onlyMyEvents} onChange={e => setOnlyMyEvents(e.target.checked)} />
                                Только мои
                            </label>
                        )}
                        <label className="cl-check">
                            <input type="checkbox" checked={onlyMine} onChange={e => { setOnlyMine(e.target.checked); if (e.target.checked) setOnlyAuthor(false); }} />
                            Я исполнитель
                        </label>
                        <label className="cl-check">
                            <input type="checkbox" checked={onlyAuthor} onChange={e => { setOnlyAuthor(e.target.checked); if (e.target.checked) setOnlyMine(false); }} />
                            Я автор
                        </label>
                        <button className="btn btn-ghost" onClick={() => { loadTasks(gridStart, gridEnd, projectId, onlyMine, onlyAuthor); if (showEvents) loadEvents(gridStart, gridEnd, onlyMyEvents); }} disabled={loading}>
                            <Icon d={ICONS.refresh} /> {loading ? "…" : "Обновить"}
                        </button>
                    </div>
            <div className="card cal-card">
                {error && <div className="alert" style={{ marginBottom: 12 }}>{error}</div>}

                <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 6, marginBottom: 6 }}>
                    {CAL_WEEKDAYS.map(w => (
                        <div key={w} style={{ textAlign: "center", fontSize: 12, fontWeight: 600, color: "var(--text-muted)", padding: "4px 0" }}>
                            {w}
                        </div>
                    ))}
                </div>

                {loading ? (
                    <div className="empty-state" style={{ padding: "40px 0" }}><div className="empty-icon">⏳</div>Загрузка…</div>
                ) : (
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 6 }}>
                        {cells.map(d => {
                            const key = dayKey(d);
                            const dayTasks = showTasks ? (tasksByDay[key] ?? []) : [];
                            const dayEvents = showEvents ? (eventsByDay[key] ?? []) : [];
                            const inMonth = d.getMonth() === cursor.getMonth();
                            const isToday = key === todayKey;
                            const isSelected = key === selectedDay;
                            // Показываем максимум 3 точки, приоритет — по важности задачи
                            const dots = [...dayTasks]
                                .sort((a, b) => ["critical", "high", "medium", "low"].indexOf(a.priority) - ["critical", "high", "medium", "low"].indexOf(b.priority))
                                .slice(0, 3);
                            return (
                                <div
                                    key={key}
                                    className="cal-cell"
                                    onClick={() => setSelectedDay(isSelected ? null : key)}
                                    style={{
                                                                                borderRadius: 8,
                                        padding: "6px 6px 8px",
                                        background: isSelected ? "var(--surface2)" : "var(--surface)",
                                        border: isToday ? "1.5px solid var(--accent)" : "1px solid var(--border)",
                                        opacity: inMonth ? 1 : 0.4,
                                        cursor: "pointer",
                                        display: "flex",
                                        flexDirection: "column",
                                        gap: 4,
                                    }}
                                >
                                    <div style={{ fontSize: 12, fontWeight: isToday ? 700 : 500, color: isToday ? "var(--accent)" : "var(--text)" }}>
                                        {d.getDate()}
                                    </div>
                                    {dayEvents.length > 0 && (
                                        <div style={{ display: "flex", gap: 2, flexWrap: "wrap", fontSize: 11, lineHeight: 1 }}>
                                            {dayEvents.slice(0, 3).map(ev => (
                                                <span key={ev.id} title={`${new Date(ev.starts_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })} ${ev.title || INTERACTION_LABELS[ev.type]?.label || ""} · ${ev.client_name ?? ""}`}
                                                    style={{ opacity: ev.status === "done" ? 0.45 : 1 }}>
                                                    {INTERACTION_LABELS[ev.type]?.icon ?? "📅"}
                                                </span>
                                            ))}
                                            {dayEvents.length > 3 && <span style={{ fontSize: 10, color: "var(--text-muted)" }}>+{dayEvents.length - 3}</span>}
                                        </div>
                                    )}
                                    {dayTasks.length > 0 && (
                                        <>
                                            <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                                                {dots.map(t => (
                                                    <span key={t.id} title={t.title} style={{
                                                        width: 7, height: 7, borderRadius: "50%",
                                                        background: PRIORITY_COLORS[t.priority] ?? PRIORITY_COLORS.medium,
                                                        display: "inline-block",
                                                    }} />
                                                ))}
                                            </div>
                                            {dayTasks.length > 3 && (
                                                <div style={{ fontSize: 10, color: "var(--text-muted)" }}>+{dayTasks.length - 3}</div>
                                            )}
                                        </>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}

                {selectedDay && (
                    <div style={{ marginTop: 20, borderTop: "1px solid var(--border)", paddingTop: 16 }}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
                            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-muted)" }}>
                                📅 {new Date(`${selectedDay}T00:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })}
                                {showTasks && <>{" · "}{selectedTasks.length} {selectedTasks.length === 1 ? "задача" : "задач"}</>}
                                {showEvents && <>{" · "}{selectedEvents.length} {selectedEvents.length === 1 ? "событие" : "событий"}</>}
                            </div>
                            <button className="btn btn-primary btn-sm" onClick={() => setEventModal({ day: selectedDay })}>
                                <Icon d={ICONS.plus} /> Запланировать
                            </button>
                        </div>
                        {selectedTasks.length === 0 && selectedEvents.length === 0 && (
                            <div style={{ fontSize: 13, color: "var(--text-muted)" }}>На этот день ничего нет</div>
                        )}
                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                            {selectedEvents.map(ev => {
                                const type = INTERACTION_LABELS[ev.type] ?? { icon: "📅", label: ev.type };
                                const done = ev.status === "done";
                                return (
                                    <div key={`e${ev.id}`} style={{ padding: "8px 12px", borderRadius: 8, background: "var(--surface2)", opacity: done ? 0.7 : 1 }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                                            <span title={type.label}>{type.icon}</span>
                                            <span style={{ flex: 1, minWidth: 120, fontSize: 14 }}>
                                                {ev.title || type.label}
                                                {ev.client_name && (
                                                    <>
                                                        {" · "}
                                                        <a href="#client" style={{ color: "var(--accent-light)" }} onClick={e => { e.preventDefault(); onOpenClient?.(ev.client_id); }}>{ev.client_name}</a>
                                                    </>
                                                )}
                                            </span>
                                            <span className="meta-chip" style={{ fontSize: 11 }}>{formatEventWhen(ev.starts_at, ev.duration_minutes)}</span>
                                            <span className="meta-chip" style={{ fontSize: 11 }}>{userName(usersById, ev.assignee_id)}</span>
                                            <span className="meta-chip" style={{ fontSize: 11, color: done ? "var(--green)" : undefined }}>{EVENT_STATUS_LABELS[ev.status] ?? ev.status}</span>
                                            {ev.status === "planned" && canActOn(ev) && (
                                                <>
                                                    <button className="btn btn-primary btn-sm" disabled={eventBusy} onClick={() => setCompleting({ id: ev.id, summary: ev.notes ?? "" })}>Состоялась</button>
                                                    <button className="btn btn-ghost btn-sm" onClick={() => setEventModal({ event: ev })} title="Изменить"><Icon d={ICONS.edit} /></button>
                                                    <button className="btn btn-ghost btn-sm" disabled={eventBusy} onClick={() => cancelEvent(ev)}>Отменить</button>
                                                </>
                                            )}
                                        </div>
                                        {completing?.id === ev.id && (
                                            <div style={{ marginTop: 10 }}>
                                                <label className="form-label">Итог — станет записью в «Взаимодействиях» (время — сейчас)</label>
                                                <textarea className="form-input" rows={3} maxLength={5000} autoFocus value={completing.summary} onChange={e => setCompleting(c => ({ ...c, summary: e.target.value }))} />
                                                <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 8 }}>
                                                    <button className="btn btn-ghost btn-sm" onClick={() => setCompleting(null)}>Отмена</button>
                                                    <button className="btn btn-primary btn-sm" disabled={eventBusy} onClick={() => completeEvent(ev)}>Сохранить</button>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                            {selectedTasks.map(t => {
                                const dl = formatDeadline(t.deadline);
                                return (
                                    <div
                                        key={t.id}
                                        onClick={() => onOpenTask?.(t.title)}
                                        style={{
                                            display: "flex", alignItems: "center", gap: 10,
                                            padding: "8px 12px", borderRadius: 8,
                                            background: "var(--surface2)", cursor: "pointer",
                                        }}
                                    >
                                        <span style={{
                                            fontSize: 11, padding: "2px 6px", borderRadius: 4, fontWeight: 600,
                                            background: (PRIORITY_COLORS[t.priority] ?? PRIORITY_COLORS.medium) + "22",
                                            color: PRIORITY_COLORS[t.priority] ?? PRIORITY_COLORS.medium,
                                        }}>
                                            {PRIORITY_LABELS[t.priority] ?? t.priority}
                                        </span>
                                        <span style={{ flex: 1, fontSize: 14 }}>{t.title}</span>
                                        {dl && (
                                            <span className="meta-chip" style={{ fontSize: 11, color: dl.isOverdue ? "var(--red)" : undefined }}>
                                                {dl.fmt}
                                            </span>
                                        )}
                                        <span className="meta-chip" style={{ fontSize: 11 }}>{CMDK_TASK_STATUS_LABELS[t.status] ?? t.status}</span>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}
                {eventModal && (
                    <EventFormModal
                        token={token} event={eventModal.event ?? null} clientId={eventModal.event?.client_id ?? null}
                        defaultDay={eventModal.day ?? null} users={users} currentUserId={currentUserId}
                        onClose={() => setEventModal(null)}
                        onSaved={() => loadEvents(gridStart, gridEnd, onlyMyEvents)}
                    />
                )}
            </div>
        </div>
    );
}
