import { useState, useEffect, useMemo } from "react";
import { apiRequest } from "../api";
import { Icon } from "./Icon";
import { ICONS } from "../constants/icons";
import { PRIORITY_COLORS } from "../constants/priority";
import { parseBackendDate, formatDeadline } from "../utils/date";

export function SidebarDeadlineWidget({ token, onOpenTask, onOpenFullCalendar }) {
    const today = new Date();
    const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const [cursor, setCursor] = useState(new Date(today.getFullYear(), today.getMonth(), 1));
    const [tasks, setTasks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [selectedDay, setSelectedDay] = useState(null);

    const monthStart = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const gridStart = new Date(monthStart);
    const startOffset = (monthStart.getDay() + 6) % 7;
    gridStart.setDate(gridStart.getDate() - startOffset);
    const gridEnd = new Date(gridStart);
    gridEnd.setDate(gridEnd.getDate() + 42);

    // Диапазон запроса берём с запасом: сетка месяца + минимум 30 дней вперёд
    // от сегодня, чтобы список «Ближайшие дедлайны» не зависел от того, какой
    // месяц сейчас пролистан в мини-календаре.
    const upcomingHorizon = new Date(todayStart);
    upcomingHorizon.setDate(upcomingHorizon.getDate() + 31);
    const rangeFrom = gridStart < todayStart ? gridStart : todayStart;
    const rangeTo = gridEnd > upcomingHorizon ? gridEnd : upcomingHorizon;

    useEffect(() => {
        if (!token) return;
        let cancelled = false;
        setLoading(true);
        apiRequest({ path: `/tasks/calendar?date_from=${rangeFrom.toISOString()}&date_to=${rangeTo.toISOString()}`, token })
            .then(data => { if (!cancelled) setTasks(Array.isArray(data) ? data : []); })
            .catch(() => { if (!cancelled) setTasks([]); })
            .finally(() => { if (!cancelled) setLoading(false); });
        setSelectedDay(null);
        return () => { cancelled = true; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token, cursor.getFullYear(), cursor.getMonth()]);

    const dayKey = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

    const tasksByDay = useMemo(() => {
        const map = {};
        for (const t of tasks) {
            const d = parseBackendDate(t.deadline);
            if (!d) continue;
            const key = dayKey(d);
            (map[key] ??= []).push(t);
        }
        return map;
    }, [tasks]);

    const cells = useMemo(() => {
        const arr = [];
        const d = new Date(gridStart);
        for (let i = 0; i < 42; i++) { arr.push(new Date(d)); d.setDate(d.getDate() + 1); }
        return arr;
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [cursor.getFullYear(), cursor.getMonth()]);

    const topPriorityColor = (dayTasks) => {
        const order = ["critical", "high", "medium", "low"];
        const sorted = [...dayTasks].sort((a, b) => order.indexOf(a.priority) - order.indexOf(b.priority));
        return PRIORITY_COLORS[sorted[0]?.priority] ?? PRIORITY_COLORS.medium;
    };

    const todayKey = dayKey(today);
    const monthLabel = cursor.toLocaleDateString("ru-RU", { month: "long", year: "numeric" });

    const upcomingList = useMemo(() => {
        return tasks
            .filter(t => {
                const d = parseBackendDate(t.deadline);
                return d && d >= todayStart;
            })
            .sort((a, b) => parseBackendDate(a.deadline) - parseBackendDate(b.deadline))
            .slice(0, 6);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tasks]);

    const listItems = selectedDay ? (tasksByDay[selectedDay] ?? []) : upcomingList;
    const listTitle = selectedDay
        ? new Date(selectedDay).toLocaleDateString("ru-RU", { day: "numeric", month: "long" })
        : "Ближайшие дедлайны";

    return (
        <div className="card">
            <div className="section-header">
                <div className="section-title"><Icon d={ICONS.calendar} /> Календарь</div>
                {onOpenFullCalendar && (
                    <button className="btn btn-ghost btn-sm" onClick={onOpenFullCalendar}>Открыть →</button>
                )}
            </div>

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                <button className="btn btn-ghost btn-sm" style={{ padding: "2px 6px" }} onClick={() => setCursor(c => new Date(c.getFullYear(), c.getMonth() - 1, 1))}>
                    <Icon d={ICONS.chevronL} size={14} />
                </button>
                <span style={{ fontSize: 12, fontWeight: 600, textTransform: "capitalize", color: "var(--text-muted)" }}>{monthLabel}</span>
                <button className="btn btn-ghost btn-sm" style={{ padding: "2px 6px" }} onClick={() => setCursor(c => new Date(c.getFullYear(), c.getMonth() + 1, 1))}>
                    <Icon d={ICONS.chevronR} size={14} />
                </button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 2, marginBottom: 2 }}>
                {["П", "В", "С", "Ч", "П", "С", "В"].map((w, i) => (
                    <div key={i} style={{ textAlign: "center", fontSize: 10, color: "var(--text-muted)" }}>{w}</div>
                ))}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 2, opacity: loading ? 0.5 : 1 }}>
                {cells.map(d => {
                    const key = dayKey(d);
                    const dayTasks = tasksByDay[key] ?? [];
                    const inMonth = d.getMonth() === cursor.getMonth();
                    const isToday = key === todayKey;
                    const isSelected = key === selectedDay;
                    return (
                        <div
                            key={key}
                            onClick={() => dayTasks.length > 0 && setSelectedDay(isSelected ? null : key)}
                            title={dayTasks.map(t => t.title).join(", ")}
                            style={{
                                aspectRatio: "1", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                                borderRadius: 5, fontSize: 10.5,
                                background: isSelected ? "var(--surface2)" : "transparent",
                                border: isToday ? "1px solid var(--accent)" : "1px solid transparent",
                                opacity: inMonth ? 1 : 0.35,
                                cursor: dayTasks.length > 0 ? "pointer" : "default",
                                color: isToday ? "var(--accent)" : "var(--text)",
                                fontWeight: isToday ? 700 : 400,
                            }}
                        >
                            <span>{d.getDate()}</span>
                            {dayTasks.length > 0 && (
                                <span style={{ width: 4, height: 4, borderRadius: "50%", background: topPriorityColor(dayTasks), marginTop: 1 }} />
                            )}
                        </div>
                    );
                })}
            </div>

            <div className="divider" style={{ margin: "12px 0" }} />

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: selectedDay ? "capitalize" : "none" }}>
                    {listTitle}
                </div>
                {selectedDay && (
                    <button className="btn btn-ghost btn-sm" style={{ padding: "1px 6px", fontSize: 11 }} onClick={() => setSelectedDay(null)}>✕</button>
                )}
            </div>

            {loading ? (
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Загрузка…</div>
            ) : listItems.length === 0 ? (
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                    {selectedDay ? "Нет задач с дедлайном в этот день" : "Нет ближайших дедлайнов"}
                </div>
            ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {listItems.map(t => {
                        const dl = formatDeadline(t.deadline);
                        return (
                            <div
                                key={t.id}
                                onClick={() => onOpenTask?.(t.title)}
                                style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}
                            >
                                <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0, background: PRIORITY_COLORS[t.priority] ?? PRIORITY_COLORS.medium }} />
                                <span style={{ fontSize: 12.5, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.title}</span>
                                {dl && (
                                    <span style={{ fontSize: 10.5, color: dl.isOverdue ? "var(--red)" : "var(--text-muted)", flexShrink: 0 }}>
                                        {dl.isToday ? "сегодня" : dl.fmt}
                                    </span>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
