import { useState, useEffect, useCallback, useMemo } from "react";
import { apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { CAL_WEEKDAYS } from "../constants/calendar";
import { CMDK_TASK_STATUS_LABELS } from "../constants/commandPalette";
import { ICONS } from "../constants/icons";
import { PRIORITY_COLORS, PRIORITY_LABELS } from "../constants/priority";
import { parseBackendDate, formatDeadline } from "../utils/date";

export function DeadlineCalendarTab({ token, onOpenTask }) {
    const today = new Date();
    const [cursor, setCursor] = useState(new Date(today.getFullYear(), today.getMonth(), 1));
    const [tasks, setTasks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [projectId, setProjectId] = useState("");
    const [onlyMine, setOnlyMine] = useState(false);
    const [onlyAuthor, setOnlyAuthor] = useState(false);
    const [projects, setProjects] = useState([]);
    const [selectedDay, setSelectedDay] = useState(null); // "YYYY-MM-DD" | null

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
    const selectedTasks = selectedDay ? (tasksByDay[selectedDay] ?? []) : [];

    const monthLabel = cursor.toLocaleDateString("ru-RU", { month: "long", year: "numeric" });

    return (
        <div style={{ padding: "16px 16px 32px" }}>
            <div className="card" style={{ marginTop: 0 }}>
                <div className="section-header" style={{ flexWrap: "wrap", gap: 12 }}>
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
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <select className="input input-sm" style={{ width: 160 }} value={projectId} onChange={e => setProjectId(e.target.value)}>
                            <option value="">Все проекты</option>
                            {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                        </select>
                        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: "pointer" }}>
                            <input type="checkbox" checked={onlyMine} onChange={e => { setOnlyMine(e.target.checked); if (e.target.checked) setOnlyAuthor(false); }} />
                            Я исполнитель
                        </label>
                        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: "pointer" }}>
                            <input type="checkbox" checked={onlyAuthor} onChange={e => { setOnlyAuthor(e.target.checked); if (e.target.checked) setOnlyMine(false); }} />
                            Я автор
                        </label>
                        <button className="btn btn-ghost btn-sm" onClick={() => loadTasks(gridStart, gridEnd, projectId, onlyMine, onlyAuthor)} disabled={loading}>
                            <Icon d={ICONS.refresh} /> {loading ? "…" : "Обновить"}
                        </button>
                    </div>
                </div>

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
                            const dayTasks = tasksByDay[key] ?? [];
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
                                    onClick={() => dayTasks.length > 0 && setSelectedDay(isSelected ? null : key)}
                                    style={{
                                        minHeight: 68,
                                        borderRadius: 8,
                                        padding: "6px 6px 8px",
                                        background: isSelected ? "var(--surface2)" : "var(--surface)",
                                        border: isToday ? "1.5px solid var(--accent)" : "1px solid var(--border)",
                                        opacity: inMonth ? 1 : 0.4,
                                        cursor: dayTasks.length > 0 ? "pointer" : "default",
                                        display: "flex",
                                        flexDirection: "column",
                                        gap: 4,
                                    }}
                                >
                                    <div style={{ fontSize: 12, fontWeight: isToday ? 700 : 500, color: isToday ? "var(--accent)" : "var(--text)" }}>
                                        {d.getDate()}
                                    </div>
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
                        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-muted)", marginBottom: 10 }}>
                            📅 {new Date(selectedDay).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })}
                            {" · "}{selectedTasks.length} {selectedTasks.length === 1 ? "задача" : "задач"}
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
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
            </div>
        </div>
    );
}
