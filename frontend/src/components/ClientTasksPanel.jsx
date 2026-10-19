import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "../api";
import { PRIORITY_COLORS, PRIORITY_LABELS } from "../constants/priority";
import { formatDeadline } from "../utils/date";

const STATUS_LABELS = { backlog: "Очередь", todo: "Новая", in_progress: "В работе", review: "На проверке", done: "Готово" };
const PAGE_SIZE = 50;

/**
 * Задачи клиента (GET /tasks/filter?client_id=): открытые сверху, выполненные ниже. Быстрое добавление задачи уже
 * привязанной к этому клиенту и отметка «выполнено». Видимость задач общая для команды, как и в основном списке.
 */
export function ClientTasksPanel({ token, clientId, users, currentUserId, onChanged }) {
    const [data, setData] = useState({ items: [], total: 0 });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [title, setTitle] = useState("");
    const [deadline, setDeadline] = useState("");
    const [assignee, setAssignee] = useState(currentUserId ?? "");
    const [busy, setBusy] = useState(false);

    const load = useCallback(async () => {
        try {
            const res = await apiRequest({ path: `/tasks/filter?client_id=${clientId}&page=1&size=${PAGE_SIZE}`, token });
            setData({ items: res?.items ?? [], total: res?.total ?? 0 });
            setError(null);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }, [token, clientId]);

    useEffect(() => { load(); }, [load]);

    const run = async action => {
        setBusy(true);
        setError(null);
        try {
            await action();
            await load();
            await onChanged?.();
        } catch (e) {
            setError(e.message);
        } finally {
            setBusy(false);
        }
    };

    const add = e => {
        e.preventDefault();
        if (!title.trim()) return;
        return run(async () => {
            await apiRequest({
                path: "/tasks", method: "POST", token,
                body: {
                    title: title.trim(),
                    client_id: clientId,
                    user_id: assignee ? Number(assignee) : null,
                    deadline: deadline ? new Date(deadline).toISOString() : null,
                },
            });
            setTitle(""); setDeadline("");
        });
    };

    const toggle = task => run(() => apiRequest({
        path: `/tasks/${task.id}/status`, method: "PATCH", token,
        body: { status: task.status === "done" ? "todo" : "done" },
    }));

    // открытые — по сроку (без срока в конце), выполненные — после них
    const items = [...data.items].sort((a, b) => {
        const done = x => (x.status === "done" ? 1 : 0);
        if (done(a) !== done(b)) return done(a) - done(b);
        const time = x => (x.deadline ? new Date(x.deadline).getTime() : Infinity);
        return time(a) - time(b);
    });

    if (loading) return <div style={{ color: "var(--text-muted)" }}>Загрузка…</div>;

    return (
        <div>
            {error && <div className="alert" style={{ marginBottom: 10 }}>{error}</div>}

            <form onSubmit={add} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
                <input
                    style={{ flex: "1 1 220px" }} placeholder="Новая задача по клиенту…" value={title} maxLength={200}
                    onChange={e => setTitle(e.target.value)}
                />
                <input type="datetime-local" value={deadline} onChange={e => setDeadline(e.target.value)} style={{ flex: "0 1 200px" }} />
                <select value={assignee} onChange={e => setAssignee(e.target.value)} style={{ flex: "0 1 160px" }}>
                    <option value="">Никому</option>
                    {users.map(u => <option key={u.id} value={u.id}>{u.id === currentUserId ? "Мне" : u.username}</option>)}
                </select>
                <button className="btn btn-primary btn-sm" type="submit" disabled={busy || !title.trim()}>Добавить</button>
            </form>

            {items.length === 0 ? (
                <div className="empty-state"><div className="empty-icon">✅</div>Задач по этому клиенту нет</div>
            ) : items.map(task => {
                const dl = formatDeadline(task.deadline);
                const done = task.status === "done";
                return (
                    <div key={task.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 0", borderBottom: "1px solid var(--border)" }}>
                        <input
                            type="checkbox" checked={done} disabled={busy} onChange={() => toggle(task)}
                            title={done ? "Вернуть в работу" : "Отметить выполненной"}
                            style={{ width: 16, height: 16, accentColor: "var(--accent)", cursor: "pointer" }}
                        />
                        <span className="home-dot" style={{ background: PRIORITY_COLORS[task.priority] }} title={PRIORITY_LABELS[task.priority]} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 14, textDecoration: done ? "line-through" : "none", color: done ? "var(--text-muted)" : "var(--text)" }}>
                                <span className="task-id">#{task.id}</span> {task.title}
                            </div>
                            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                                {STATUS_LABELS[task.status] ?? task.status}
                                {task.user?.username ? ` · @${task.user.username}` : ""}
                            </div>
                        </div>
                        {dl && !done && (
                            <span className={`meta-chip${dl.isOverdue ? " overdue" : dl.isToday ? " today" : ""}`} style={{ fontSize: 11 }}>📅 {dl.fmt}</span>
                        )}
                    </div>
                );
            })}
            {data.total > items.length && (
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 8 }}>
                    Показаны первые {items.length} из {data.total}. Остальные — в разделе «Задачи» по фильтру клиента.
                </div>
            )}
        </div>
    );
}
