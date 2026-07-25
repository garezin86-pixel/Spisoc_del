import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, apiRequest, clearTokens, getRefreshToken, saveTokens } from "./api";
import AttachmentsPanel from "./AttachmentsPanel";

// ── WebSocket hook ────────────────────────────────────────────────────────────
function useWebSocket(token, onEvent) {
    const wsRef = useRef(null);
    const reconnectRef = useRef(null);
    const mountedRef = useRef(true);

    const connect = useCallback(() => {
        if (!token || !mountedRef.current) return;

        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const host = window.location.host;
        const url = `${protocol}//${host}/api/ws?token=${token}`;

        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
            console.log("[WS] connected");
            if (reconnectRef.current) {
                clearTimeout(reconnectRef.current);
                reconnectRef.current = null;
            }
        };

        ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                if (msg.event === "pong") return;
                onEvent(msg.event, msg.data);
            } catch { }
        };

        ws.onclose = (e) => {
            console.log("[WS] disconnected, reconnecting in 3s...", e.code);
            if (mountedRef.current && e.code !== 4001) {
                reconnectRef.current = setTimeout(connect, 3000);
            }
        };

        ws.onerror = () => ws.close();
    }, [token, onEvent]);

    useEffect(() => {
        mountedRef.current = true;
        connect();

        // Keepalive ping каждые 25 сек
        const ping = setInterval(() => {
            if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send("ping");
            }
        }, 25000);

        return () => {
            mountedRef.current = false;
            clearTimeout(reconnectRef.current);
            clearInterval(ping);
            wsRef.current?.close();
        };
    }, [connect]);
}

// ─── Helpers ──────────────────────────────────────────────
const initialForm = { title: "", description: "", deadline: "", priority: "medium", project_id: "", recurrence_rule: "none", status: "todo" };

function decodeToken(token) {
    try {
        const payload = token.split(".")[1];
        const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
        const padded = base64.padEnd(base64.length + (4 - (base64.length % 4)) % 4, "=");
        const bytes = Uint8Array.from(atob(padded), c => c.charCodeAt(0));
        return JSON.parse(new TextDecoder("utf-8").decode(bytes));
    } catch { return null; }
}

function parseBackendDate(deadline) {
    if (!deadline) return null;
    const m = String(deadline).match(/^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})/);
    if (m) return new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]), Number(m[4]), Number(m[5]));
    const d = new Date(deadline);
    return isNaN(d.getTime()) ? null : d;
}

function formatDeadline(deadline) {
    if (!deadline) return null;
    try {
        const d = parseBackendDate(deadline);
        if (!d) return null;
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const dDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
        const diff = dDay - today;
        const isFmt = /^\d{2}\.\d{2}/.test(String(deadline));
        return {
            fmt: isFmt ? String(deadline) : d.toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }),
            isOverdue: diff < 0,
            isToday: diff === 0,
        };
    } catch { return null; }
}

function extractItems(data) {
    if (!data) return [];
    let items;
    if (Array.isArray(data)) items = data;
    else if (Array.isArray(data.items)) items = data.items;
    else return [];
    // Дедупликация по id — защита от двойного вызова (StrictMode, race conditions)
    const seen = new Set();
    return items.filter(item => {
        if (item?.id == null) return true;
        if (seen.has(item.id)) return false;
        seen.add(item.id);
        return true;
    });
}

const ROLE_LABELS = { admin: "Админ", manager: "Менеджер", user: "Участник" };
const ROLE_COLORS = {
    admin: { color: "var(--red)", bg: "var(--red-dim)" },
    manager: { color: "var(--amber)", bg: "var(--amber-dim)" },
    user: { color: "var(--accent-light)", bg: "rgba(124,106,240,0.12)" },
};

// ─── Icons ────────────────────────────────────────────────
function Icon({ d, size = 14 }) {
    return (
        <svg
            viewBox="0 0 24 24"
            style={{
                width: size,
                height: size,
                minWidth: size,
                minHeight: size,
                flexShrink: 0,
                display: "inline-block",
                verticalAlign: "middle",
                fill: "currentColor",
            }}
        >
            <path d={d} />
        </svg>
    );
}
const ICONS = {
    check: "M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z",
    x: "M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
    edit: "M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 000-1.41l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z",
    trash: "M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z",
    restore: "M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z",
    chart: "M5 9.2h3V19H5zM10.6 5h2.8v14h-2.8zm5.6 8H19v6h-2.8z",
    refresh: "M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z",
    plus: "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z",
    clock: "M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67V7z",
    user: "M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z",
    group: "M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z",
    save: "M17 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14c1.1 0 2-.9 2-2V7l-4-4zm-5 16c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm3-10H5V5h10v4z",
    logout: "M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5zM4 5h8V3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h8v-2H4V5z",
    filter: "M10 18h4v-2h-4v2zM3 6v2h18V6H3zm3 7h12v-2H6v2z",
    comment: "M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z",
    reassign: "M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z",
    chevronL: "M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z",
    chevronR: "M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z",
    userPlus: "M15 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm-9-2V7H4v3H1v2h3v3h2v-3h3v-2H6zm9 4c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z",
    userMinus: "M14 14.252V16h-4v2H2v-2c0-2.21 3.582-4 8-4 1.506 0 2.919.281 4 .752zM12 13c-3.315 0-6-2.685-6-6s2.685-6 6-6 6 2.685 6 6-2.685 6-6 6zm7 3v-3h2v3h3v2h-3v3h-2v-3h-3v-2h3z",
    shield: "M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z",
    hardDel: "M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z",
    kanban: "M3 3h5v18H3zm6.5 0H15v8H9.5zm0 10H15v8H9.5zM17 3h4v11h-4zm0 13h4v5h-4z",
};

// ─── Pagination ───────────────────────────────────────────
function Pagination({ page, totalPages, onPage }) {
    if (totalPages <= 1) return null;
    return (
        <div className="pagination">
            <button className="btn btn-ghost btn-sm" onClick={() => onPage(page - 1)} disabled={page <= 1}>
                <Icon d={ICONS.chevronL} />
            </button>
            <span className="page-info">{page} / {totalPages}</span>
            <button className="btn btn-ghost btn-sm" onClick={() => onPage(page + 1)} disabled={page >= totalPages}>
                <Icon d={ICONS.chevronR} />
            </button>
        </div>
    );
}

// ─── Comments panel ───────────────────────────────────────
// ─── AuditPanel ──────────────────────────────────────────
const AUDIT_ACTION_ICONS = { create: "✅", update: "✏️", delete: "🗑", restore: "♻️" };
const AUDIT_ACTION_LABELS = { create: "Создана", update: "Изменена", delete: "Удалена", restore: "Восстановлена" };
const AUDIT_FIELD_LABELS = {
    title: "Заголовок", description: "Описание", is_done: "Статус",
    deadline: "Дедлайн", user_id: "Исполнитель", group_id: "Группа",
    priority: "Приоритет", project_id: "Проект", deleted_at: "Удалена",
};

function AuditPanel({ taskId, token }) {
    const [entries, setEntries] = useState([]);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        setLoading(true);
        apiRequest({ path: `/tasks/${taskId}/audit`, token })
            .then(data => setEntries(Array.isArray(data) ? data : []))
            .catch(() => setEntries([]))
            .finally(() => setLoading(false));
    }, [taskId, token]);

    return (
        <div className="comments-panel">
            <div className="comments-title">
                📋 История изменений
                {entries.length > 0 && <span className="count-badge">{entries.length}</span>}
            </div>
            {loading ? (
                <div className="comments-empty">Загрузка…</div>
            ) : entries.length === 0 ? (
                <div className="comments-empty">История пуста</div>
            ) : (
                <div className="comment-list">
                    {entries.map(e => (
                        <div key={e.id} className="comment-item">
                            <div className="comment-meta">
                                <span className="comment-author">
                                    {AUDIT_ACTION_ICONS[e.action] || "📝"} {AUDIT_ACTION_LABELS[e.action] || e.action}
                                    {e.user?.username && <span style={{ marginLeft: 6, color: "var(--text-muted)" }}>· {e.user.username}</span>}
                                </span>
                                <span className="comment-date">{e.changed_at}</span>
                            </div>
                            {e.action === "update" && e.new_values && (
                                <div style={{ marginTop: 4, display: "flex", flexDirection: "column", gap: 2 }}>
                                    {Object.entries(e.new_values).map(([field, newVal]) => (
                                        <div key={field} style={{ fontSize: 12, color: "var(--text-muted)" }}>
                                            <span style={{ color: "var(--text-dim)" }}>
                                                {AUDIT_FIELD_LABELS[field] || field}:
                                            </span>{" "}
                                            {e.old_values?.[field] !== undefined && (
                                                <span style={{ textDecoration: "line-through", marginRight: 4 }}>
                                                    {String(e.old_values[field] ?? "—")}
                                                </span>
                                            )}
                                            <span style={{ color: "var(--accent-light)" }}>
                                                {String(newVal ?? "—")}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}


function CommentsPanel({ taskId, token }) {
    const [comments, setComments] = useState([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [text, setText] = useState("");
    const [loading, setLoading] = useState(false);
    const [sending, setSending] = useState(false);
    const PAGE_SIZE = 5;

    const inflightRef = React.useRef(false);
    const load = useCallback(async (p = 1) => {
        if (p === 1 && inflightRef.current) return; // защита от двойного вызова
        inflightRef.current = true;
        setLoading(true);
        try {
            const data = await apiRequest({
                path: `/comments/tasks/${taskId}/comments?page=${p}&size=${PAGE_SIZE}`, token,
            });
            setComments(extractItems(data));
            setTotal(data?.total ?? 0);
            setPage(p);
        } catch { /* ignore */ }
        finally { setLoading(false); inflightRef.current = false; }
    }, [taskId, token]);

    useEffect(() => { load(1); }, [load]);

    async function handleSend() {
        if (!text.trim()) return;
        setSending(true);
        try {
            await apiRequest({ path: `/comments/tasks/${taskId}/comment`, method: "POST", token, body: { content: text.trim() } });
            setText("");
            await load(1);
        } catch { /* ignore */ }
        finally { setSending(false); }
    }

    return (
        <div className="comments-panel">
            <div className="comments-title">
                <Icon d={ICONS.comment} /> Комментарии
                {total > 0 && <span className="count-badge">{total}</span>}
            </div>
            {loading ? (
                <div className="comments-empty">Загрузка…</div>
            ) : comments.length === 0 ? (
                <div className="comments-empty">Комментариев нет</div>
            ) : (
                <>
                    <div className="comment-list">
                        {comments.map(c => (
                            <div key={c.id} className="comment-item">
                                <div className="comment-meta">
                                    <span className="comment-author">{c.user?.username ?? "—"}</span>
                                    <span className="comment-date">
                                        {c.created_at ? new Date(c.created_at).toLocaleString("ru-RU", {
                                            day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
                                        }) : ""}
                                    </span>
                                </div>
                                <div className="comment-text">{c.content}</div>
                            </div>
                        ))}
                    </div>
                    <Pagination page={page} totalPages={Math.ceil(total / PAGE_SIZE)} onPage={load} />
                </>
            )}
            <div className="comment-form">
                <textarea value={text} onChange={e => setText(e.target.value)}
                    placeholder="Написать комментарий… (Ctrl+Enter)" rows={2}
                    onKeyDown={e => { if (e.key === "Enter" && e.ctrlKey) handleSend(); }} />
                <button className="btn btn-primary btn-sm" onClick={handleSend} disabled={sending || !text.trim()}>
                    <Icon d={ICONS.plus} /> {sending ? "…" : "Отправить"}
                </button>
            </div>
        </div>
    );
}


// ─── ChecklistPanel ────────────────────────────────────────
function ChecklistPanel({ taskId, token }) {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(false);
    const [newTitle, setNewTitle] = useState("");
    const [adding, setAdding] = useState(false);

    const loadingRef = React.useRef(false);
    const load = useCallback(async () => {
        if (loadingRef.current) return;
        loadingRef.current = true;
        setLoading(true);
        try {
            const data = await apiRequest({ path: `/tasks/${taskId}/checklist`, token });
            setItems(Array.isArray(data) ? data : []);
        } catch { /* ignore */ }
        finally { setLoading(false); loadingRef.current = false; }
    }, [taskId, token]);

    useEffect(() => { load(); }, [load]);

    async function handleAdd() {
        if (!newTitle.trim()) return;
        setAdding(true);
        try {
            await apiRequest({
                path: `/tasks/${taskId}/checklist`, method: "POST", token,
                body: { title: newTitle.trim() },
            });
            setNewTitle("");
            await load();
        } catch { /* ignore */ }
        finally { setAdding(false); }
    }

    async function handleToggleDone(item) {
        // Оптимистичное обновление — не ждём ответа сервера, чтобы галочка отзывалась мгновенно
        setItems(prev => prev.map(i => i.id === item.id ? { ...i, is_done: !i.is_done } : i));
        try {
            await apiRequest({
                path: `/tasks/${taskId}/checklist/${item.id}`, method: "PATCH", token,
                body: { is_done: !item.is_done },
            });
        } catch {
            setItems(prev => prev.map(i => i.id === item.id ? item : i)); // откат при ошибке
        }
    }

    async function handleDelete(item) {
        setItems(prev => prev.filter(i => i.id !== item.id));
        try {
            await apiRequest({ path: `/tasks/${taskId}/checklist/${item.id}`, method: "DELETE", token });
        } catch {
            await load(); // откат — проще перезагрузить, чем восстанавливать позицию в списке
        }
    }

    async function handleMove(item, direction) {
        const idx = items.findIndex(i => i.id === item.id);
        const swapIdx = idx + direction;
        if (swapIdx < 0 || swapIdx >= items.length) return;

        const reordered = [...items];
        [reordered[idx], reordered[swapIdx]] = [reordered[swapIdx], reordered[idx]];
        setItems(reordered);

        try {
            await apiRequest({
                path: `/tasks/${taskId}/checklist/reorder`, method: "PATCH", token,
                body: { items: reordered.map((i, idx2) => ({ id: i.id, order_index: idx2 })) },
            });
        } catch {
            await load();
        }
    }

    const doneCount = items.filter(i => i.is_done).length;

    return (
        <div className="comments-panel">
            <div className="comments-title">
                ☑️ Чек-лист
                {items.length > 0 && <span className="count-badge">{doneCount}/{items.length}</span>}
            </div>
            {loading ? (
                <div className="comments-empty">Загрузка…</div>
            ) : items.length === 0 ? (
                <div className="comments-empty">Пунктов пока нет</div>
            ) : (
                <div className="comment-list">
                    {items.map((item, idx) => (
                        <div key={item.id} className="comment-item" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <input
                                type="checkbox"
                                checked={item.is_done}
                                onChange={() => handleToggleDone(item)}
                                style={{ flexShrink: 0, width: 16, height: 16, cursor: "pointer" }}
                            />
                            <span style={{
                                flex: 1,
                                textDecoration: item.is_done ? "line-through" : "none",
                                color: item.is_done ? "var(--text-muted)" : "var(--text)",
                            }}>
                                {item.title}
                            </span>
                            <button className="btn btn-ghost btn-sm" style={{ padding: "2px 6px" }}
                                disabled={idx === 0} onClick={() => handleMove(item, -1)}>▲</button>
                            <button className="btn btn-ghost btn-sm" style={{ padding: "2px 6px" }}
                                disabled={idx === items.length - 1} onClick={() => handleMove(item, 1)}>▼</button>
                            <button className="btn btn-danger btn-sm" style={{ padding: "2px 6px" }}
                                onClick={() => handleDelete(item)}>
                                <Icon d={ICONS.trash} />
                            </button>
                        </div>
                    ))}
                </div>
            )}
            <div className="comment-form">
                <input
                    value={newTitle}
                    onChange={e => setNewTitle(e.target.value)}
                    placeholder="Новый пункт… (Enter)"
                    onKeyDown={e => { if (e.key === "Enter") handleAdd(); }}
                />
                <button className="btn btn-primary btn-sm" onClick={handleAdd} disabled={adding || !newTitle.trim()}>
                    <Icon d={ICONS.plus} /> {adding ? "…" : "Добавить"}
                </button>
            </div>
        </div>
    );
}


// ─── TagsPanel ─────────────────────────────────────────────
function TagsPanel({ task, allTags, token, onTagsCreated, onSaved }) {
    const [selectedIds, setSelectedIds] = useState(new Set((task.tags || []).map(t => t.id)));
    const [saving, setSaving] = useState(false);
    const [newTagName, setNewTagName] = useState("");
    const [creating, setCreating] = useState(false);
    const [error, setError] = useState(null);

    function toggle(tagId) {
        setSelectedIds(prev => {
            const next = new Set(prev);
            if (next.has(tagId)) next.delete(tagId); else next.add(tagId);
            return next;
        });
    }

    async function handleSave() {
        setSaving(true);
        setError(null);
        try {
            const updated = await apiRequest({
                path: `/tags/tasks/${task.id}`, method: "PUT", token,
                body: { tag_ids: Array.from(selectedIds) },
            });
            onSaved?.(updated.tags || []);
        } catch (err) {
            setError(err.message);
        } finally {
            setSaving(false);
        }
    }

    async function handleCreateTag() {
        if (!newTagName.trim()) return;
        setCreating(true);
        setError(null);
        try {
            const tag = await apiRequest({
                path: "/tags", method: "POST", token,
                body: { name: newTagName.trim() },
            });
            setNewTagName("");
            await onTagsCreated?.();
            setSelectedIds(prev => new Set(prev).add(tag.id));
        } catch (err) {
            setError(err.message);
        } finally {
            setCreating(false);
        }
    }

    return (
        <div className="comments-panel">
            <div className="comments-title">🏷️ Теги</div>
            {allTags.length === 0 ? (
                <div className="comments-empty">В команде пока нет ни одного тега — создайте первый ниже</div>
            ) : (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
                    {allTags.map(tag => {
                        const isSelected = selectedIds.has(tag.id);
                        return (
                            <button
                                key={tag.id}
                                type="button"
                                onClick={() => toggle(tag.id)}
                                style={{
                                    padding: "5px 12px",
                                    borderRadius: 14,
                                    fontSize: 12,
                                    fontWeight: 600,
                                    cursor: "pointer",
                                    border: `1px solid ${isSelected ? tag.color : "var(--border)"}`,
                                    background: isSelected ? tag.color + "22" : "transparent",
                                    color: isSelected ? tag.color : "var(--text-muted)",
                                }}
                            >
                                {isSelected ? "✓ " : ""}{tag.name}
                            </button>
                        );
                    })}
                </div>
            )}
            {error && <div className="alert" style={{ marginBottom: 8 }}>{error}</div>}
            <div className="comment-form" style={{ marginBottom: 12 }}>
                <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving}>
                    <Icon d={ICONS.save} /> {saving ? "Сохранение…" : "Сохранить теги"}
                </button>
            </div>
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
                <div className="comment-form">
                    <input
                        value={newTagName}
                        onChange={e => setNewTagName(e.target.value)}
                        placeholder="Новый тег (например, клиент-X)…"
                        onKeyDown={e => { if (e.key === "Enter") handleCreateTag(); }}
                    />
                    <button className="btn btn-ghost btn-sm" onClick={handleCreateTag} disabled={creating || !newTagName.trim()}>
                        <Icon d={ICONS.plus} /> {creating ? "…" : "Создать тег"}
                    </button>
                </div>
            </div>
        </div>
    );
}


// ─── Priority config ──────────────────────────────────────
const PRIORITY_COLORS = { critical: "#ef4444", high: "#f97316", medium: "#3b82f6", low: "#6b7280" };
const PRIORITY_LABELS = { critical: "Критический", high: "Высокий", medium: "Средний", low: "Низкий" };
const PRIORITY_ICONS = { critical: "🔴", high: "🟠", medium: "🔵", low: "⚪" };

// ─── Статусы задач (общий список для карточек, канбана и выпадающего меню) ───
const STATUS_LIST = [
    { key: "backlog", label: "Очередь", icon: "📥", color: "#6b7280" },
    { key: "todo", label: "Новые", icon: "🆕", color: "#7c6af0" },
    { key: "in_progress", label: "В работе", icon: "🚧", color: "#f59e0b" },
    { key: "review", label: "На проверке", icon: "🔎", color: "#3b82f6" },
    { key: "done", label: "Готово", icon: "✅", color: "#22c55e" },
];
const STATUS_META = Object.fromEntries(STATUS_LIST.map(s => [s.key, s]));

// Выпадающее меню выбора статуса — заменяет кнопки "Вперёд"/"Назад"
function StatusMenu({ status, onChange, disabled }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const current = STATUS_META[status] ?? STATUS_LIST[1];

    useEffect(() => {
        if (!open) return;
        function handleClickOutside(e) {
            if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        }
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, [open]);

    return (
        <div ref={ref} style={{ position: "relative", display: "inline-block" }}>
            <button
                type="button"
                className="btn btn-sm"
                disabled={disabled}
                onClick={() => setOpen(v => !v)}
                style={{
                    background: current.color + "22",
                    color: current.color,
                    border: `1px solid ${current.color}55`,
                    fontWeight: 600,
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                }}
            >
                <span style={{
                    display: "inline-block", width: 8, height: 8,
                    borderRadius: "50%", background: current.color, flexShrink: 0,
                }} />
                {current.icon} {current.label}
                <span style={{ fontSize: 10, opacity: 0.8 }}>▾</span>
            </button>

            {open && (
                <div style={{
                    position: "absolute",
                    top: "calc(100% + 4px)",
                    left: 0,
                    zIndex: 30,
                    minWidth: 170,
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)",
                    boxShadow: "var(--shadow-sm)",
                    overflow: "hidden",
                }}>
                    {STATUS_LIST.map(s => (
                        <div
                            key={s.key}
                            onClick={() => { if (s.key !== status) onChange(s.key); setOpen(false); }}
                            style={{
                                padding: "9px 12px",
                                fontSize: 13,
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                                cursor: "pointer",
                                color: "var(--text)",
                                background: s.key === status ? "var(--surface2)" : "transparent",
                            }}
                            onMouseEnter={e => { e.currentTarget.style.background = "var(--surface2)"; }}
                            onMouseLeave={e => { e.currentTarget.style.background = s.key === status ? "var(--surface2)" : "transparent"; }}
                        >
                            <span style={{
                                display: "inline-block", width: 8, height: 8,
                                borderRadius: "50%", background: s.color, flexShrink: 0,
                            }} />
                            {s.icon} {s.label}
                            {s.key === status && <span style={{ marginLeft: "auto", color: "var(--accent)" }}>✓</span>}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

// ─── TaskCard ─────────────────────────────────────────────
function TaskCard({ task, groups, users, token, allTags, onTagsCreated, onTagsUpdated, onToggle, onDelete, onUpdate, onReassign, hideReassign, collapsible, currentUserId, currentRole, selected, onToggleSelect }) {
    const [expanded, setExpanded] = useState(!collapsible);
    const [editing, setEditing] = useState(false);
    const [showComments, setShowComments] = useState(false);
    const [showAudit, setShowAudit] = useState(false);
    const [showAttachments, setShowAttachments] = useState(false);
    const [showReassign, setShowReassign] = useState(false);
    const [showChecklist, setShowChecklist] = useState(false);
    const [showTags, setShowTags] = useState(false);
    const [saving, setSaving] = useState(false);
    const formatForInput = (value) => {
        if (!value) return "";

        // если уже ISO
        if (value.includes("T")) {
            return value.slice(0, 16);
        }

        // если формат "14.06.2026 22:15"
        const [date, time] = value.split(" ");
        if (!date || !time) return "";

        const [day, month, year] = date.split(".");
        return `${year}-${month}-${day}T${time.slice(0, 5)}`;
    };
    const [editForm, setEditForm] = useState({
        title: task.title, description: task.description || "",
        deadline: formatForInput(task.deadline),
        priority: task.priority || "medium",
        recurrence_rule: task.recurrence_rule || "none",
    });
    const [reassignUserId, setReassignUserId] = useState("");
    const [reassignGroupId, setReassignGroupId] = useState("");
    const dl = formatDeadline(task.deadline);

    async function handleSave() {
        setSaving(true);
        await onUpdate(task, {
            title: editForm.title.trim(),
            description: editForm.description.trim() || null,
            deadline: editForm.deadline
                ? new Date(editForm.deadline).toISOString()
                : null,
            priority: editForm.priority,
            recurrence_rule: editForm.recurrence_rule,
        });
        setSaving(false); setEditing(false);
    }

    async function handleReassign() {
        await onReassign(task.id, reassignUserId || null, reassignGroupId || null);
        setShowReassign(false); setReassignUserId(""); setReassignGroupId("");
    }

    // Компактная строка для свёрнутого режима
    if (collapsible && !expanded) {
        return (
            <div
                onClick={() => setExpanded(true)}
                style={{
                    display: "flex", alignItems: "center", gap: 10,
                    padding: "10px 14px", borderRadius: 8, cursor: "pointer",
                    background: "var(--surface)", border: "1px solid var(--border)",
                    transition: "border-color 0.15s",
                }}
                onMouseEnter={e => e.currentTarget.style.borderColor = "var(--accent)"}
                onMouseLeave={e => e.currentTarget.style.borderColor = "var(--border)"}
            >
                <span style={{ fontSize: 15 }}>{task.is_done ? "✅" : "⏳"}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                        fontSize: 14, fontWeight: 500,
                        color: task.is_done ? "var(--text-muted)" : "var(--text)",
                        textDecoration: task.is_done ? "line-through" : "none",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                        <span className="task-id">#{task.id}</span> {task.title}
                    </div>
                    {dl && (
                        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                            📅 {dl.fmt}
                        </div>
                    )}
                </div>
                {task.user?.username && (
                    <span className="meta-chip task-row-user" style={{
                        fontSize: 11,
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        flexShrink: 0,
                    }}>{task.user.username}</span>
                )}
                {task.priority && (
                    <span style={{
                        fontSize: 11, padding: "2px 7px", borderRadius: 4,
                        background: PRIORITY_COLORS[task.priority] + "22",
                        color: PRIORITY_COLORS[task.priority], fontWeight: 600,
                        whiteSpace: "nowrap", flexShrink: 0,
                    }}>
                        {PRIORITY_ICONS[task.priority]}
                    </span>
                )}
                <span style={{ fontSize: 11, color: "var(--text-muted)", flexShrink: 0 }}>▼</span>
            </div>
        );
    }

    return (
        <article className={`task-card${task.is_done ? " done-card" : ""}`}>
            <div className="task-main-info"> {/* НОВЫЙ ИЗОЛИРУЮЩИЙ КОНТЕЙНЕР ДЛЯ ВЕРХНЕЙ ЧАСТИ */}
                <div className="task-top">
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="task-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            {onToggleSelect && (
                                <input
                                    type="checkbox"
                                    checked={!!selected}
                                    onChange={() => onToggleSelect(task.id)}
                                    onClick={e => e.stopPropagation()}
                                    style={{
                                        width: 16, height: 16, minWidth: 16, minHeight: 16,
                                        flexShrink: 0, margin: 0, padding: 0,
                                        border: "1px solid var(--border)", borderRadius: 4,
                                        cursor: "pointer", accentColor: "var(--accent)",
                                    }}
                                />
                            )}
                            <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                                <span className="task-id">#{task.id}</span>
                                {task.title}
                            </span>
                        </div>
                        {task.description && <div className="task-desc">{task.description}</div>}
                        <div className="task-meta-row">
                            {dl && (
                                <span className={`meta-chip${dl.isOverdue && !task.is_done ? " overdue" : dl.isToday && !task.is_done ? " today" : ""}`}>
                                    <Icon d={ICONS.clock} />
                                    {dl.isOverdue && !task.is_done ? "Просрочено: " : dl.isToday && !task.is_done ? "Сегодня: " : ""}
                                    {dl.fmt}
                                </span>
                            )}
                            {task.author?.username && (
                                <span className="meta-chip"><Icon d={ICONS.user} /> {task.author.username}</span>
                            )}
                            {task.user?.username && task.user.username !== task.author?.username && (
                                <span className="meta-chip"><Icon d={ICONS.user} /> → {task.user.username}</span>
                            )}
                            {task.group?.name && (
                                <span className="meta-chip"><Icon d={ICONS.group} /> {task.group.name}</span>
                            )}
                            {task.comments_count > 0 && (
                                <span className="meta-chip"><Icon d={ICONS.comment} /> {task.comments_count}</span>
                            )}
                            {task.recurrence_rule && task.recurrence_rule !== "none" && (
                                <span className="meta-chip" title="Повторяющаяся задача">
                                    🔁 {{ daily: "Ежедневно", weekly: "Еженедельно", monthly: "Ежемесячно" }[task.recurrence_rule]}
                                </span>
                            )}
                            {task.checklist_items?.length > 0 && (
                                <span className="meta-chip">
                                    ☑️ {task.checklist_items.filter(i => i.is_done).length}/{task.checklist_items.length}
                                </span>
                            )}
                            {(task.tags || []).map(tag => (
                                <span key={tag.id} className="meta-chip" style={{
                                    background: tag.color + "22", color: tag.color, borderColor: tag.color + "55",
                                }}>
                                    {tag.name}
                                </span>
                            ))}
                        </div>
                    </div>
                    <span className={`badge ${task.status === "done" ? "badge-done" : "badge-active"}`}>
                        {{ "backlog": "Очередь", "todo": "Новые", "in_progress": "В работе", "review": "На проверке", "done": "Готово" }[task.status]}
                    </span>
                    {task.priority && (
                        <span style={{
                            fontSize: 11, padding: "2px 7px", borderRadius: 4,
                            background: PRIORITY_COLORS[task.priority] + "22",
                            color: PRIORITY_COLORS[task.priority], fontWeight: 600, whiteSpace: "nowrap"
                        }}>
                            {PRIORITY_ICONS[task.priority]} {PRIORITY_LABELS[task.priority]}
                        </span>
                    )}
                    {collapsible && (
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => { setExpanded(false); setEditing(false); setShowComments(false); setShowReassign(false); }}
                            style={{ fontSize: 11, padding: "2px 8px", left: 5, position: "relative" }}
                        >
                            свернуть ▲
                        </button>
                    )}
                </div>
            </div> {/* КОНЕЦ НОВОГО КОНТЕЙНЕРА */}
            {editing && (
                <div className="edit-form">
                    <div className="form-group">
                        <label className="form-label">Заголовок</label>
                        <input value={editForm.title}
                            onChange={e => setEditForm({ ...editForm, title: e.target.value })} />
                    </div>
                    <div className="form-group">
                        <label className="form-label">Описание</label>
                        <textarea value={editForm.description} style={{ minHeight: 64 }}
                            onChange={e => setEditForm({ ...editForm, description: e.target.value })} />
                    </div>
                    <div className="form-group">
                        <label className="form-label">Дедлайн</label>
                        <input type="datetime-local" value={editForm.deadline}
                            onChange={e => setEditForm({ ...editForm, deadline: e.target.value })} />
                    </div>

                    <div className="form-group">
                        <label className="form-label">Приоритет</label>
                        <select value={editForm.priority}
                            onChange={e => setEditForm(f => ({ ...f, priority: e.target.value }))}>
                            <option value="low">⚪ Низкий</option>
                            <option value="medium">🔵 Средний</option>
                            <option value="high">🟠 Высокий</option>
                            <option value="critical">🔴 Критический</option>
                        </select>
                    </div>

                    <div className="form-group">
                        <label className="form-label">Повторение</label>
                        <select value={editForm.recurrence_rule}
                            onChange={e => setEditForm(f => ({ ...f, recurrence_rule: e.target.value }))}>
                            <option value="none">Не повторяется</option>
                            <option value="daily">🔁 Каждый день</option>
                            <option value="weekly">🔁 Каждую неделю</option>
                            <option value="monthly">🔁 Каждый месяц</option>
                        </select>
                    </div>

                    <div className="edit-actions">
                        <button className="btn btn-primary btn-sm" onClick={handleSave}
                            disabled={saving || !editForm.title.trim()}>
                            <Icon d={ICONS.save} /> {saving ? "Сохранение…" : "Сохранить"}
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>
                            <Icon d={ICONS.x} /> Отмена
                        </button>
                    </div>
                </div>
            )}

            {showReassign && (
                <div className="edit-form">
                    <div className="edit-form-row">
                        <div className="form-group">
                            <label className="form-label">Пользователь</label>
                            <select value={reassignUserId} onChange={e => setReassignUserId(e.target.value)}>
                                <option value="">— не менять —</option>
                                {users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                            </select>
                        </div>
                        <div className="form-group">
                            <label className="form-label">Группа</label>
                            <select value={reassignGroupId} onChange={e => setReassignGroupId(e.target.value)}>
                                <option value="">— не менять —</option>
                                {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                            </select>
                        </div>
                    </div>
                    <div className="edit-actions">
                        <button className="btn btn-primary btn-sm" onClick={handleReassign}>
                            <Icon d={ICONS.reassign} /> Переназначить
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={() => setShowReassign(false)}>
                            <Icon d={ICONS.x} /> Отмена
                        </button>
                    </div>
                </div>
            )}

            <div className="task-actions">
                <StatusMenu
                    status={task.status || (task.is_done ? "done" : "todo")}
                    onChange={(newStatus) => onToggle(task, newStatus)}
                />
                {!editing && (
                    <button className="btn btn-ghost btn-sm" onClick={() => { setEditing(true); setShowReassign(false); }}>
                        <Icon d={ICONS.edit} /> Изменить
                    </button>
                )}
                {!hideReassign && (
                    <button className="btn btn-ghost btn-sm" onClick={() => { setShowReassign(v => !v); setEditing(false); }}>
                        <Icon d={ICONS.reassign} /> Переназначить
                    </button>
                )}
                <button className="btn btn-ghost btn-sm" onClick={() => { setShowComments(v => !v); setShowAudit(false); }}>
                    <Icon d={ICONS.comment} /> {showComments ? "Скрыть" : "Комментарии"}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => setShowAttachments(v => !v)}>
                    📎 {showAttachments ? "Скрыть" : "Вложения"}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => setShowChecklist(v => !v)}>
                    ☑️ {showChecklist ? "Скрыть" : "Чек-лист"}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => setShowTags(v => !v)}>
                    🏷️ {showTags ? "Скрыть" : "Теги"}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => { setShowAudit(v => !v); setShowComments(false); }}>
                    📋 {showAudit ? "Скрыть" : "История"}
                </button>
                <button className="btn btn-danger btn-sm" onClick={() => onDelete(task)}>
                    <Icon d={ICONS.trash} /> Удалить
                </button>
            </div>

            {showComments && <CommentsPanel taskId={task.id} token={token} />}
            {showAttachments && (
                <AttachmentsPanel
                    taskId={task.id}
                    token={token}
                    currentUserId={currentUserId}
                    canDelete={currentRole === "admin" || currentRole === "manager"}
                />
            )}
            {showChecklist && <ChecklistPanel taskId={task.id} token={token} />}
            {showTags && (
                <TagsPanel
                    task={task}
                    allTags={allTags}
                    token={token}
                    onTagsCreated={onTagsCreated}
                    onSaved={(updatedTags) => onTagsUpdated?.(task.id, updatedTags)}
                />
            )}
            {showAudit && <AuditPanel taskId={task.id} token={token} />}
        </article>
    );
}

// ─── TrashCard ────────────────────────────────────────────
function TrashCard({ task, onRestore, onHardDelete }) {
    const dl = formatDeadline(task.deadline);

    return (
        <article className="task-card done-card">
            <div className="task-main-info">
                <div className="task-top">
                    {/* Единообразие с TaskCard: внутренний div с flex:1 */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="task-title">
                            <span className="task-id">#{task.id}</span>
                            {task.title}
                        </div>
                        {task.description && <div className="task-desc">{task.description}</div>}
                        <div className="task-meta-row">
                            {dl && (
                                <span className="meta-chip">
                                    <Icon d={ICONS.clock} />
                                    {dl.fmt}
                                </span>
                            )}
                            {task.author?.username && (
                                <span className="meta-chip">
                                    <Icon d={ICONS.user} /> {task.author.username}
                                </span>
                            )}
                            {task.group?.name && (
                                <span className="meta-chip">
                                    <Icon d={ICONS.group} /> {task.group.name}
                                </span>
                            )}
                        </div>
                    </div>
                    <span className="badge badge-done">Удалена</span>
                </div>
            </div>
            <div className="task-actions">
                <button className="btn btn-success btn-sm" onClick={() => onRestore(task)}>
                    <Icon d={ICONS.check} /> Восстановить
                </button>
                <button className="btn btn-danger btn-sm" onClick={() => onHardDelete(task)}>
                    <Icon d={ICONS.trash} /> Удалить навсегда
                </button>
            </div>
        </article>
    );
}

// ─── GroupPanel ───────────────────────────────────────────
function GroupPanel({ group, allUsers, token, canManage, onRefresh }) {
    const [members, setMembers] = useState([]);
    const [loading, setLoading] = useState(false);
    const [addUserId, setAddUserId] = useState("");
    const [adding, setAdding] = useState(false);
    const [expanded, setExpanded] = useState(false);
    const [error, setError] = useState(null);

    const loadingRef = React.useRef(false);
    const load = useCallback(async () => {
        if (loadingRef.current) return;
        loadingRef.current = true;
        setLoading(true);
        try {
            const data = await apiRequest({
                path: `/groups/${group.id}/users?page=1&size=100`, token,
            });
            setMembers(extractItems(data));
        } catch { setMembers([]); }
        finally { setLoading(false); loadingRef.current = false; }
    }, [group.id, token]);

    useEffect(() => { if (expanded) load(); }, [expanded, load]);

    async function handleAdd() {
        if (!addUserId) return;
        const newUser = allUsers.find(u => u.id === Number(addUserId));
        if (!newUser) return;
        setMembers(prev => [...prev, newUser]);
        setAddUserId("");
        setAdding(true); setError(null);
        try {
            await apiRequest({
                path: `/groups/${group.id}/users/${addUserId}`,
                method: "POST", token,
            });
        } catch (err) {
            setMembers(prev => prev.filter(m => m.id !== newUser.id));
            setAddUserId(String(newUser.id));
            setError(err.message);
        }
        finally { setAdding(false); }
    }

    async function handleRemove(userId) {
        const removed = members.find(m => m.id === userId);
        setMembers(prev => prev.filter(m => m.id !== userId));
        setError(null);
        try {
            await apiRequest({
                path: `/groups/${group.id}/users/${userId}`,
                method: "DELETE", token,
            });
        } catch (err) {
            setMembers(prev => [...prev, removed]);
            setError(err.message);
        }
    }

    // пользователи не в группе — для селекта добавления
    const memberIds = new Set(members.map(m => m.id));
    const notInGroup = allUsers.filter(u => !memberIds.has(u.id));

    return (
        <div className="group-card">
            <div className="group-card-header" onClick={() => setExpanded(v => !v)}>
                <div className="group-card-title">
                    <Icon d={ICONS.group} size={16} />
                    <span>{group.name}</span>
                    {members.length > 0 && !loading && (
                        <span className="count-badge">{members.length}</span>
                    )}
                </div>
                <Icon d={expanded ? ICONS.chevronL : ICONS.chevronR} size={14} />
            </div>

            {expanded && (
                <div className="group-card-body">
                    {error && <div className="alert" style={{ marginBottom: 10 }}>{error}</div>}

                    {/* Member list */}
                    {loading ? (
                        <div className="comments-empty">Загрузка…</div>
                    ) : members.length === 0 ? (
                        <div className="comments-empty">В группе нет участников</div>
                    ) : (
                        <div className="member-list">
                            {members.map(m => {
                                const rc = ROLE_COLORS[m.role] ?? ROLE_COLORS.user;
                                return (
                                    <div key={m.id} className="member-row">
                                        <div className="member-info">
                                            <div className="member-avatar">
                                                {m.username.charAt(0).toUpperCase()}
                                            </div>
                                            <div>
                                                <div className="member-name">
                                                    {m.username}
                                                    {!m.is_active && (
                                                        <span className="inactive-badge">неакт.</span>
                                                    )}
                                                </div>
                                                <div className="member-role-row">
                                                    <span className="role-badge"
                                                        style={{ color: rc.color, background: rc.bg }}>
                                                        {ROLE_LABELS[m.role] ?? m.role}
                                                    </span>
                                                    {m.telegram_id && (
                                                        <span className="meta-chip" style={{ fontSize: "0.72rem" }}>
                                                            TG: {m.telegram_id}
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                        {canManage && (
                                            <button className="btn btn-danger btn-sm"
                                                onClick={() => handleRemove(m.id)}
                                                title="Удалить из группы">
                                                <Icon d={ICONS.userMinus} />
                                            </button>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    )}

                    {/* Add member — только для manager/admin */}
                    {canManage && (
                        <div className="group-add-row">
                            <select value={addUserId} onChange={e => setAddUserId(e.target.value)}
                                style={{ flex: 1 }}>
                                <option value="">Добавить участника…</option>
                                {notInGroup.map(u => (
                                    <option key={u.id} value={u.id}>
                                        {u.username} ({ROLE_LABELS[u.role] ?? u.role})
                                    </option>
                                ))}
                            </select>
                            <button className="btn btn-primary btn-sm" onClick={handleAdd}
                                disabled={adding || !addUserId}>
                                <Icon d={ICONS.userPlus} /> {adding ? "…" : "Добавить"}
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}


// ─── KanbanTab ────────────────────────────────────────────
const KANBAN_COLUMNS = [
    { key: "backlog", label: "Очередь", color: "#6b7280" },
    { key: "todo", label: "Новые", color: "#7c6af0" },
    { key: "in_progress", label: "В работе", color: "#f59e0b" },
    { key: "review", label: "На проверке", color: "#3b82f6" },
    { key: "done", label: "Готово", color: "#22c55e" },
];

function KanbanTab({ token }) {
    const [board, setBoard] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [projectId, setProjectId] = useState("");
    const [onlyMine, setOnlyMine] = useState(false);
    const [onlyAuthor, setOnlyAuthor] = useState(false);
    const [projects, setProjects] = useState([]);
    const [dragging, setDragging] = useState(null); // { taskId, fromCol }
    const [dragOver, setDragOver] = useState(null);
    const [movingId, setMovingId] = useState(null);

    // const API = (path) => `/api${path}`;
    // const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

    const loadBoard = useCallback(async (pid, mine, author) => {
        setLoading(true);
        setError(null);
        try {
            const params = new URLSearchParams();
            if (pid) params.set("project_id", pid);
            if (mine) params.set("only_mine", "true");
            if (author) params.set("only_author", "true");
            const data = await apiRequest({ path: `/tasks/kanban?${params}`, token });
            setBoard(data);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => {
        if (!token) return;
        apiRequest({ path: "/projects?page=1&size=50", token })
            .then(data => setProjects(Array.isArray(data) ? data : (data.items ?? [])))
            .catch(() => { });
    }, [token]);

    useEffect(() => {
        if (!token) return;
        loadBoard(projectId, onlyMine, onlyAuthor);
    }, [projectId, onlyMine, onlyAuthor, loadBoard]);

    // ── Drag & Drop ──────────────────────────────────────────
    const onDragStart = (e, taskId, fromCol) => {
        setDragging({ taskId, fromCol });
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("taskId", taskId);
    };

    const onDragOver = (e, col) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        setDragOver(col);
    };

    // Перемещение задачи в другую колонку (используется и при drag&drop, и при выборе из списка статусов)
    const moveTask = async (taskId, fromCol, toCol) => {
        if (!fromCol || fromCol === toCol) return;

        // Оптимистичное обновление
        setBoard(prev => {
            const task = prev[fromCol]?.find(t => t.id === taskId);
            if (!task) return prev;
            return {
                ...prev,
                [fromCol]: prev[fromCol].filter(t => t.id !== taskId),
                [toCol]: [{ ...task, status: toCol }, ...prev[toCol]],
            };
        });

        setMovingId(taskId);
        try {
            await apiRequest({
                path: `/tasks/${taskId}/status`,
                method: "PATCH",
                token,
                body: { status: toCol },
            });
        } catch {
            // Откат при ошибке
            loadBoard(projectId, onlyMine, onlyAuthor);
        } finally {
            setMovingId(null);
        }
    };

    const onDrop = (e, toCol) => {
        e.preventDefault();
        setDragOver(null);
        if (!dragging) return;
        const { taskId, fromCol } = dragging;
        setDragging(null);
        moveTask(taskId, fromCol, toCol);
    };

    const onDragEnd = () => { setDragging(null); setDragOver(null); };

    // ── Render ───────────────────────────────────────────────
    if (loading) return (
        <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
            Загрузка канбан-доски…
        </div>
    );
    if (error) return (
        <div style={{ padding: 40, textAlign: "center", color: "var(--red)" }}>
            Ошибка: {error}
        </div>
    );

    const totalTasks = board ? Object.values(board).reduce((s, arr) => s + arr.length, 0) : 0;

    return (
        <div style={{ padding: "16px 16px 32px" }}>
            {/* Фильтры */}
            <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
                <select
                    className="form-control"
                    style={{ minWidth: 180, maxWidth: 260 }}
                    value={projectId}
                    onChange={e => setProjectId(e.target.value)}
                >
                    <option value="">Все задачи</option>
                    {projects.map(p => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                </select>
                <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", color: "var(--text-dim)", fontSize: 13 }}>
                    <input
                        type="checkbox"
                        checked={onlyMine}
                        onChange={e => { setOnlyMine(e.target.checked); if (e.target.checked) setOnlyAuthor(false); }}
                        style={{ accentColor: "var(--accent)" }}
                    />
                    Только мои
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", color: "var(--text-dim)", fontSize: 13 }}>
                    <input
                        type="checkbox"
                        checked={onlyAuthor}
                        onChange={e => { setOnlyAuthor(e.target.checked); if (e.target.checked) setOnlyMine(false); }}
                        style={{ accentColor: "var(--accent)" }}
                    />
                    Я автор
                </label>
                <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => loadBoard(projectId, onlyMine)}
                    style={{ marginLeft: "auto" }}
                >
                    <Icon d={ICONS.refresh} /> Обновить
                </button>
                <span style={{ color: "var(--text-muted)", fontSize: 13 }}>
                    {totalTasks} задач
                </span>
            </div>

            {/* Доска */}
            <div style={{
                display: "flex",
                gap: 12,
                overflowX: "auto",
                overflowY: "hidden",
                height: "calc(100vh - 220px)",
                paddingBottom: 8,
                paddingRight: 16,
                alignItems: "flex-start",
            }}>
                {KANBAN_COLUMNS.map(col => {
                    const tasks = board?.[col.key] ?? [];
                    const isOver = dragOver === col.key;
                    return (
                        <div
                            key={col.key}
                            onDragOver={e => onDragOver(e, col.key)}
                            onDrop={e => onDrop(e, col.key)}
                            onDragLeave={() => setDragOver(null)}
                            style={{
                                minWidth: 260,
                                maxWidth: 300,
                                flexShrink: 0,
                                background: isOver
                                    ? "rgba(124,106,240,0.08)"
                                    : "var(--surface)",
                                border: `1.5px solid ${isOver ? "var(--accent)" : "var(--border)"}`,
                                borderRadius: "var(--radius)",
                                transition: "border-color 0.15s, background 0.15s",
                                // overflow: "hidden",
                                overflowY: "auto",
                                maxHeight: "100%",
                            }}
                        >
                            {/* Шапка колонки */}
                            <div style={{
                                padding: "12px 14px 10px",
                                borderBottom: "1px solid var(--border)",
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                            }}>
                                <span style={{
                                    display: "inline-block",
                                    width: 10, height: 10,
                                    borderRadius: "50%",
                                    background: col.color,
                                    flexShrink: 0,
                                }} />
                                <span style={{ fontFamily: "Syne, sans-serif", fontWeight: 700, fontSize: 13 }}>
                                    {col.label}
                                </span>
                                <span style={{
                                    marginLeft: "auto",
                                    background: "var(--surface2)",
                                    color: "var(--text-muted)",
                                    fontSize: 11,
                                    fontWeight: 600,
                                    borderRadius: 20,
                                    padding: "1px 8px",
                                }}>
                                    {tasks.length}
                                </span>
                            </div>

                            {/* Карточки */}
                            <div style={{ padding: "8px 8px", display: "flex", flexDirection: "column", gap: 7, minHeight: 60 }}>
                                {tasks.length === 0 ? (
                                    <div style={{
                                        textAlign: "center",
                                        color: "var(--text-muted)",
                                        fontSize: 12,
                                        padding: "24px 0",
                                        opacity: isOver ? 0.3 : 0.6,
                                    }}>
                                        {isOver ? "Отпустите сюда" : "Пусто"}
                                    </div>
                                ) : tasks.map(task => (
                                    <KanbanCard
                                        key={task.id}
                                        task={task}
                                        col={col.key}
                                        onDragStart={onDragStart}
                                        onDragEnd={onDragEnd}
                                        onChangeStatus={(newStatus) => moveTask(task.id, col.key, newStatus)}
                                        isMoving={movingId === task.id}
                                        isDragging={dragging?.taskId === task.id}
                                    />
                                ))}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

function KanbanCard({ task, col, onDragStart, onDragEnd, onChangeStatus, isMoving, isDragging }) {
    const priColor = PRIORITY_COLORS[task.priority] ?? "#3b82f6";
    const isOverdue = task.deadline && !task.is_done && new Date(task.deadline) < new Date();

    return (
        <div
            draggable
            onDragStart={e => onDragStart(e, task.id, col)}
            onDragEnd={onDragEnd}
            style={{
                background: "var(--surface2)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                padding: "10px 12px",
                cursor: isDragging ? "grabbing" : "grab",
                opacity: isDragging ? 0.4 : isMoving ? 0.7 : 1,
                transition: "opacity 0.15s, box-shadow 0.15s",
                boxShadow: isDragging ? "none" : "var(--shadow-sm)",
                userSelect: "none",
            }}
        >
            {/* Приоритет */}
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5 }}>
                <span style={{
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: "0.04em",
                    color: priColor,
                    background: priColor + "22",
                    borderRadius: 6,
                    padding: "1px 7px",
                    textTransform: "uppercase",
                }}>
                    {PRIORITY_LABELS[task.priority] ?? task.priority}
                </span>
                <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-muted)" }}>
                    #{task.id}
                </span>
            </div>

            {/* Заголовок */}
            <div style={{
                fontSize: 13,
                fontWeight: 600,
                color: "var(--text)",
                lineHeight: 1.4,
                marginBottom: 6,
                wordBreak: "break-word",
            }}>
                {task.title}
            </div>

            {/* Описание (обрезанное) */}
            {task.description && (
                <div style={{
                    fontSize: 11,
                    color: "var(--text-muted)",
                    lineHeight: 1.4,
                    marginBottom: 6,
                    overflow: "hidden",
                    display: "-webkit-box",
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: "vertical",
                }}>
                    {task.description}
                </div>
            )}

            {/* Дедлайн + исполнитель */}
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
                {task.deadline && (
                    <span style={{
                        fontSize: 11,
                        color: isOverdue ? "var(--red)" : "var(--text-muted)",
                        display: "flex",
                        alignItems: "center",
                        gap: 3,
                    }}>
                        <Icon d={ICONS.clock} size={11} />
                        {new Date(task.deadline).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}
                    </span>
                )}
                {task.user && (
                    <span style={{
                        marginLeft: "auto",
                        fontSize: 11,
                        color: "var(--text-dim)",
                        display: "flex",
                        alignItems: "center",
                        gap: 3,
                    }}>
                        <Icon d={ICONS.user} size={11} />
                        {task.user.username}
                    </span>
                )}
            </div>

            {/* Теги + чек-лист + повторение (компактно) */}
            {((task.tags?.length > 0) || (task.checklist_items?.length > 0) || (task.recurrence_rule && task.recurrence_rule !== "none")) && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                    {task.recurrence_rule && task.recurrence_rule !== "none" && (
                        <span style={{ fontSize: 10, color: "var(--text-muted)" }} title="Повторяющаяся задача">🔁</span>
                    )}
                    {task.checklist_items?.length > 0 && (
                        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
                            ☑️ {task.checklist_items.filter(i => i.is_done).length}/{task.checklist_items.length}
                        </span>
                    )}
                    {(task.tags || []).map(tag => (
                        <span key={tag.id} style={{
                            fontSize: 10, padding: "1px 6px", borderRadius: 8,
                            background: tag.color + "22", color: tag.color, fontWeight: 600,
                        }}>
                            {tag.name}
                        </span>
                    ))}
                </div>
            )}

            {/* Смена статуса без перетаскивания */}
            <div draggable={false} style={{ marginTop: 8 }} onMouseDown={e => e.stopPropagation()}>
                <StatusMenu status={task.status || col} onChange={onChangeStatus} disabled={isMoving} />
            </div>
        </div>
    );
}

// ─── TemplatesTab ──────────────────────────────────────────
function TemplatesTab({ token }) {
    const [view, setView] = useState("list");
    const [templates, setTemplates] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [saving, setSaving] = useState(false);
    const [editingTemplate, setEditingTemplate] = useState(null);
    const [form, setForm] = useState({ title: "", description: "" });
    const [items, setItems] = useState([]);
    const [applyTemplate, setApplyTemplate] = useState(null);
    const [projects, setProjects] = useState([]);
    const [applyProjectId, setApplyProjectId] = useState("");
    const [applying, setApplying] = useState(false);
    const [applySuccess, setApplySuccess] = useState(null);
    const dragIdx = useRef(null);

    async function loadTemplates() {
        setLoading(true); setError(null);
        try {
            const data = await apiRequest({ path: "/templates", token });
            setTemplates(Array.isArray(data) ? data : []);
        } catch (e) { setError(e.message); }
        finally { setLoading(false); }
    }

    async function loadProjects() {
        try {
            const data = await apiRequest({ path: "/projects?page=1&size=100", token });
            setProjects(extractItems(data));
        } catch { setProjects([]); }
    }

    useEffect(() => { loadTemplates(); loadProjects(); }, []); // eslint-disable-line

    function openCreate() {
        setEditingTemplate(null);
        setForm({ title: "", description: "" });
        setItems([]);
        setView("create");
    }

    function openEdit(tpl) {
        setEditingTemplate(tpl);
        setForm({ title: tpl.title, description: tpl.description || "" });
        setItems([...tpl.items].sort((a, b) => a.order_index - b.order_index)
            .map(it => ({ title: it.title, priority: it.priority, order_index: it.order_index })));
        setView("edit");
    }

    function addItem() {
        setItems(prev => [...prev, { title: "", priority: "medium", order_index: prev.length }]);
    }

    function removeItem(idx) {
        setItems(prev => prev.filter((_, i) => i !== idx).map((it, i) => ({ ...it, order_index: i })));
    }

    function updateItem(idx, field, value) {
        setItems(prev => prev.map((it, i) => i === idx ? { ...it, [field]: value } : it));
    }

    function onDragStart(idx) { dragIdx.current = idx; }
    function onDragOver(e, idx) {
        e.preventDefault();
        if (dragIdx.current === null || dragIdx.current === idx) return;
        const next = [...items];
        const [moved] = next.splice(dragIdx.current, 1);
        next.splice(idx, 0, moved);
        dragIdx.current = idx;
        setItems(next.map((it, i) => ({ ...it, order_index: i })));
    }
    function onDragEnd() { dragIdx.current = null; }

    async function handleSave() {
        if (!form.title.trim()) return;
        setSaving(true); setError(null);
        const body = {
            title: form.title.trim(),
            description: form.description.trim() || null,
            items: items.filter(it => it.title.trim())
                .map((it, i) => ({ title: it.title.trim(), priority: it.priority, order_index: i })),
        };
        try {
            if (view === "edit" && editingTemplate) {
                await apiRequest({ path: `/templates/${editingTemplate.id}`, method: "PUT", token, body });
            } else {
                await apiRequest({ path: "/templates", method: "POST", token, body });
            }
            await loadTemplates();
            setView("list");
        } catch (e) { setError(e.message); }
        finally { setSaving(false); }
    }

    async function handleDelete(id) {
        if (!window.confirm("Удалить шаблон?")) return;
        try {
            await apiRequest({ path: `/templates/${id}`, method: "DELETE", token });
            await loadTemplates();
        } catch (e) { setError(e.message); }
    }

    function openApply(tpl) {
        setApplyTemplate(tpl);
        setApplyProjectId(projects.length > 0 ? String(projects[0].id) : "");
        setApplySuccess(null);
    }

    async function handleApply() {
        if (!applyProjectId || !applyTemplate) return;
        setApplying(true);
        try {
            const created = await apiRequest({
                path: `/templates/${applyTemplate.id}/apply`,
                method: "POST", token,
                body: { project_id: Number(applyProjectId) },
            });
            setApplySuccess(Array.isArray(created) ? created.length : "?");
        } catch (e) { setError(e.message); setApplyTemplate(null); }
        finally { setApplying(false); }
    }

    const TEMPLATE_ICON = "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zm-1 1.5L18.5 9H13V3.5zM6 20V4h5v7h7v9H6z";

    if (view === "create" || view === "edit") {
        return (
            <div className="card" style={{ marginTop: 0 }}>
                <div className="section-header">
                    <div>
                        <div className="section-title">{view === "edit" ? "Редактировать шаблон" : "Новый шаблон"}</div>
                        <div className="section-sub">Добавьте задачи, которые будут созданы при применении</div>
                    </div>
                    <button className="btn btn-ghost btn-sm" onClick={() => setView("list")}>
                        <Icon d={ICONS.x} /> Отмена
                    </button>
                </div>
                {error && <div style={{ color: "var(--red)", marginBottom: 12, fontSize: 13 }}>{error}</div>}
                <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 20 }}>
                    <div>
                        <label className="field-label">НАЗВАНИЕ ШАБЛОНА</label>
                        <input className="input" placeholder="Например: Спринт разработки"
                            value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} />
                    </div>
                    <div>
                        <label className="field-label">ОПИСАНИЕ (необязательно)</label>
                        <textarea className="input" rows={2} placeholder="Для чего этот шаблон…"
                            value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                            style={{ resize: "vertical" }} />
                    </div>
                </div>
                <div style={{ marginBottom: 12 }}>
                    <label className="field-label">ЗАДАЧИ В ШАБЛОНЕ</label>
                    {items.length === 0 && (
                        <div style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 8 }}>
                            Нет задач. Добавьте хотя бы одну.
                        </div>
                    )}
                    {items.map((item, idx) => (
                        <div key={idx} draggable
                            onDragStart={() => onDragStart(idx)}
                            onDragOver={e => onDragOver(e, idx)}
                            onDragEnd={onDragEnd}
                            style={{
                                display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
                                padding: "8px 10px", background: "var(--bg-card2)", borderRadius: 8,
                                cursor: "grab", border: "1px solid var(--border)",
                            }}>
                            <span style={{ color: "var(--text-muted)", fontSize: 16, cursor: "grab", flexShrink: 0 }}>⠿</span>
                            <input className="input" placeholder="Название задачи" value={item.title}
                                onChange={e => updateItem(idx, "title", e.target.value)}
                                style={{ flex: 1, marginBottom: 0 }} />
                            <select className="input" value={item.priority}
                                onChange={e => updateItem(idx, "priority", e.target.value)}
                                style={{ width: 130, flexShrink: 0, color: PRIORITY_COLORS[item.priority], marginBottom: 0 }}>
                                {Object.entries(PRIORITY_LABELS).map(([val, label]) => (
                                    <option key={val} value={val}>{PRIORITY_ICONS[val]} {label}</option>
                                ))}
                            </select>
                            <button className="btn btn-ghost btn-sm" onClick={() => removeItem(idx)}
                                style={{ flexShrink: 0, color: "var(--red)" }}>
                                <Icon d={ICONS.x} />
                            </button>
                        </div>
                    ))}
                    <button className="btn btn-ghost btn-sm" onClick={addItem} style={{ marginTop: 4 }}>
                        <Icon d={ICONS.plus} /> Добавить задачу
                    </button>
                </div>
                <button className="btn btn-primary" onClick={handleSave}
                    disabled={saving || !form.title.trim()} style={{ width: "100%", marginTop: 8 }}>
                    <Icon d={ICONS.save} /> {saving ? "Сохранение…" : view === "edit" ? "Сохранить изменения" : "Создать шаблон"}
                </button>
            </div>
        );
    }

    return (
        <>
            <div className="card" style={{ marginTop: 0 }}>
                <div className="section-header">
                    <div>
                        <div className="section-title">Шаблоны задач</div>
                        <div className="section-sub">
                            {templates.length > 0
                                ? `${templates.length} шаблон${templates.length === 1 ? "" : templates.length < 5 ? "а" : "ов"}`
                                : "Создайте шаблон и применяйте его к проектам"}
                        </div>
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                        <button className="btn btn-ghost btn-sm" onClick={loadTemplates} disabled={loading}>
                            <Icon d={ICONS.refresh} /> Обновить
                        </button>
                        <button className="btn btn-primary btn-sm" onClick={openCreate}>
                            <Icon d={ICONS.plus} /> Новый шаблон
                        </button>
                    </div>
                </div>
                {error && <div style={{ color: "var(--red)", marginBottom: 12, fontSize: 13 }}>{error}</div>}
                {loading ? (
                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                ) : templates.length === 0 ? (
                    <div className="empty-state" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
                        <div className="empty-icon">📋</div>
                        <span>Нет шаблонов</span>
                        <button className="btn btn-primary btn-sm" onClick={openCreate}>
                            <Icon d={ICONS.plus} /> Создать первый шаблон
                        </button>
                    </div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 12 }}>
                        {templates.map(tpl => (
                            <div key={tpl.id} style={{
                                background: "var(--bg-card2)", border: "1px solid var(--border)",
                                borderRadius: 12, padding: "14px 16px",
                            }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                                            <Icon d={TEMPLATE_ICON} size={16} />
                                            <span style={{ fontWeight: 600, fontSize: 15 }}>{tpl.title}</span>
                                        </div>
                                        {tpl.description && (
                                            <div style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 8 }}>
                                                {tpl.description}
                                            </div>
                                        )}
                                        {tpl.items && tpl.items.length > 0 ? (
                                            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                                                {[...tpl.items].sort((a, b) => a.order_index - b.order_index).map(item => (
                                                    <span key={item.id} className="meta-chip" style={{
                                                        background: PRIORITY_COLORS[item.priority] + "18",
                                                        color: PRIORITY_COLORS[item.priority],
                                                        border: `1px solid ${PRIORITY_COLORS[item.priority]}33`,
                                                    }}>
                                                        {PRIORITY_ICONS[item.priority]} {item.title}
                                                    </span>
                                                ))}
                                            </div>
                                        ) : (
                                            <span style={{ color: "var(--text-muted)", fontSize: 12 }}>Нет задач</span>
                                        )}
                                    </div>
                                    <div style={{ display: "flex", flexDirection: "column", gap: 6, flexShrink: 0 }}>
                                        <button className="btn btn-primary btn-sm" onClick={() => openApply(tpl)}
                                            disabled={!tpl.items || tpl.items.length === 0}>
                                            ▶ Использовать
                                        </button>
                                        <button className="btn btn-ghost btn-sm" onClick={() => openEdit(tpl)}>
                                            <Icon d={ICONS.edit} /> Изменить
                                        </button>
                                        <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(tpl.id)}
                                            style={{ color: "var(--red)" }}>
                                            <Icon d={ICONS.trash} /> Удалить
                                        </button>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {applyTemplate && (
                <div style={{
                    position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    zIndex: 1000, padding: 16,
                }} onClick={e => { if (e.target === e.currentTarget) { setApplyTemplate(null); setApplySuccess(null); } }}>
                    <div style={{
                        background: "var(--bg-card)", border: "1px solid var(--border)",
                        borderRadius: 16, padding: 24, width: "100%", maxWidth: 420,
                    }}>
                        {applySuccess !== null ? (
                            <div style={{ textAlign: "center" }}>
                                <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
                                <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 8 }}>Создано {applySuccess} задач</div>
                                <div style={{ color: "var(--text-muted)", fontSize: 14, marginBottom: 20 }}>
                                    Задачи из шаблона «{applyTemplate.title}» добавлены в проект.
                                </div>
                                <button className="btn btn-primary" style={{ width: "100%" }}
                                    onClick={() => { setApplyTemplate(null); setApplySuccess(null); }}>
                                    Закрыть
                                </button>
                            </div>
                        ) : (
                            <>
                                <div style={{ fontWeight: 700, fontSize: 17, marginBottom: 4 }}>Применить шаблон</div>
                                <div style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 20 }}>
                                    «{applyTemplate.title}» — {applyTemplate.items?.length ?? 0} задач
                                </div>
                                <label className="field-label">ВЫБЕРИТЕ ПРОЕКТ</label>
                                {projects.length === 0 ? (
                                    <div style={{ color: "var(--red)", fontSize: 13, marginBottom: 16 }}>
                                        Нет доступных проектов. Сначала создайте проект.
                                    </div>
                                ) : (
                                    <select className="input" value={applyProjectId}
                                        onChange={e => setApplyProjectId(e.target.value)}
                                        style={{ marginBottom: 20 }}>
                                        {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                                    </select>
                                )}
                                <div style={{ display: "flex", gap: 8 }}>
                                    <button className="btn btn-ghost" style={{ flex: 1 }}
                                        onClick={() => { setApplyTemplate(null); setApplySuccess(null); }}>
                                        Отмена
                                    </button>
                                    <button className="btn btn-primary" style={{ flex: 1 }}
                                        onClick={handleApply}
                                        disabled={applying || !applyProjectId || projects.length === 0}>
                                        {applying ? "Создание…" : "Создать задачи"}
                                    </button>
                                </div>
                            </>
                        )}
                    </div>
                </div>
            )}
        </>
    );
}

// ─── ProjectsTab ──────────────────────────────────────────
function ProjectsTab({ token, canManage, currentUserId, currentRole }) {
    const [projects, setProjects] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [selectedProject, setSelectedProject] = useState(null);
    const [projectTasks, setProjectTasks] = useState([]);
    const [tasksLoading, setTasksLoading] = useState(false);
    const [showCreate, setShowCreate] = useState(false);
    const [createForm, setCreateForm] = useState({ name: "", description: "", group_id: "" });
    const [creating, setCreating] = useState(false);
    const [groups, setGroups] = useState([]);
    // const [showGroupPicker, setShowGroupPicker] = useState(false);
    const [groupPickerProjectId, setGroupPickerProjectId] = useState(null);
    const [settingGroup, setSettingGroup] = useState(false);

    // Редактирование проекта в списке
    const [editingProjectId, setEditingProjectId] = useState(null);
    const [editForm, setEditForm] = useState({ name: "", description: "" });
    const [saving, setSaving] = useState(false);

    // Управление участниками в списке
    const [membersProjectId, setMembersProjectId] = useState(null);
    const [membersData, setMembersData] = useState({}); // { [projectId]: [{id, username}] }
    const [addMemberUserId, setAddMemberUserId] = useState("");
    const [memberLoading, setMemberLoading] = useState(false);

    // Форма создания задачи внутри проекта
    const [showTaskForm, setShowTaskForm] = useState(false);
    const [taskForm, setTaskForm] = useState({ title: "", description: "", deadline: "", priority: "medium" });
    const [users, setUsers] = useState([]);
    const [assignUserId, setAssignUserId] = useState("");
    const [creatingTask, setCreatingTask] = useState(false);
    const [taskError, setTaskError] = useState(null);

    async function loadProjects() {
        setLoading(true);
        try {
            const data = await apiRequest({ path: "/projects?page=1&size=50", token });
            setProjects(extractItems(data));
            setTotal(data?.total ?? 0);
        } catch { setProjects([]); }
        finally { setLoading(false); }
    }

    async function loadUsers() {
        try {
            const data = await apiRequest({ path: "/users?page=1&size=100", token });
            setUsers(extractItems(data));
        } catch { setUsers([]); }
    }

    async function loadGroups() {
        try {
            const data = await apiRequest({ path: "/groups?page=1&size=100", token });
            setGroups(extractItems(data));
        } catch { setGroups([]); }
    }

    useEffect(() => { loadProjects(); loadUsers(); loadGroups(); }, []); // eslint-disable-line

    async function handleCreate(e) {
        e.preventDefault();
        if (!createForm.name.trim()) return;
        setCreating(true);
        setError(null);
        try {
            await apiRequest({
                path: "/projects", method: "POST", token, body: {
                    name: createForm.name.trim(),
                    description: createForm.description.trim() || null,
                    group_id: createForm.group_id ? Number(createForm.group_id) : null,
                }
            });
            setCreateForm({ name: "", description: "", group_id: "" });
            setShowCreate(false);
            await loadProjects();
        } catch (err) { setError(err.message); }
        finally { setCreating(false); }
    }

    async function handleDelete(projectId) {
        if (!window.confirm("Удалить проект и все его задачи? Это действие необратимо.")) return;
        try {
            await apiRequest({ path: `/projects/${projectId}`, method: "DELETE", token });
            if (selectedProject?.id === projectId) {
                setSelectedProject(null);
                setProjectTasks([]);
            }
            await loadProjects();
        } catch (err) { setError(err.message); }
    }

    async function loadProjectTasks(projectId) {
        setTasksLoading(true);
        try {
            const data = await apiRequest({
                path: `/tasks/filter?project_id=${projectId}&page=1&size=100`, token
            });
            setProjectTasks(extractItems(data));
        } catch { setProjectTasks([]); }
        finally { setTasksLoading(false); }
    }

    async function openProject(projectId) {
        try {
            const data = await apiRequest({ path: `/projects/${projectId}`, token });
            setSelectedProject(data);
            setProjectTasks([]);
            setShowTaskForm(false);
            await loadProjectTasks(projectId);
        } catch (err) { setError(err.message); }
    }

    async function handleCreateTask(e) {
        e.preventDefault();
        if (!taskForm.title.trim() || !selectedProject) return;
        setCreatingTask(true);
        setTaskError(null);
        try {
            await apiRequest({
                path: "/tasks", method: "POST", token, body: {
                    title: taskForm.title.trim(),
                    description: taskForm.description.trim() || null,
                    deadline: taskForm.deadline ? `${taskForm.deadline}:00` : null,
                    priority: taskForm.priority || "medium",
                    project_id: selectedProject.id,
                    user_id: assignUserId ? Number(assignUserId) : null,
                }
            });
            setTaskForm({ title: "", description: "", deadline: "", priority: "medium" });
            setAssignUserId("");
            setShowTaskForm(false);
            await loadProjectTasks(selectedProject.id);
        } catch (err) { setTaskError(err.message); }
        finally { setCreatingTask(false); }
    }

    // async function handleSetGroup(groupId) {
    //     if (!selectedProject) return;
    //     setSettingGroup(true);
    //     try {
    //         await apiRequest({
    //             path: `/projects/${selectedProject.id}/group`,
    //             method: "PATCH",
    //             token,
    //             body: { group_id: groupId || null },
    //         });
    //         const data = await apiRequest({ path: `/projects/${selectedProject.id}`, token });
    //         setSelectedProject(data);
    //         setShowGroupPicker(false);
    //     } catch (err) { setError(err.message); }
    //     finally { setSettingGroup(false); }
    // }
    async function handleSetGroup(projectId, groupId) {
        setSettingGroup(true);

        try {
            await apiRequest({
                path: `/projects/${projectId}/group`,
                method: "PATCH",
                token,
                body: { group_id: groupId || null },
            });

            // обновляем список проектов
            await loadProjects();

            setGroupPickerProjectId(null);
        } catch (err) {
            setError(err.message);
        } finally {
            setSettingGroup(false);
        }
    }

    async function handleEditProject(e, projectId) {
        e.preventDefault();
        if (!editForm.name.trim()) return;
        setSaving(true);
        try {
            await apiRequest({
                path: `/projects/${projectId}`, method: "PATCH", token,
                body: { name: editForm.name.trim(), description: editForm.description.trim() || null },
            });
            setEditingProjectId(null);
            await loadProjects();
        } catch (err) { setError(err.message); }
        finally { setSaving(false); }
    }

    async function loadProjectMembers(projectId) {
        try {
            const data = await apiRequest({ path: `/projects/${projectId}`, token });
            setMembersData(prev => ({ ...prev, [projectId]: data.members || [] }));
        } catch { /* ignore */ }
    }

    async function toggleMembersPanel(projectId, currentMembers) {
        if (membersProjectId === projectId) {
            setMembersProjectId(null);
            setAddMemberUserId("");
        } else {
            setMembersProjectId(projectId);
            setAddMemberUserId("");
            setMembersData(prev => ({ ...prev, [projectId]: currentMembers || [] }));
            await loadProjectMembers(projectId);
        }
    }

    async function handleAddMember(projectId) {
        if (!addMemberUserId) return;
        setMemberLoading(true);
        try {
            await apiRequest({ path: `/projects/${projectId}/members/${addMemberUserId}`, method: "POST", token });
            setAddMemberUserId("");
            await loadProjectMembers(projectId);
            await loadProjects();
        } catch (err) { setError(err.message); }
        finally { setMemberLoading(false); }
    }

    async function handleRemoveMember(projectId, userId) {
        setMemberLoading(true);
        try {
            await apiRequest({ path: `/projects/${projectId}/members/${userId}`, method: "DELETE", token });
            await loadProjectMembers(projectId);
            await loadProjects();
        } catch (err) { setError(err.message); }
        finally { setMemberLoading(false); }
    }

    const pct = (p) => p.task_count > 0 ? Math.round((p.done_count / p.task_count) * 100) : 0;

    // ── Детальный вид проекта ──────────────────────────────
    if (selectedProject) {
        const progress = selectedProject.task_count > 0
            ? Math.round((selectedProject.done_count / selectedProject.task_count) * 100) : 0;
        return (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div className="card">
                    <button className="btn btn-ghost btn-sm" onClick={() => { setSelectedProject(null); setProjectTasks([]); }} style={{ marginBottom: 12 }}>
                        ← Назад к проектам
                    </button>
                    <div className="section-header">
                        <div>
                            <div className="section-title">{selectedProject.name}</div>
                            {selectedProject.description && (
                                <div className="section-sub">{selectedProject.description}</div>
                            )}
                            {selectedProject.group?.name && (
                                <div style={{ marginTop: 4 }}>
                                    <span className="meta-chip" style={{ fontSize: 12 }}>
                                        🏷 {selectedProject.group.name}
                                    </span>
                                </div>
                            )}
                        </div>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                            <button className="btn btn-primary btn-sm"
                                onClick={() => { setShowTaskForm(v => !v); setTaskError(null); }}>
                                <Icon d={ICONS.plus} /> Создать задачу
                            </button>
                            {canManage && (
                                <button className="btn btn-ghost btn-sm" style={{ color: "var(--red)" }}
                                    onClick={() => handleDelete(selectedProject.id)}>
                                    🗑 Удалить
                                </button>
                            )}
                        </div>
                    </div>

                    {/* Форма создания задачи */}
                    {showTaskForm && (
                        <form onSubmit={handleCreateTask} style={{
                            display: "flex", flexDirection: "column", gap: 10,
                            marginBottom: 16, padding: 14,
                            background: "var(--surface2)", borderRadius: 10,
                            border: "1px solid var(--border)"
                        }}>
                            {taskError && <div className="alert">{taskError}</div>}
                            <div className="form-group">
                                <label className="form-label">Заголовок *</label>
                                <input placeholder="Что нужно сделать?"
                                    value={taskForm.title}
                                    onChange={e => setTaskForm(f => ({ ...f, title: e.target.value }))} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Описание</label>
                                <textarea placeholder="Необязательно" rows={2}
                                    value={taskForm.description}
                                    onChange={e => setTaskForm(f => ({ ...f, description: e.target.value }))} />
                            </div>
                            <div className="form-two-col">
                                <div className="form-group">
                                    <label className="form-label">Дедлайн</label>
                                    <input type="datetime-local" value={taskForm.deadline}
                                        onChange={e => setTaskForm(f => ({ ...f, deadline: e.target.value }))} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">Приоритет</label>
                                    <select value={taskForm.priority}
                                        onChange={e => setTaskForm(f => ({ ...f, priority: e.target.value }))}>
                                        <option value="low">⚪ Низкий</option>
                                        <option value="medium">🔵 Средний</option>
                                        <option value="high">🟠 Высокий</option>
                                        <option value="critical">🔴 Критический</option>
                                    </select>
                                </div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">Назначить</label>
                                <select value={assignUserId}
                                    onChange={e => setAssignUserId(e.target.value)}>
                                    <option value="">— Никому —</option>
                                    {users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                                </select>
                            </div>
                            <div style={{ display: "flex", gap: 8 }}>
                                <button type="submit" className="btn btn-primary btn-sm"
                                    disabled={creatingTask || !taskForm.title.trim()}>
                                    <Icon d={ICONS.plus} /> {creatingTask ? "Создание…" : "Создать"}
                                </button>
                                <button type="button" className="btn btn-ghost btn-sm"
                                    onClick={() => { setShowTaskForm(false); setTaskError(null); }}>
                                    Отмена
                                </button>
                            </div>
                        </form>
                    )}

                    <div className="stats-grid" style={{ marginBottom: 12 }}>
                        <div className="stat-box">
                            <div className="stat-value">{selectedProject.task_count}</div>
                            <div className="stat-label">Задач</div>
                        </div>
                        <div className="stat-box">
                            <div className="stat-value" style={{ color: "var(--green)" }}>{selectedProject.done_count}</div>
                            <div className="stat-label">Готово</div>
                        </div>
                        <div className="stat-box">
                            <div className="stat-value" style={{ color: "var(--accent-light)" }}>
                                {selectedProject.task_count - selectedProject.done_count}
                            </div>
                            <div className="stat-label">В работе</div>
                        </div>
                    </div>
                    <div className="progress-wrap" style={{ marginBottom: 16 }}>
                        <div className="progress-track">
                            <div className="progress-fill" style={{ width: `${progress}%` }} />
                        </div>
                        <div className="progress-caption">{progress}% выполнено</div>
                    </div>

                    {selectedProject.members && selectedProject.members.length > 0 && (
                        <div style={{ marginBottom: 16 }}>
                            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6 }}>
                                👥 Участники
                            </div>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                                {selectedProject.members.map(m => (
                                    <span key={m.id} className="meta-chip">{m.username}</span>
                                ))}
                            </div>
                        </div>
                    )}

                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-muted)" }}>
                            📋 Задачи проекта
                        </div>
                        <button className="btn btn-ghost btn-sm" onClick={() => loadProjectTasks(selectedProject.id)} disabled={tasksLoading}>
                            <Icon d={ICONS.refresh} /> {tasksLoading ? "…" : "Обновить"}
                        </button>
                    </div>

                    {tasksLoading ? (
                        <div className="empty-state" style={{ padding: "16px 0" }}>
                            <div className="empty-icon">⏳</div>Загрузка задач…
                        </div>
                    ) : projectTasks.length === 0 ? (
                        <div className="empty-state" style={{ padding: "16px 0" }}>
                            <div className="empty-icon">📋</div>Нет задач в проекте
                        </div>
                    ) : (
                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                            {projectTasks.map(t => (
                                <TaskCard
                                    key={t.id}
                                    task={t}
                                    groups={[]}
                                    users={users}
                                    token={token}
                                    onToggle={async (task, newStatus) => {
                                        const nextIsDone = newStatus === "done";

                                        setProjectTasks(prev => prev.map(t =>
                                            t.id === task.id
                                                ? { ...t, status: newStatus, is_done: nextIsDone }
                                                : t
                                        ));

                                        try {
                                            await apiRequest({
                                                path: `/tasks/${task.id}/status`,
                                                method: "PATCH",
                                                token,
                                                body: { status: newStatus },
                                            });
                                        } catch {
                                            setProjectTasks(prev => prev.map(t =>
                                                t.id === task.id
                                                    ? { ...t, status: task.status, is_done: task.is_done }
                                                    : t
                                            ));
                                        }
                                    }}
                                    onDelete={async (task) => {
                                        if (!window.confirm("Удалить задачу?")) return;
                                        setProjectTasks(prev => prev.filter(t => t.id !== task.id));
                                        try {
                                            await apiRequest({ path: `/tasks/${task.id}`, method: "DELETE", token });
                                        } catch {
                                            await loadProjectTasks(selectedProject.id);
                                        }
                                    }}
                                    onUpdate={async (task, updates) => {
                                        setProjectTasks(prev => prev.map(t =>
                                            t.id === task.id ? { ...t, ...updates } : t
                                        ));
                                        try {
                                            await apiRequest({
                                                path: `/tasks/${task.id}`,
                                                method: "PATCH",
                                                token,
                                                body: updates,
                                            });
                                        } catch {
                                            await loadProjectTasks(selectedProject.id);
                                        }
                                    }}
                                    onReassign={async (taskId, userId, groupId) => {
                                        await apiRequest({
                                            path: `/tasks/${taskId}`,
                                            method: "PATCH",
                                            token,
                                            body: { user_id: userId, group_id: groupId },
                                        });
                                        await loadProjectTasks(selectedProject.id);
                                    }}
                                    hideReassign
                                    collapsible
                                    currentUserId={currentUserId}
                                    currentRole={currentRole}
                                />
                            ))}
                        </div>
                    )}
                </div>
            </div>
        );
    }

    // ── Список проектов ────────────────────────────────────
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div className="card">
                <div className="section-header">
                    <div>
                        <div className="section-title">Проекты</div>
                        <div className="section-sub">{total > 0 ? `${total} проектов` : "Нет проектов"}</div>
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                        <button className="btn btn-ghost btn-sm" onClick={loadProjects} disabled={loading}>
                            <Icon d={ICONS.refresh} /> Обновить
                        </button>
                        {canManage && (
                            <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(v => !v)}>
                                + Создать
                            </button>
                        )}
                    </div>
                </div>

                {showCreate && (
                    <form onSubmit={handleCreate} style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12, padding: 12, background: "var(--surface)", borderRadius: 8 }}>
                        {error && <div className="alert">{error}</div>}
                        <div className="form-group">
                            <label className="form-label">Название *</label>
                            <input className="form-input" placeholder="Например, Редизайн сайта"
                                value={createForm.name}
                                onChange={e => setCreateForm(f => ({ ...f, name: e.target.value }))} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">Описание</label>
                            <textarea className="form-input" placeholder="Необязательно" rows={2}
                                value={createForm.description}
                                onChange={e => setCreateForm(f => ({ ...f, description: e.target.value }))} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">Группа</label>
                            <select value={createForm.group_id}
                                onChange={e => setCreateForm(f => ({ ...f, group_id: e.target.value }))}>
                                <option value="">— Без группы —</option>
                                {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                            </select>
                        </div>
                        <div style={{ display: "flex", gap: 8 }}>
                            <button type="submit" className="btn btn-primary btn-sm"
                                disabled={creating || !createForm.name.trim()}>
                                {creating ? "Создание…" : "Создать"}
                            </button>
                            <button type="button" className="btn btn-ghost btn-sm"
                                onClick={() => { setShowCreate(false); setError(null); }}>
                                Отмена
                            </button>
                        </div>
                    </form>
                )}
            </div>

            {loading ? (
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
            ) : projects.length === 0 ? (
                <div className="empty-state"><div className="empty-icon">📁</div>Нет доступных проектов</div>
            ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {projects.map(p => {
                        const isEditing = editingProjectId === p.id;
                        const isShowingMembers = membersProjectId === p.id;
                        const currentMembers = membersData[p.id] || p.members || [];
                        const notMember = users.filter(u => !currentMembers.some(m => m.id === u.id));
                        return (
                            <div key={p.id} className="card">
                                <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                                    <div style={{ fontSize: 28, lineHeight: 1, cursor: "pointer" }}
                                        onClick={() => openProject(p.id)}>📁</div>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        {isEditing ? (
                                            <form onSubmit={e => handleEditProject(e, p.id)}
                                                style={{ display: "flex", flexDirection: "column", gap: 8 }}
                                                onClick={e => e.stopPropagation()}>
                                                <input value={editForm.name}
                                                    onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))}
                                                    placeholder="Название проекта"
                                                    style={{ fontWeight: 600, fontSize: 14 }}
                                                    autoFocus />
                                                <textarea value={editForm.description}
                                                    onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))}
                                                    placeholder="Описание (необязательно)" rows={2} />
                                                <div style={{ display: "flex", gap: 6 }}>
                                                    <button type="submit" className="btn btn-primary btn-sm"
                                                        disabled={saving || !editForm.name.trim()}>
                                                        <Icon d={ICONS.save} /> {saving ? "…" : "Сохранить"}
                                                    </button>
                                                    <button type="button" className="btn btn-ghost btn-sm"
                                                        onClick={() => setEditingProjectId(null)}>
                                                        <Icon d={ICONS.x} /> Отмена
                                                    </button>
                                                </div>
                                            </form>
                                        ) : (
                                            <>
                                                <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4, cursor: "pointer" }}
                                                    onClick={() => openProject(p.id)}>
                                                    {p.name}
                                                </div>
                                                {p.description && (
                                                    <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 6, cursor: "pointer" }}
                                                        onClick={() => openProject(p.id)}>
                                                        {p.description}
                                                    </div>
                                                )}
                                                <div style={{ display: "flex", gap: 12, fontSize: 12, color: "var(--text-muted)", marginBottom: 8, cursor: "pointer" }}
                                                    onClick={() => openProject(p.id)}>
                                                    <span>📋 {p.task_count}</span>
                                                    <span style={{ color: "var(--green)" }}>✅ {p.done_count}</span>
                                                    {p.members?.length > 0 && <span>👥 {p.members.length}</span>}
                                                    {p.group?.name && <span>🏷 {p.group.name}</span>}
                                                </div>
                                                <div className="progress-wrap" style={{ cursor: "pointer" }}
                                                    onClick={() => openProject(p.id)}>
                                                    <div className="progress-track">
                                                        <div className="progress-fill" style={{ width: `${pct(p)}%` }} />
                                                    </div>
                                                    <div className="progress-caption">{pct(p)}%</div>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                    {canManage && !isEditing && (
                                        <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                                            <button className="btn btn-ghost btn-sm"
                                                title="Редактировать проект"
                                                onClick={e => {
                                                    e.stopPropagation();
                                                    setEditForm({ name: p.name, description: p.description || "" });
                                                    setEditingProjectId(p.id);
                                                    setMembersProjectId(null);
                                                }}>
                                                <Icon d={ICONS.edit} />
                                            </button>
                                            <button className="btn btn-ghost btn-sm"
                                                title="Участники"
                                                style={{ color: isShowingMembers ? "var(--accent-light)" : undefined }}
                                                onClick={e => { e.stopPropagation(); toggleMembersPanel(p.id, p.members); }}>
                                                <Icon d={ICONS.userPlus} />
                                            </button>
                                            {/* сюда кнопку  */}
                                            <button
                                                className="btn btn-ghost btn-sm"
                                                title={p.group ? "Сменить группу" : "Привязать группу"}
                                                onClick={e => {
                                                    e.stopPropagation();
                                                    setGroupPickerProjectId(
                                                        groupPickerProjectId === p.id ? null : p.id
                                                    );
                                                }}
                                            >
                                                🏷
                                            </button>
                                            <button className="btn btn-ghost btn-sm"
                                                title="Удалить проект"
                                                style={{ color: "var(--red)" }}
                                                onClick={e => { e.stopPropagation(); handleDelete(p.id); }}>
                                                <Icon d={ICONS.trash} />
                                            </button>
                                        </div>
                                    )}
                                </div>

                                {/* Панель выбора группы */}
                                {groupPickerProjectId === p.id && canManage && (
                                    <div
                                        style={{
                                            marginTop: 12,
                                            padding: 12,
                                            background: "var(--surface2)",
                                            borderRadius: 8,
                                            border: "1px solid var(--border)"
                                        }}
                                    >
                                        <select
                                            defaultValue={p.group_id || ""}
                                            onChange={e =>
                                                handleSetGroup(
                                                    p.id,
                                                    e.target.value ? Number(e.target.value) : null
                                                )
                                            }
                                            disabled={settingGroup}
                                            style={{ width: "100%" }}
                                        >
                                            <option value="">— Без группы —</option>
                                            {groups.map(g => (
                                                <option key={g.id} value={g.id}>
                                                    {g.name}
                                                </option>
                                            ))}
                                        </select>

                                        <button
                                            className="btn btn-ghost btn-sm"
                                            style={{ marginTop: 8 }}
                                            onClick={() => setGroupPickerProjectId(null)}
                                        >
                                            Отмена
                                        </button>
                                    </div>
                                )}

                                {/* Панель управления участниками */}
                                {isShowingMembers && canManage && (
                                    <div style={{
                                        marginTop: 12, padding: 12,
                                        background: "var(--surface2)", borderRadius: 8,
                                        border: "1px solid var(--border)"
                                    }}>
                                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 8 }}>
                                            👥 Участники проекта
                                        </div>
                                        {currentMembers.length === 0 ? (
                                            <div style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 8 }}>
                                                Нет участников
                                            </div>
                                        ) : (
                                            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
                                                {currentMembers.map(m => (
                                                    <span key={m.id} style={{
                                                        display: "inline-flex", alignItems: "center", gap: 4,
                                                        padding: "2px 8px", borderRadius: 12,
                                                        background: "var(--surface)", border: "1px solid var(--border)",
                                                        fontSize: 12,
                                                    }}>
                                                        {m.username}
                                                        <button
                                                            onClick={() => handleRemoveMember(p.id, m.id)}
                                                            disabled={memberLoading}
                                                            style={{
                                                                background: "none", border: "none", cursor: "pointer",
                                                                color: "var(--red)", padding: 0, lineHeight: 1,
                                                                display: "flex", alignItems: "center",
                                                            }}
                                                            title="Удалить участника">
                                                            <Icon d={ICONS.x} size={12} />
                                                        </button>
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                        <div style={{ display: "flex", gap: 6 }}>
                                            <select value={addMemberUserId}
                                                onChange={e => setAddMemberUserId(e.target.value)}
                                                style={{ flex: 1 }}
                                                disabled={memberLoading}>
                                                <option value="">Добавить участника…</option>
                                                {notMember.map(u => (
                                                    <option key={u.id} value={u.id}>{u.username}</option>
                                                ))}
                                            </select>
                                            <button className="btn btn-primary btn-sm"
                                                onClick={() => handleAddMember(p.id)}
                                                disabled={memberLoading || !addMemberUserId}>
                                                <Icon d={ICONS.userPlus} /> {memberLoading ? "…" : "Добавить"}
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

// ─── Groups Tab ───────────────────────────────────────────
function GroupsTab({ token, currentRole }) {
    const canManage = currentRole === "admin" || currentRole === "manager";
    const [groups, setGroups] = useState([]);
    const [allUsers, setAllUsers] = useState([]);
    const [loading, setLoading] = useState(false);

    const tokenRef = React.useRef(token);
    tokenRef.current = token;
    // loadingRef предотвращает двойной вызов при StrictMode double-mount
    const loadingRef = React.useRef(false);

    const loadGroups = useCallback(async () => {
        setLoading(true);
        try {
            const data = await apiRequest({ path: "/groups?page=1&size=100", token: tokenRef.current });
            setGroups(extractItems(data));
        } catch { setGroups([]); }
        finally { setLoading(false); }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);



    const loadUsers = useCallback(async () => {
        try {
            const data = await apiRequest({ path: "/users?page=1&size=100", token: tokenRef.current });
            setAllUsers(extractItems(data));
        } catch { setAllUsers([]); }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        // Защита от двойного вызова (React StrictMode монтирует дважды)
        if (loadingRef.current) return;
        loadingRef.current = true;
        loadGroups();
        loadUsers();
        return () => { loadingRef.current = false; };
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="content-grid" style={{ gridTemplateColumns: "1fr" }}>
            <div className="card">
                <div className="section-header">
                    <div>
                        <div className="section-title">
                            <Icon d={ICONS.group} size={15} /> Группы
                        </div>
                        <div className="section-sub">
                            {groups.length > 0 ? `${groups.length} групп` : "Нет групп"}
                            {canManage && " · вы можете управлять участниками"}
                        </div>
                    </div>
                    <button className="btn btn-ghost btn-sm" onClick={loadGroups} disabled={loading}>
                        <Icon d={ICONS.refresh} /> Обновить
                    </button>
                </div>

                {loading ? (
                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                ) : groups.length === 0 ? (
                    <div className="empty-state"><div className="empty-icon">👥</div>Групп нет</div>
                ) : (
                    <div className="group-list">
                        {groups.map(g => (
                            <GroupPanel
                                key={g.id}
                                group={g}
                                allUsers={allUsers}
                                token={token}
                                canManage={canManage}
                                onRefresh={loadGroups}
                            />
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}


// ─── Tokens Tab ───────────────────────────────────────────
function formatTokenDate(iso) {
    if (!iso) return "—";
    try {
        return new Date(iso).toLocaleString("ru-RU", {
            day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
        });
    } catch { return "—"; }
}

function TokensTab({ token }) {
    const [tokens, setTokens] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [newName, setNewName] = useState("");
    const [expiresInDays, setExpiresInDays] = useState("");
    const [creating, setCreating] = useState(false);
    const [justCreated, setJustCreated] = useState(null); // { token, name } — показываем один раз
    const [copied, setCopied] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await apiRequest({ path: "/tokens", token });
            setTokens(Array.isArray(data) ? data : []);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => { load(); }, [load]);

    async function handleCreate(e) {
        e.preventDefault();
        if (!newName.trim()) return;
        setCreating(true);
        setError(null);
        try {
            const body = { name: newName.trim() };
            if (expiresInDays) body.expires_in_days = Number(expiresInDays);
            const created = await apiRequest({ path: "/tokens", method: "POST", token, body });
            setJustCreated({ token: created.token, name: created.name });
            setNewName("");
            setExpiresInDays("");
            setCopied(false);
            await load();
        } catch (err) {
            setError(err.message);
        } finally {
            setCreating(false);
        }
    }

    async function handleRevoke(tokenId, name) {
        if (!window.confirm(`Отозвать токен «${name}»? Все интеграции, использующие его, сразу перестанут работать.`)) return;
        try {
            await apiRequest({ path: `/tokens/${tokenId}`, method: "DELETE", token });
            if (justCreated && tokens.find(t => t.id === tokenId)?.name === justCreated.name) {
                setJustCreated(null);
            }
            await load();
        } catch (err) {
            setError(err.message);
        }
    }

    async function handleCopy() {
        try {
            await navigator.clipboard.writeText(justCreated.token);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch { /* clipboard недоступен — пользователь скопирует вручную */ }
    }

    return (
        <div>
            <div className="card" style={{ marginTop: 0 }}>
                <div className="section-header">
                    <div>
                        <div className="section-title">🔑 Персональные API-токены</div>
                        <div className="section-sub">
                            Для скриптов и интеграций (Zapier-подобные сценарии), которым неудобно
                            перелогиниваться каждые 30 минут, как обычной веб-сессии.
                        </div>
                    </div>
                </div>

                {error && <div className="alert" style={{ marginBottom: 12 }}>{error}</div>}

                {justCreated && (
                    <div className="alert" style={{
                        marginBottom: 16, display: "flex", flexDirection: "column", gap: 8,
                        borderColor: "#22c55e", background: "#22c55e11",
                    }}>                        <div>
                            <strong>Токен «{justCreated.name}» создан.</strong> Сохраните его сейчас —
                            повторно посмотреть не получится, хранится только хэш.
                        </div>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                            <code style={{
                                flex: 1, padding: "8px 12px", background: "var(--surface2)",
                                borderRadius: 6, fontSize: 13, wordBreak: "break-all",
                            }}>
                                {justCreated.token}
                            </code>
                            <button type="button" className="btn btn-sm btn-primary" onClick={handleCopy}>
                                {copied ? "✓ Скопировано" : "Скопировать"}
                            </button>
                        </div>
                        <button type="button" className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start" }}
                            onClick={() => setJustCreated(null)}>
                            Скрыть
                        </button>
                    </div>
                )}

                <form className="form" onSubmit={handleCreate} style={{ marginBottom: 20 }}>
                    <div className="form-two-col">
                        <div className="form-group">
                            <label className="form-label">Название</label>
                            <input
                                value={newName}
                                onChange={e => setNewName(e.target.value)}
                                placeholder="Например: Zapier, личный скрипт…"
                            />
                        </div>
                        <div className="form-group">
                            <label className="form-label">Срок действия (дней)</label>
                            <input
                                type="number"
                                min="1"
                                max="3650"
                                value={expiresInDays}
                                onChange={e => setExpiresInDays(e.target.value)}
                                placeholder="Пусто — бессрочный"
                            />
                        </div>
                    </div>
                    <button className="btn btn-primary" type="submit" disabled={creating || !newName.trim()}>
                        <Icon d={ICONS.plus} /> {creating ? "Создание…" : "Создать токен"}
                    </button>
                </form>

                {loading ? (
                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                ) : tokens.length === 0 ? (
                    <div className="empty-state"><div className="empty-icon">🔑</div>Токенов пока нет</div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        {tokens.map(t => {
                            const isExpired = t.expires_at && new Date(t.expires_at) < new Date();
                            return (
                                <div key={t.id} style={{
                                    display: "flex", alignItems: "center", gap: 12,
                                    padding: "10px 14px", borderRadius: 8,
                                    background: "var(--surface2)", border: "1px solid var(--border)",
                                }}>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 8 }}>
                                            {t.name}
                                            {isExpired && <span className="meta-chip" style={{ background: "#ef444422", color: "#ef4444" }}>Истёк</span>}
                                        </div>
                                        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                                            <code>{t.token_prefix}…</code>
                                            {" · создан "}{formatTokenDate(t.created_at)}
                                            {" · истекает: "}{t.expires_at ? formatTokenDate(t.expires_at) : "никогда"}
                                            {" · использован: "}{t.last_used_at ? formatTokenDate(t.last_used_at) : "ни разу"}
                                        </div>
                                    </div>
                                    <button className="btn btn-danger btn-sm" onClick={() => handleRevoke(t.id, t.name)}>
                                        <Icon d={ICONS.trash} /> Отозвать
                                    </button>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
}


// ─── Dashboard Tab ────────────────────────────────────────
// ─── Push Notifications Card ───────────────────────────────
// Конвертирует VAPID public key из base64url в Uint8Array — именно в таком
// виде браузерный Push API ожидает applicationServerKey.
function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const rawData = window.atob(base64);
    return Uint8Array.from([...rawData].map(c => c.charCodeAt(0)));
}

function PushNotificationsCard({ token }) {
    const [supported] = useState(() => "serviceWorker" in navigator && "PushManager" in window);
    const [subscribed, setSubscribed] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [checked, setChecked] = useState(false);

    useEffect(() => {
        if (!supported) { setChecked(true); return; }
        (async () => {
            try {
                const reg = await navigator.serviceWorker.getRegistration();
                const sub = reg ? await reg.pushManager.getSubscription() : null;
                setSubscribed(!!sub);
            } catch { /* ignore — просто считаем неподписанным */ }
            finally { setChecked(true); }
        })();
    }, [supported]);

    async function handleEnable() {
        setBusy(true);
        setError(null);
        try {
            if (Notification.permission === "denied") {
                throw new Error("Уведомления заблокированы в настройках браузера для этого сайта.");
            }
            const permission = await Notification.requestPermission();
            if (permission !== "granted") {
                throw new Error("Разрешение на уведомления не получено.");
            }

            const reg = await navigator.serviceWorker.register("/sw.js");
            await navigator.serviceWorker.ready;

            const { public_key } = await apiRequest({ path: "/push/vapid-public-key", token });
            if (!public_key) {
                throw new Error("Push не настроен на сервере (нет VAPID-ключа).");
            }

            const subscription = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(public_key),
            });

            await apiRequest({ path: "/push/subscribe", method: "POST", token, body: subscription.toJSON() });
            setSubscribed(true);
        } catch (err) {
            setError(err.message);
        } finally {
            setBusy(false);
        }
    }

    async function handleDisable() {
        setBusy(true);
        setError(null);
        try {
            const reg = await navigator.serviceWorker.getRegistration();
            const sub = reg ? await reg.pushManager.getSubscription() : null;
            if (sub) {
                await apiRequest({ path: "/push/unsubscribe", method: "POST", token, body: { endpoint: sub.endpoint } });
                await sub.unsubscribe();
            }
            setSubscribed(false);
        } catch (err) {
            setError(err.message);
        } finally {
            setBusy(false);
        }
    }

    if (!supported) {
        return null; // старые браузеры / iOS Safari < 16.4 — молча не показываем блок
    }

    if (!checked) return null; // не мигаем состоянием, пока не проверили реальную подписку

    return (
        <div className="card">
            <div className="section-header">
                <div>
                    <div className="section-title">🔔 Push-уведомления в браузере</div>
                    <div className="section-sub">
                        Работает даже если вкладка закрыта — дублирует часть уведомлений Telegram-бота
                        для тех, кто не хочет держать Telegram открытым.
                    </div>
                </div>
                <button
                    className={`btn btn-sm ${subscribed ? "btn-ghost" : "btn-primary"}`}
                    onClick={subscribed ? handleDisable : handleEnable}
                    disabled={busy}
                >
                    {busy ? "…" : subscribed ? "Выключить" : "Включить"}
                </button>
            </div>
            {error && <div className="alert">{error}</div>}
        </div>
    );
}

function DashboardTab({ stats, loading, username, role, token }) {
    const isManagerOrAdmin = role === "admin" || role === "manager";

    if (loading) {
        return (
            <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "0 0 32px" }}>
                <PushNotificationsCard token={token} />
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка дашборда…</div>
                {isManagerOrAdmin && <ManagerAnalyticsSection token={token} />}
            </div>
        );
    }
    if (!stats) {
        return (
            <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "0 0 32px" }}>
                <PushNotificationsCard token={token} />
                <div className="empty-state"><div className="empty-icon">📊</div>Нет данных</div>
                {isManagerOrAdmin && <ManagerAnalyticsSection token={token} />}
            </div>
        );
    }

    const completionPercent = stats.total > 0 ? Math.round((stats.done / stats.total) * 100) : 0;
    const authorPercent = stats.a_total > 0 ? Math.round((stats.a_done / stats.a_total) * 100) : 0;

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "0 0 32px" }}>
            {/* Приветствие */}
            <div className="card" style={{ background: "linear-gradient(135deg, var(--accent) 0%, var(--accent-light) 100%)", border: "none" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div style={{ width: 48, height: 48, borderRadius: "50%", background: "rgba(255,255,255,0.2)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, fontWeight: 700, color: "#fff" }}>
                        {(username || "U")[0].toUpperCase()}
                    </div>
                    <div>
                        <div style={{ fontSize: 18, fontWeight: 700, color: "#fff" }}>Привет, {username}!</div>
                        <div style={{ fontSize: 13, color: "rgba(255,255,255,0.8)" }}>Роль: {role}</div>
                    </div>
                </div>
            </div>

            <PushNotificationsCard token={token} />

            {/* Мои задачи (исполнитель) */}
            <div className="card">
                <div className="section-header">
                    <div className="section-title">Назначено мне</div>
                    <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{completionPercent}% выполнено</div>
                </div>
                <div className="stats-grid" style={{ marginBottom: 12 }}>
                    <div className="stat-box">
                        <div className="stat-value">{stats.total ?? 0}</div>
                        <div className="stat-label">Всего</div>
                    </div>
                    <div className="stat-box">
                        <div className="stat-value" style={{ color: "var(--green)" }}>{stats.done ?? 0}</div>
                        <div className="stat-label">Готово</div>
                    </div>
                    <div className="stat-box">
                        <div className="stat-value" style={{ color: "var(--accent-light)" }}>{stats.pending ?? 0}</div>
                        <div className="stat-label">В работе</div>
                    </div>
                </div>
                <div className="progress-wrap">
                    <div className="progress-track">
                        <div className="progress-fill" style={{ width: `${completionPercent}%` }} />
                    </div>
                    <div className="progress-caption">{completionPercent}%</div>
                </div>
            </div>

            {/* Созданные мной */}
            <div className="card">
                <div className="section-header">
                    <div className="section-title">Создано мной</div>
                    <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{authorPercent}% выполнено</div>
                </div>
                <div className="stats-grid" style={{ marginBottom: 12 }}>
                    <div className="stat-box">
                        <div className="stat-value">{stats.a_total ?? 0}</div>
                        <div className="stat-label">Всего</div>
                    </div>
                    <div className="stat-box">
                        <div className="stat-value" style={{ color: "var(--green)" }}>{stats.a_done ?? 0}</div>
                        <div className="stat-label">Закрыто</div>
                    </div>
                    <div className="stat-box">
                        <div className="stat-value" style={{ color: "var(--accent-light)" }}>{(stats.a_total ?? 0) - (stats.a_done ?? 0)}</div>
                        <div className="stat-label">Открыто</div>
                    </div>
                </div>
                <div className="progress-wrap">
                    <div className="progress-track">
                        <div className="progress-fill" style={{ width: `${authorPercent}%` }} />
                    </div>
                    <div className="progress-caption">{authorPercent}%</div>
                </div>
            </div>

            {/* Последние задачи */}
            {stats.tasks && stats.tasks.length > 0 && (
                <div className="card">
                    <div className="section-header">
                        <div className="section-title">Последние задачи</div>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        {stats.tasks.map(t => (
                            <div key={t.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
                                <span style={{ fontSize: 16 }}>{t.is_done ? "✅" : "⏳"}</span>
                                <span style={{ flex: 1, fontSize: 14, color: t.is_done ? "var(--text-muted)" : "var(--text)", textDecoration: t.is_done ? "line-through" : "none" }}>
                                    {t.title}
                                </span>
                                {t.priority && (
                                    <span style={{ fontSize: 11, padding: "2px 6px", borderRadius: 4, background: PRIORITY_COLORS[t.priority] + "22", color: PRIORITY_COLORS[t.priority], fontWeight: 600 }}>
                                        {PRIORITY_LABELS[t.priority] ?? t.priority}
                                    </span>
                                )}
                                {t.deadline && (
                                    <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{t.deadline}</span>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Аналитика для менеджера/админа — отдельная секция, подгружает свои данные сама */}
            {isManagerOrAdmin && <ManagerAnalyticsSection token={token} />}
        </div>
    );
}

// ─── Manager Analytics Section ─────────────────────────────
function ManagerAnalyticsSection({ token }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            setLoading(true);
            try {
                const result = await apiRequest({ path: "/analytics/dashboard", token });
                if (!cancelled) setData(result);
            } catch (err) {
                if (!cancelled) setError(err.message);
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [token]);

    if (loading) {
        return (
            <div className="card">
                <div className="section-title" style={{ marginBottom: 12 }}>📊 Аналитика команды</div>
                <div className="empty-state"><div className="empty-icon">⏳</div>Считаем метрики…</div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="card">
                <div className="section-title" style={{ marginBottom: 12 }}>📊 Аналитика команды</div>
                <div className="alert">{error}</div>
            </div>
        );
    }

    const executors = data?.executor_completion || [];
    const projects = data?.project_overdue || [];

    return (
        <>
            <div className="card">
                <div className="section-header">
                    <div>
                        <div className="section-title">📊 Закрытие задач в срок — по исполнителям</div>
                        <div className="section-sub">Только задачи с дедлайном, которые уже завершены</div>
                    </div>
                </div>
                {executors.length === 0 ? (
                    <div className="empty-state"><div className="empty-icon">📊</div>Пока нет завершённых задач с дедлайном</div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        {executors.map(e => (
                            <div key={e.user_id}>
                                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontSize: 13 }}>
                                    <span style={{ fontWeight: 600 }}>{e.username}</span>
                                    <span style={{ color: "var(--text-muted)" }}>
                                        {e.on_time}/{e.total_completed} в срок ({e.on_time_rate}%)
                                    </span>
                                </div>
                                <div className="progress-track">
                                    <div
                                        className="progress-fill"
                                        style={{
                                            width: `${e.on_time_rate}%`,
                                            background: e.on_time_rate >= 80 ? "var(--green)" : e.on_time_rate >= 50 ? "#f59e0b" : "#ef4444",
                                        }}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <div className="card">
                <div className="section-header">
                    <div>
                        <div className="section-title">📊 Средняя просрочка — по проектам</div>
                        <div className="section-sub">Среди задач, закрытых с опозданием (в днях)</div>
                    </div>
                </div>
                {projects.length === 0 ? (
                    <div className="empty-state"><div className="empty-icon">📊</div>Пока нет данных по проектам</div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        {projects.map(p => (
                            <div key={p.project_id} style={{
                                display: "flex", alignItems: "center", justifyContent: "space-between",
                                padding: "8px 12px", borderRadius: 8, background: "var(--surface2)",
                            }}>
                                <div>
                                    <div style={{ fontWeight: 600, fontSize: 14 }}>{p.project_name}</div>
                                    <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                                        {p.completed_late}/{p.total_completed} закрыто с опозданием
                                    </div>
                                </div>
                                <span style={{
                                    fontSize: 16, fontWeight: 700,
                                    color: p.avg_overdue_days === 0 ? "var(--green)" : p.avg_overdue_days > 3 ? "#ef4444" : "#f59e0b",
                                }}>
                                    {p.avg_overdue_days === 0 ? "✓ вовремя" : `+${p.avg_overdue_days} дн.`}
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </>
    );
}

// ─── Main App ─────────────────────────────────────────────
function App() {
    const [token, setToken] = useState(localStorage.getItem("spisoc_token"));
    const [tab, setTab] = useState("tasks"); // "tasks" | "projects" | "groups" | "trash" | "dashboard" | "templates"

    // ── WebSocket realtime ────────────────────────────────────────────────────
    const handleWsEvent = useCallback((event, data) => {
        if (event === "task_created") {
            // Перезагружаем список если на вкладке задач
            if (tab === "tasks") loadTasks(tasksPage, viewMode);
            if (tab === "kanban") loadKanban();
        } else if (event === "task_updated" || event === "kanban_moved") {
            if (tab === "tasks") loadTasks(tasksPage, viewMode);
            if (tab === "kanban") loadKanban();
        } else if (event === "task_deleted") {
            if (tab === "tasks") loadTasks(tasksPage, viewMode);
            if (tab === "kanban") loadKanban();
        } else if (event === "task_restored") {
            if (tab === "trash") loadTrash();
        } else if (event === "comment_added") {
            // Комментарии обновятся при следующем открытии задачи
        }
    }, [tab]);  // eslint-disable-line

    useWebSocket(token, handleWsEvent);
    const [theme, setTheme] = useState(() => localStorage.getItem("spisoc_theme") || "dark");
    const [tasks, setTasks] = useState([]);
    const [trashTasks, setTrash] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [filterPriority, setFilterPriority] = useState(null);
    const [appProjects, setAppProjects] = useState([]);
    const [dashStats, setDashStats] = useState(null);
    const [dashLoading, setDashLoading] = useState(false);

    const [filterType, setFilterType] = useState("");
    const [statusFilter, setStatusFilter] = useState("");
    const [searchQuery, setSearchQuery] = useState("");
    const [viewMode, setViewMode] = useState("user"); // "user" | "author"

    const [tasksPage, setTasksPage] = useState(1);
    const [tasksTotal, setTasksTotal] = useState(0);
    const PAGE_SIZE = 50;

    const [trashPage, setTrashPage] = useState(1);
    const [trashTotal, setTrashTotal] = useState(0);

    const [groups, setGroups] = useState([]);
    const [users, setUsers] = useState([]);
    const [allTags, setAllTags] = useState([]);
    const [tagFilter, setTagFilter] = useState("");

    const [filterPresets, setFilterPresets] = useState([]);
    const [presetNameInput, setPresetNameInput] = useState("");
    const [savingPreset, setSavingPreset] = useState(false);

    const [form, setForm] = useState(initialForm);
    const [assignType, setAssignType] = useState("self");
    const [selectedGroupId, setSelectedGroupId] = useState("");
    const [selectedUserId, setSelectedUserId] = useState("");

    const tokenPayload = useMemo(() => decodeToken(token), [token]);
    const currentUserId = useMemo(() => tokenPayload?.sub ? Number(tokenPayload.sub) : null, [tokenPayload]);
    const currentUsername = useMemo(() => tokenPayload?.username || tokenPayload?.sub || "Пользователь", [tokenPayload]);
    const currentRole = useMemo(() => tokenPayload?.role ?? "user", [tokenPayload]);
    const canManage = currentRole === "admin" || currentRole === "manager";

    // Поиск теперь серверный (см. searchDebounceRef useEffect выше) — полнотекстовый
    // по title+description на всех страницах, а не только по уже загруженной.
    // Раньше здесь была клиентская фильтрация по подстроке в title/id —
    // это скрывало бы результаты, найденные сервером по description.
    const visibleTasks = tasks;

    const [selectedTaskIds, setSelectedTaskIds] = useState(new Set());
    const [bulkStatus, setBulkStatus] = useState("");
    const [bulkPriority, setBulkPriority] = useState("");
    const [bulkTagId, setBulkTagId] = useState("");
    const [bulkUserId, setBulkUserId] = useState("");
    const [bulkApplying, setBulkApplying] = useState(false);

    function toggleTaskSelection(taskId) {
        setSelectedTaskIds(prev => {
            const next = new Set(prev);
            if (next.has(taskId)) next.delete(taskId); else next.add(taskId);
            return next;
        });
    }

    function toggleSelectAllVisible() {
        setSelectedTaskIds(prev => {
            const allSelected = visibleTasks.every(t => prev.has(t.id));
            if (allSelected) return new Set(); // все выбраны — снимаем всё
            return new Set(visibleTasks.map(t => t.id)); // иначе выбираем все видимые
        });
    }

    async function handleBulkApply() {
        if (!bulkStatus && !bulkPriority && !bulkTagId && !bulkUserId) {
            setError("Выберите хотя бы одно поле для изменения");
            return;
        }

        const body = { task_ids: Array.from(selectedTaskIds) };
        if (bulkStatus) body.status = bulkStatus;
        if (bulkPriority) body.priority = bulkPriority;
        if (bulkTagId) body.tag_id = Number(bulkTagId);
        if (bulkUserId) body.user_id = Number(bulkUserId);

        setBulkApplying(true);
        try {
            const response = await fetch(`${API_BASE}/tasks/bulk`, {
                method: "PATCH",
                headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            if (!response.ok) {
                const text = await response.text();
                throw new Error(text || `Ошибка ${response.status}`);
            }
            const result = await response.json();
            if (result.skipped.length > 0) {
                setError(`Обновлено: ${result.updated}. Пропущено (нет доступа или удалены): ${result.skipped.join(", ")}`);
            }
            setSelectedTaskIds(new Set());
            setBulkStatus(""); setBulkPriority(""); setBulkTagId(""); setBulkUserId("");
            await loadTasks(tasksPage, viewMode);
        } catch (err) {
            setError(err.message);
        } finally {
            setBulkApplying(false);
        }
    }

    const [showTooltip, setShowTooltip] = useState(false);
    const chipRef = React.useRef(null);
    const [tooltipPos, setTooltipPos] = useState({ top: 0, right: 0 });
    const loadAppProjects = React.useCallback(async () => {
        if (!token) return;
        try {
            const data = await apiRequest({ path: "/projects?page=1&size=100", token });
            setAppProjects(extractItems(data));
        } catch { setAppProjects([]); }
    }, [token]);

    // Загружаем проекты при входе
    useEffect(() => { if (token) loadAppProjects(); }, [token, loadAppProjects]);

    // Применяем тему к документу
    useEffect(() => {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("spisoc_theme", theme);
    }, [theme]);

    // ── loaders ──────────────────────────────────────────
    // Refs позволяют функциям читать актуальные значения без пересоздания,
    // что исключает цепочку useCallback→useEffect→двойной setState
    const tokenRef = React.useRef(token);
    const filterTypeRef = React.useRef(filterType);
    const statusFilterRef = React.useRef(statusFilter);
    const viewModeRef = React.useRef(viewMode);
    tokenRef.current = token;
    filterTypeRef.current = filterType;
    statusFilterRef.current = statusFilter;
    viewModeRef.current = viewMode;

    const filterPriorityRef = React.useRef(filterPriority);
    filterPriorityRef.current = filterPriority;
    const searchQueryRef = React.useRef(searchQuery);
    searchQueryRef.current = searchQuery;
    const tagFilterRef = React.useRef(tagFilter);
    tagFilterRef.current = tagFilter;
    // AbortController отменяет предыдущий запрос при новом вызове
    const tasksAbortRef = React.useRef(null);
    const trashAbortRef = React.useRef(null);

    const loadTasks = useCallback(async (page = 1, filterUserGroup) => {
        // Отменяем предыдущий запрос если он ещё выполняется
        if (tasksAbortRef.current) tasksAbortRef.current.abort();
        const controller = new AbortController();
        tasksAbortRef.current = controller;

        const mode = filterUserGroup ?? viewModeRef.current;
        setLoading(true);
        try {
            const q = new URLSearchParams();
            q.set("filter_user_group", mode);
            q.set("page", page);
            q.set("size", PAGE_SIZE);
            if (filterTypeRef.current) q.set("filter_type", filterTypeRef.current);
            if (filterPriorityRef.current) q.set("priority", filterPriorityRef.current);
            if (statusFilterRef.current) q.set("status", statusFilterRef.current);
            if (searchQueryRef.current.trim()) q.set("search", searchQueryRef.current.trim());
            if (tagFilterRef.current) q.set("tag_id", tagFilterRef.current);
            const data = await apiRequest({ path: `/tasks/filter?${q}`, token: tokenRef.current });
            // Если запрос был отменён — игнорируем результат
            if (controller.signal.aborted) return;
            setTasks(extractItems(data));
            setTasksTotal(data?.total ?? 0);
            setTasksPage(page);
        } catch (err) {
            if (!controller.signal.aborted) handleAuthError(err);
        }
        finally {
            if (!controller.signal.aborted) setLoading(false);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const loadFilterPresets = useCallback(async () => {
        try {
            const data = await apiRequest({ path: "/tasks/presets", token: tokenRef.current });
            setFilterPresets(Array.isArray(data) ? data : []);
        } catch (err) {
            handleAuthError(err);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    async function handleSavePreset() {
        const name = presetNameInput.trim();
        if (!name) {
            setError("Введите название пресета");
            return;
        }
        setSavingPreset(true);
        try {
            await apiRequest({
                path: "/tasks/presets",
                method: "POST",
                token,
                body: {
                    name,
                    status: statusFilter || null,
                    priority: filterPriority || null,
                    tag_id: tagFilter ? Number(tagFilter) : null,
                    filter_user_group: viewMode || null,
                    filter_type: filterType || null,
                },
            });
            setPresetNameInput("");
            await loadFilterPresets();
        } catch (err) {
            setError(err.message);
        } finally {
            setSavingPreset(false);
        }
    }

    function handleApplyPreset(preset) {
        // Выставляем все стейты фильтров разом и перезагружаем список.
        setStatusFilter(preset.status || "");
        setFilterPriority(preset.priority || null);
        setTagFilter(preset.tag_id ? String(preset.tag_id) : "");
        setFilterType(preset.filter_type || "");
        if (preset.filter_user_group) setViewMode(preset.filter_user_group);
        // Рефы (statusFilterRef и т.д.) обновятся синхронно с ре-рендером на
        // следующий тик, поэтому передаём filter_user_group явным аргументом,
        // а не полагаемся на viewModeRef, который ещё не успеет обновиться.
        loadTasks(1, preset.filter_user_group || undefined);
    }

    async function handleDeletePreset(presetId) {
        try {
            await apiRequest({ path: `/tasks/presets/${presetId}`, method: "DELETE", token });
            setFilterPresets(prev => prev.filter(p => p.id !== presetId));
        } catch (err) {
            setError(err.message);
        }
    }

    const loadTrash = useCallback(async (page = 1) => {
        if (trashAbortRef.current) trashAbortRef.current.abort();
        const controller = new AbortController();
        trashAbortRef.current = controller;

        setLoading(true);
        try {
            const q = new URLSearchParams();
            q.set("page", page); q.set("size", PAGE_SIZE);
            const data = await apiRequest({ path: `/tasks/trash?${q}`, token: tokenRef.current });
            if (controller.signal.aborted) return;
            setTrash(extractItems(data));
            setTrashTotal(data?.total ?? 0);
            setTrashPage(page);
        } catch (err) {
            if (!controller.signal.aborted) handleAuthError(err);
        }
        finally {
            if (!controller.signal.aborted) setLoading(false);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const loadGroups = useCallback(async () => {
        try {
            const data = await apiRequest({ path: "/groups?page=1&size=100", token: tokenRef.current });
            setGroups(extractItems(data));
        } catch { setGroups([]); }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);


    const loadDashboard = useCallback(async () => {
        if (!tokenRef.current) return;
        setDashLoading(true);
        try {
            const [meData, statsData] = await Promise.all([
                apiRequest({ path: "/users/me", token: tokenRef.current }),
                apiRequest({ path: `/users/${currentUserId}/stats`, token: tokenRef.current }),
            ]);
            setDashStats({ ...statsData, username: meData?.username });
        } catch { setDashStats(null); }
        finally { setDashLoading(false); }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [currentUserId]);

    const loadUsers = useCallback(async () => {
        try {
            const data = await apiRequest({ path: "/users?page=1&size=100", token: tokenRef.current });
            setUsers(extractItems(data));
        } catch { setUsers([]); }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const loadTags = useCallback(async () => {
        try {
            const data = await apiRequest({ path: "/tags", token: tokenRef.current });
            // /tags отдаёт плоский массив (не пагинированный список), extractItems тут не нужен
            setAllTags(Array.isArray(data) ? data : []);
        } catch { setAllTags([]); }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Один эффект — все загрузки. Используем ref чтобы отделить
    // первый запуск (логин) от последующих (смена фильтров/вкладки).
    // isFirstRender объявлен ВНЕ useEffect и НЕ пересоздаётся при ре-рендере.
    const didInitRef = React.useRef(false);
    const prevTokenRef = React.useRef(null);

    useEffect(() => {
        if (!token) {
            // Логаут — сбрасываем флаг чтобы при следующем логине загрузить заново
            didInitRef.current = false;
            prevTokenRef.current = null;
            return;
        }

        const isNewLogin = token !== prevTokenRef.current;
        prevTokenRef.current = token;

        if (isNewLogin) {
            // Первый вход или смена токена — грузим всё
            didInitRef.current = true;
            loadGroups();
            loadUsers();
            loadTags();
            loadFilterPresets();
            if (tab === "tasks") loadTasks(1);
            if (tab === "trash") loadTrash(1);
            if (tab === "dashboard") loadDashboard();
        } else {
            // Смена фильтров/вкладки — только задачи
            if (tab === "tasks") loadTasks(1);
            if (tab === "trash") loadTrash(1);
            if (tab === "dashboard") loadDashboard();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token, tab, filterType, statusFilter, viewMode, filterPriority, tagFilter]);

    // Полнотекстовый поиск — дебаунс 400мс, серверный (title+description),
    // а не клиентская фильтрация по уже загруженной странице (та не видела бы
    // совпадения в description и не искала бы по остальным страницам).
    const searchDebounceRef = React.useRef(null);
    useEffect(() => {
        if (!didInitRef.current) return;
        if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
        searchDebounceRef.current = setTimeout(() => {
            if (tab === "tasks") loadTasks(1);
        }, 400);
        return () => clearTimeout(searchDebounceRef.current);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [searchQuery]);

    // ── auth ─────────────────────────────────────────────
    function handleAuthError(err) {
        if (["401", "403", "invalid"].some(s => err.message?.includes(s))) logout();
        else setError(err.message);
    }

    async function logout() {
        try {
            const refreshToken = getRefreshToken();
            if (refreshToken) {
                await apiRequest({
                    path: "/auth/logout", method: "POST",
                    token, body: { refresh_token: refreshToken },
                });
            }
        } catch { /* игнорируем ошибки при logout */ }
        clearTokens();
        setToken(null); setTasks([]);
    }

    async function handleLogin(e) {
        e.preventDefault();
        const fd = new FormData(e.target);
        try {
            setError(null);
            const resp = await apiRequest({
                path: "/auth/login", method: "POST",
                body: { username: fd.get("username"), password: fd.get("password") },
            });
            saveTokens(resp.access_token, resp.refresh_token);
            setToken(resp.access_token);
        } catch (err) { setError(err.message); }
    }

    // ── task actions ─────────────────────────────────────
    async function handleCreateTask(e) {
        e.preventDefault();
        if (!form.title.trim()) { setError("Введите заголовок задачи"); return; }
        try {
            setError(null);
            const payload = {
                title: form.title.trim(),
                description: form.description.trim() || null,
                status: form.status || "todo",
                priority: form.priority || "medium",
                project_id: form.project_id ? Number(form.project_id) : null,
                deadline: form.deadline ? `${form.deadline}:00` : null,
                recurrence_rule: form.recurrence_rule || "none",
            };
            if (assignType === "self") { payload.user_id = currentUserId; payload.group_id = null; }
            else if (assignType === "user") { payload.user_id = selectedUserId ? Number(selectedUserId) : null; payload.group_id = null; }
            else if (assignType === "group") { payload.group_id = selectedGroupId ? Number(selectedGroupId) : null; payload.user_id = null; }
            else { payload.user_id = null; payload.group_id = null; }

            await apiRequest({ path: "/tasks", method: "POST", token, body: payload });
            setForm(initialForm); setAssignType("self");
            setSelectedGroupId(""); setSelectedUserId("");
            await loadTasks(1);
        } catch (err) { handleAuthError(err); }
    }

    async function handleToggleTask(task, newStatus) {
        if (!newStatus) return;
        const nextIsDone = newStatus === "done";
        setTasks(prev => prev.map(t =>
            t.id === task.id ? { ...t, status: newStatus, is_done: nextIsDone } : t
        ));
        try {
            await apiRequest({
                path: `/tasks/${task.id}/status`,
                method: "PATCH",
                token,
                body: { status: newStatus },
            });
        } catch (err) {
            setTasks(prev => prev.map(t => t.id === task.id ? task : t));
            handleAuthError(err);
        }
    }

    async function handleUpdateTask(task, updates) {
        setTasks(prev => prev.map(t => t.id === task.id ? { ...t, ...updates } : t));
        try {
            await apiRequest({ path: `/tasks/${task.id}`, method: "PATCH", token, body: updates });
        } catch (err) {
            setTasks(prev => prev.map(t => t.id === task.id ? task : t));
            handleAuthError(err);
        }
    }

    async function handleDeleteTask(task) {
        setTasks(prev => prev.filter(t => t.id !== task.id));
        setTasksTotal(prev => prev - 1);
        try {
            await apiRequest({ path: `/tasks/${task.id}`, method: "DELETE", token });
        } catch (err) {
            setTasks(prev => [...prev, task].sort((a, b) => a.id - b.id));
            setTasksTotal(prev => prev + 1);
            handleAuthError(err);
        }
    }

    async function handleReassignTask(taskId, userId, groupId) {
        const userObj = userId ? users.find(u => u.id === Number(userId)) : null;
        const groupObj = groupId ? groups.find(g => g.id === Number(groupId)) : null;
        setTasks(prev => prev.map(t => t.id === taskId ? {
            ...t,
            ...(userObj ? { user: { id: userObj.id, username: userObj.username } } : {}),
            ...(groupObj ? { group: { id: groupObj.id, name: groupObj.name } } : {}),
        } : t));
        try {
            const q = new URLSearchParams();
            if (userId) q.set("user_id", userId);
            if (groupId) q.set("group_id", groupId);
            await apiRequest({ path: `/tasks/${taskId}/reassign?${q}`, method: "PATCH", token });
        } catch (err) {
            await loadTasks(tasksPage);
            handleAuthError(err);
        }
    }

    // TagsPanel сам делает PUT /tags/tasks/{id} — этот колбэк только
    // синхронизирует локальный кэш tasks[], чтобы чипы тегов в мета-строке
    // карточки обновились сразу, без повторной загрузки всей страницы.
    function handleTaskTagsUpdated(taskId, updatedTags) {
        setTasks(prev => prev.map(t => t.id === taskId ? { ...t, tags: updatedTags } : t));
    }

    const [exporting, setExporting] = useState(false);
    async function handleExportCsv() {
        // Экспорт отдаёт CSV-файл, а не JSON — apiRequest() из ./api не подходит
        // (он всегда пытается JSON.parse ответ), поэтому здесь прямой fetch с
        // ручной обработкой Blob и скачиванием через временную ссылку <a>.
        setExporting(true);
        try {
            const q = new URLSearchParams();
            if (statusFilter) q.set("status", statusFilter);
            if (filterPriority) q.set("priority", filterPriority);
            if (tagFilter) q.set("tag_id", tagFilter);

            const response = await fetch(`${API_BASE}/tasks/export?${q}`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (!response.ok) {
                const text = await response.text();
                throw new Error(text || `Ошибка ${response.status}`);
            }
            const blob = await response.blob();
            const disposition = response.headers.get("Content-Disposition") || "";
            const match = disposition.match(/filename="?([^"]+)"?/);
            const filename = match ? match[1] : "tasks_export.csv";

            const url = window.URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);
        } catch (err) {
            setError(err.message);
        } finally {
            setExporting(false);
        }
    }

    const [importing, setImporting] = useState(false);
    const [importSummary, setImportSummary] = useState(null); // { created, errors, warnings } | null
    const importInputRef = useRef(null);

    async function handleImportFile(e) {
        const file = e.target.files?.[0];
        e.target.value = ""; // сбрасываем, чтобы можно было выбрать тот же файл повторно
        if (!file) return;

        setImporting(true);
        setImportSummary(null);
        try {
            const formData = new FormData();
            formData.append("file", file);

            const q = new URLSearchParams();
            if (projectId) q.set("project_id", projectId); // если на странице выбран проект — импортируем в него

            const response = await fetch(`${API_BASE}/tasks/import?${q}`, {
                method: "POST",
                headers: { Authorization: `Bearer ${token}` }, // Content-Type НЕ ставим — fetch сам
                body: formData,                                // проставит multipart boundary
            });
            if (!response.ok) {
                const text = await response.text();
                throw new Error(text || `Ошибка ${response.status}`);
            }
            const summary = await response.json();
            setImportSummary(summary);
            await loadTasks(1); // перезагружаем список — импортированные задачи должны появиться
        } catch (err) {
            setError(err.message);
        } finally {
            setImporting(false);
        }
    }

    async function handleRestoreTask(task) {
        setTrash(prev => prev.filter(t => t.id !== task.id));
        setTrashTotal(prev => prev - 1);
        try {
            await apiRequest({ path: `/tasks/${task.id}/restore`, method: "PATCH", token });
        } catch (err) {
            setTrash(prev => [...prev, task].sort((a, b) => a.id - b.id));
            setTrashTotal(prev => prev + 1);
            handleAuthError(err);
        }
    }

    async function handleHardDelete(task) {
        if (!window.confirm("Удалить задачу навсегда? Это действие нельзя отменить.")) return;
        setTrash(prev => prev.filter(t => t.id !== task.id));
        setTrashTotal(prev => prev - 1);
        try {
            await apiRequest({ path: `/tasks/${task.id}/hard`, method: "DELETE", token });
        } catch (err) {
            setTrash(prev => [...prev, task].sort((a, b) => a.id - b.id));
            setTrashTotal(prev => prev + 1);
            handleAuthError(err);
        }
    }

    const stats = useMemo(() => {
        const total = tasks.length;
        const done = tasks.filter(t => t.is_done).length;
        return { total, done, pending: total - done, percent: total > 0 ? Math.round((done / total) * 100) : 0 };
    }, [tasks]);

    const tasksTotalPages = Math.ceil(tasksTotal / PAGE_SIZE);
    const trashTotalPages = Math.ceil(trashTotal / PAGE_SIZE);

    // ── Role badge in header ──────────────────────────────
    const roleColor = ROLE_COLORS[currentRole] ?? ROLE_COLORS.user;

    // ── Login screen ─────────────────────────────────────
    if (!token) {
        return (
            <div className="login-page">
                <div className="auth-card">
                    <div className="login-logo">
                        <div className="logo-mark">S</div>
                        <div>
                            <div className="brand-name">Spisoc</div>
                            <div className="brand-tagline">Управление задачами</div>
                        </div>
                    </div>
                    <div className="auth-title">Добро пожаловать</div>
                    <div className="auth-sub">Войдите, чтобы управлять задачами</div>
                    <form className="form" onSubmit={handleLogin}>
                        <div className="form-group">
                            <label className="form-label">Имя пользователя</label>
                            <input name="username" placeholder="admin" required minLength={3} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">Пароль</label>
                            <input name="password" type="password" placeholder="••••••••" required minLength={3} />
                        </div>
                        <button type="submit" className="btn btn-primary" style={{ marginTop: 4 }}>
                            Войти
                        </button>
                        {error && <div className="alert">{error}</div>}
                    </form>
                </div>
            </div>
        );
    }

    // ── Main screen ──────────────────────────────────────
    return (
        <div className="page-shell">
            <header className="app-header">
                <div className="app-header-left">
                    <div className="logo-mark">S</div>
                    <div>
                        <div className="brand-name">Spisoc</div>
                        <div className="brand-tagline">Менеджер задач</div>
                    </div>
                </div>
                <div className="header-right">
                    {/* Верхний ряд — пользователь и управление */}
                    <div className="header-row header-row-top">
                        <div className="user-chip"
                            ref={chipRef}
                            onMouseEnter={() => {
                                const rect = chipRef.current?.getBoundingClientRect();
                                if (rect) setTooltipPos({
                                    top: rect.bottom + 8,
                                    right: window.innerWidth - rect.right,
                                });
                                setShowTooltip(true);
                            }}
                            onMouseLeave={() => setShowTooltip(false)}>
                            <span className="user-chip-name">{currentUsername}</span>
                            <span className="role-badge" style={{ color: roleColor.color, background: roleColor.bg, marginLeft: 4 }}>
                                {ROLE_LABELS[currentRole] ?? currentRole}
                            </span>
                            {showTooltip && (
                                <span style={{
                                    position: "fixed",
                                    top: tooltipPos.top,
                                    right: tooltipPos.right,
                                    background: "var(--surface2)",
                                    border: "1px solid var(--border)",
                                    color: "var(--text)",
                                    fontSize: 12,
                                    padding: "5px 10px",
                                    borderRadius: 25,
                                    whiteSpace: "nowrap",
                                    zIndex: 1000,
                                }}>
                                    {currentUsername}
                                </span>
                            )}
                        </div>
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => setTheme(t => t === "dark" ? "light" : "dark")}
                            title="Переключить тему"
                            style={{ fontSize: "0.85rem" }}
                        >
                            {theme === "dark" ? "☀️" : "🌙"}
                        </button>
                        {currentRole === "admin" && (
                            <a
                                href={import.meta.env.DEV ? "http://127.0.0.1:8000/admin/" : "https://spisoc-del.onrender.com/admin/"}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="btn btn-ghost btn-sm"
                            >
                                <Icon d={ICONS.shield} /> Админка
                            </a>
                        )}
                        <button className="btn btn-ghost btn-sm" onClick={logout}>
                            <Icon d={ICONS.logout} /> Выйти
                        </button>
                    </div>
                    {/* Нижний ряд — навигация */}
                    <div className="header-row header-row-bottom">
                        <div className="tab-bar">
                            <button className={`tab-btn${tab === "dashboard" ? " active" : ""}`} onClick={() => { setTab("dashboard"); loadDashboard(); }}>
                                <Icon d={ICONS.chart} /> Дашборд
                            </button>
                            <button className={`tab-btn${tab === "tasks" ? " active" : ""}`} onClick={() => setTab("tasks")}>
                                Задачи {tasksTotal > 0 && <span className="count-badge">{tasksTotal}</span>}
                            </button>
                            <button className={`tab-btn${tab === "projects" ? " active" : ""}`} onClick={() => setTab("projects")}>
                                📁 Проекты
                            </button>
                            <button className={`tab-btn${tab === "kanban" ? " active" : ""}`} onClick={() => setTab("kanban")}>
                                <Icon d={ICONS.kanban ?? "M3 3h7v7H3zm0 11h7v7H3zm11-11h7v7h-7zm0 11h7v7h-7z"} /> Канбан
                            </button>
                            <button className={`tab-btn${tab === "templates" ? " active" : ""}`} onClick={() => setTab("templates")}>
                                <Icon d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zm-1 1.5L18.5 9H13V3.5zM6 20V4h5v7h7v9H6z" /> Шаблоны
                            </button>
                            <button className={`tab-btn${tab === "groups" ? " active" : ""}`} onClick={() => setTab("groups")}>
                                <Icon d={ICONS.group} /> Группы
                            </button>
                            <button className={`tab-btn${tab === "trash" ? " active" : ""}`} onClick={() => setTab("trash")}>
                                <Icon d={ICONS.trash} /> Корзина
                                {trashTotal > 0 && <span className="count-badge">{trashTotal}</span>}
                            </button>
                            <button className={`tab-btn${tab === "tokens" ? " active" : ""}`} onClick={() => setTab("tokens")}>
                                🔑 Токены
                            </button>
                        </div>
                    </div>
                </div>
            </header>

            {/* ── TASKS TAB ── */}
            {tab === "tasks" && (
                <div>
                    <div className="content-grid">
                        <aside className="sidebar-col">
                            <div className="card">
                                <div className="section-header">
                                    <div>
                                        <div className="section-title">Статистика</div>
                                        <div className="section-sub">Текущая страница</div>
                                    </div>
                                </div>
                                <div className="stats-grid">
                                    <div className="stat-box">
                                        <div className="stat-value">{tasksTotal}</div>
                                        <div className="stat-label">Всего</div>
                                    </div>
                                    <div className="stat-box">
                                        <div className="stat-value" style={{ color: "var(--green)" }}>{stats.done}</div>
                                        <div className="stat-label">Готово</div>
                                    </div>
                                    <div className="stat-box">
                                        <div className="stat-value" style={{ color: "var(--accent-light)" }}>{stats.pending}</div>
                                        <div className="stat-label">В работе</div>
                                    </div>
                                </div>
                                <div className="progress-wrap">
                                    <div className="progress-track">
                                        <div className="progress-fill" style={{ width: `${stats.percent}%` }} />
                                    </div>
                                    <div className="progress-caption">{stats.percent}% выполнено</div>
                                </div>
                            </div>

                            <div className="card">
                                <div className="section-header">
                                    <div className="section-title"><Icon d={ICONS.filter} size={13} /> Фильтры</div>
                                </div>
                                <div className="view-mode-row">
                                    <button
                                        className={`btn btn-sm ${viewMode === "user" ? "btn-primary" : "btn-ghost"}`}
                                        onClick={() => setViewMode("user")}>
                                        Мои задачи
                                    </button>
                                    <button
                                        className={`btn btn-sm ${viewMode === "author" ? "btn-primary" : "btn-ghost"}`}
                                        onClick={() => setViewMode("author")}>
                                        Я автор
                                    </button>
                                </div>
                                <div className="divider" />
                                <div className="filter-row">
                                    <div className="form-group">
                                        <label className="form-label">Приоритет</label>
                                        <select value={filterPriority || ""} onChange={e => setFilterPriority(e.target.value || null)}>
                                            <option value="">Все</option>
                                            <option value="critical">🔴 Критический</option>
                                            <option value="high">🟠 Высокий</option>
                                            <option value="medium">🔵 Средний</option>
                                            <option value="low">⚪ Низкий</option>
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">Тип задачи</label>
                                        <select value={filterType} onChange={e => setFilterType(e.target.value)}>
                                            <option value="">Все</option>
                                            <option value="today">На сегодня</option>
                                            <option value="overdue">Просроченные</option>
                                            <option value="planned">Запланированные</option>
                                            <option value="deadline_null">Без дедлайна</option>
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">Статус</label>
                                        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                                            <option value="">Все</option>
                                            <option value="backlog">Очередь</option>
                                            <option value="todo">Новые</option>
                                            <option value="in_progress">В работе</option>
                                            <option value="review">На проверке</option>
                                            <option value="done">Готово</option>
                                        </select>
                                    </div>
                                </div>
                            </div>
                        </aside>

                        <main className="main-column">
                            <div className="card">
                                <div className="section-header">
                                    <div>
                                        <div className="section-title">Новая задача</div>
                                        <div className="section-sub">Создайте задачу и назначьте исполнителя</div>
                                    </div>
                                </div>
                                <form className="form" onSubmit={handleCreateTask}>
                                    <div className="form-group">
                                        <label className="form-label">Заголовок *</label>
                                        <input value={form.title}
                                            onChange={e => setForm({ ...form, title: e.target.value })}
                                            placeholder="Например, проверить почту" required />
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">Описание</label>
                                        <textarea value={form.description}
                                            onChange={e => setForm({ ...form, description: e.target.value })}
                                            placeholder="Дополнительные детали (необязательно)" />
                                    </div>
                                    <div className="form-two-col">
                                        <div className="form-group">
                                            <label className="form-label">Дедлайн</label>
                                            <input type="datetime-local" value={form.deadline}
                                                onChange={e => setForm({ ...form, deadline: e.target.value })} />
                                        </div>
                                        <div className="form-group">
                                            <label className="form-label">Статус</label>
                                            <select value={form.status || "todo"}
                                                onChange={e => setForm({ ...form, status: e.target.value })}>
                                                {STATUS_LIST.map(s => (
                                                    <option key={s.key} value={s.key}>{s.icon} {s.label}</option>
                                                ))}
                                            </select>
                                        </div>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">Приоритет</label>
                                        <select value={form.priority || "medium"} onChange={e => setForm({ ...form, priority: e.target.value })}>
                                            <option value="low">⚪ Низкий</option>
                                            <option value="medium">🔵 Средний</option>
                                            <option value="high">🟠 Высокий</option>
                                            <option value="critical">🔴 Критический</option>
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">Повторение</label>
                                        <select value={form.recurrence_rule || "none"} onChange={e => setForm({ ...form, recurrence_rule: e.target.value })}>
                                            <option value="none">Не повторяется</option>
                                            <option value="daily">🔁 Каждый день</option>
                                            <option value="weekly">🔁 Каждую неделю</option>
                                            <option value="monthly">🔁 Каждый месяц</option>
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">Проект</label>
                                        <select value={form.project_id || ""} onChange={e => setForm({ ...form, project_id: e.target.value })}>
                                            <option value="">— Без проекта —</option>
                                            {appProjects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">Назначить</label>
                                        <select value={assignType} onChange={e => setAssignType(e.target.value)}>
                                            <option value="self">Себе</option>
                                            <option value="user">Пользователю</option>
                                            <option value="group">Группе</option>
                                            <option value="none">Никому</option>
                                        </select>
                                    </div>
                                    {assignType === "group" && (
                                        <div className="form-group">
                                            <label className="form-label">Группа</label>
                                            <select value={selectedGroupId} onChange={e => setSelectedGroupId(e.target.value)}>
                                                <option value="">Выберите группу</option>
                                                {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                                            </select>
                                        </div>
                                    )}
                                    {assignType === "user" && (
                                        <div className="form-group">
                                            <label className="form-label">Пользователь</label>
                                            <select value={selectedUserId} onChange={e => setSelectedUserId(e.target.value)}>
                                                <option value="">Выберите пользователя</option>
                                                {users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                                            </select>
                                        </div>
                                    )}
                                    {error && <div className="alert">{error}</div>}
                                    <button type="submit" className="btn btn-primary">
                                        <Icon d={ICONS.plus} /> Создать задачу
                                    </button>
                                </form>
                            </div>

                            <div className="card">
                                <div className="section-header">
                                    <div>
                                        <div className="section-title">Задачи</div>
                                        <div className="section-sub">
                                            {tasksTotal > 0
                                                ? `${tasksTotal} задач${searchQuery.trim() ? " (по запросу)" : ""} · стр. ${tasksPage}/${tasksTotalPages}`
                                                : "Нет задач"}
                                        </div>
                                    </div>
                                    <div style={{ display: "flex", gap: 8 }}>
                                        <button className="btn btn-ghost btn-sm" onClick={handleExportCsv} disabled={exporting}>
                                            📄 {exporting ? "Экспорт…" : "Экспорт в CSV"}
                                        </button>
                                        <input
                                            ref={importInputRef}
                                            type="file"
                                            accept=".csv,.xlsx"
                                            style={{ display: "none" }}
                                            onChange={handleImportFile}
                                        />
                                        <button
                                            className="btn btn-ghost btn-sm"
                                            onClick={() => importInputRef.current?.click()}
                                            disabled={importing}
                                        >
                                            📥 {importing ? "Импорт…" : "Импорт из CSV/Excel"}
                                        </button>
                                        <button className="btn btn-ghost btn-sm" onClick={() => loadTasks(tasksPage, viewMode)} disabled={loading}>
                                            <Icon d={ICONS.refresh} /> {loading ? "…" : "Обновить"}
                                        </button>
                                    </div>
                                </div>
                                <div className="form-two-col" style={{ marginBottom: 12 }}>
                                    <div className="form-group" style={{ marginBottom: 0 }}>
                                        <input
                                            type="text"
                                            value={searchQuery}
                                            onChange={e => setSearchQuery(e.target.value)}
                                            placeholder="Поиск по названию и описанию…"
                                        />
                                    </div>
                                    <div className="form-group" style={{ marginBottom: 0 }}>
                                        <select value={tagFilter} onChange={e => setTagFilter(e.target.value)}>
                                            <option value="">Все теги</option>
                                            {allTags.map(t => (
                                                <option key={t.id} value={t.id}>{t.name}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>

                                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginBottom: 12 }}>
                                    {filterPresets.map(preset => (
                                        <span key={preset.id} style={{
                                            display: "inline-flex", alignItems: "center", gap: 4,
                                            background: "var(--surface2)", border: "1px solid var(--border)",
                                            borderRadius: "var(--radius-sm)", overflow: "hidden",
                                        }}>
                                            <button
                                                className="btn btn-ghost btn-sm"
                                                style={{ border: "none" }}
                                                onClick={() => handleApplyPreset(preset)}
                                                title="Применить пресет"
                                            >
                                                {preset.name}
                                            </button>
                                            <button
                                                className="btn btn-ghost btn-sm"
                                                style={{ border: "none", padding: "4px 8px", color: "var(--red)" }}
                                                onClick={() => handleDeletePreset(preset.id)}
                                                title="Удалить пресет"
                                            >
                                                ×
                                            </button>
                                        </span>
                                    ))}

                                    <input
                                        type="text"
                                        value={presetNameInput}
                                        onChange={e => setPresetNameInput(e.target.value)}
                                        placeholder="Название пресета…"
                                        style={{ width: 160, padding: "6px 10px" }}
                                    />
                                    <button className="btn btn-ghost btn-sm" onClick={handleSavePreset} disabled={savingPreset}>
                                        💾 {savingPreset ? "Сохраняю…" : "Сохранить как пресет"}
                                    </button>
                                </div>

                                {loading ? (
                                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка задач…</div>
                                ) : tasks.length === 0 ? (
                                    <div className="empty-state">
                                        <div className="empty-icon">{searchQuery.trim() ? "🔍" : "📋"}</div>
                                        {searchQuery.trim() ? `Ничего не найдено по запросу «${searchQuery}»` : "Задач нет. Создайте первую!"}
                                    </div>
                                ) : (
                                    <>
                                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                                            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
                                                <input
                                                    type="checkbox"
                                                    checked={visibleTasks.length > 0 && visibleTasks.every(t => selectedTaskIds.has(t.id))}
                                                    onChange={toggleSelectAllVisible}
                                                />
                                                Выбрать все на странице
                                            </label>
                                        </div>

                                        {selectedTaskIds.size > 0 && (
                                            <div style={{
                                                display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8,
                                                padding: "10px 12px", marginBottom: 12,
                                                background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)",
                                            }}>
                                                <span style={{ fontWeight: 600, fontSize: 13 }}>Выбрано: {selectedTaskIds.size}</span>

                                                <select value={bulkStatus} onChange={e => setBulkStatus(e.target.value)} style={{ maxWidth: 140 }}>
                                                    <option value="">Статус…</option>
                                                    <option value="backlog">Бэклог</option>
                                                    <option value="todo">Todo</option>
                                                    <option value="in_progress">В работе</option>
                                                    <option value="review">Ревью</option>
                                                    <option value="done">Готово</option>
                                                </select>

                                                <select value={bulkPriority} onChange={e => setBulkPriority(e.target.value)} style={{ maxWidth: 140 }}>
                                                    <option value="">Приоритет…</option>
                                                    <option value="low">Низкий</option>
                                                    <option value="medium">Средний</option>
                                                    <option value="high">Высокий</option>
                                                    <option value="critical">Критический</option>
                                                </select>

                                                <select value={bulkTagId} onChange={e => setBulkTagId(e.target.value)} style={{ maxWidth: 140 }}>
                                                    <option value="">Тег…</option>
                                                    {allTags.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                                                </select>

                                                <select value={bulkUserId} onChange={e => setBulkUserId(e.target.value)} style={{ maxWidth: 160 }}>
                                                    <option value="">Исполнитель…</option>
                                                    {users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                                                </select>

                                                <button className="btn btn-primary btn-sm" onClick={handleBulkApply} disabled={bulkApplying}>
                                                    {bulkApplying ? "Применяю…" : "Применить"}
                                                </button>
                                                <button className="btn btn-ghost btn-sm" onClick={() => setSelectedTaskIds(new Set())} disabled={bulkApplying}>
                                                    Отменить выбор
                                                </button>
                                            </div>
                                        )}

                                        <div className="task-list">
                                            {visibleTasks.map(task => (
                                                <TaskCard key={task.id} task={task}
                                                    groups={groups} users={users} token={token}
                                                    allTags={allTags}
                                                    onTagsCreated={loadTags}
                                                    onTagsUpdated={handleTaskTagsUpdated}
                                                    onToggle={handleToggleTask}
                                                    onDelete={handleDeleteTask}
                                                    onUpdate={handleUpdateTask}
                                                    onReassign={handleReassignTask}
                                                    currentUserId={currentUserId}
                                                    currentRole={currentRole}
                                                    selected={selectedTaskIds.has(task.id)}
                                                    onToggleSelect={toggleTaskSelection} />
                                            ))}
                                        </div>
                                        <Pagination page={tasksPage} totalPages={tasksTotalPages}
                                            onPage={p => loadTasks(p, viewMode)} />
                                    </>
                                )}
                            </div>

                            {importSummary && (
                                <div style={{
                                    position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    zIndex: 1000, padding: 16,
                                }} onClick={e => { if (e.target === e.currentTarget) setImportSummary(null); }}>
                                    <div style={{
                                        background: "var(--bg-card)", border: "1px solid var(--border)",
                                        borderRadius: 16, padding: 24, width: "100%", maxWidth: 480,
                                    }}>
                                        <div style={{ fontWeight: 700, fontSize: 17, marginBottom: 12 }}>Импорт завершён</div>
                                        <div style={{ marginBottom: 16 }}>Создано задач: <b>{importSummary.created}</b></div>

                                        {importSummary.errors.length > 0 && (
                                            <div style={{ marginBottom: 16 }}>
                                                <div style={{ color: "var(--red)", fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                                                    Пропущено строк: {importSummary.errors.length}
                                                </div>
                                                <ul style={{ maxHeight: 140, overflowY: "auto", fontSize: 13, margin: 0, paddingLeft: 18 }}>
                                                    {importSummary.errors.map((e, i) => (
                                                        <li key={i}>Строка {e.row}: {e.message}</li>
                                                    ))}
                                                </ul>
                                            </div>
                                        )}

                                        {importSummary.warnings.length > 0 && (
                                            <div style={{ marginBottom: 16 }}>
                                                <div style={{ color: "var(--text-muted)", fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                                                    Предупреждения: {importSummary.warnings.length}
                                                </div>
                                                <ul style={{ maxHeight: 140, overflowY: "auto", fontSize: 13, margin: 0, paddingLeft: 18 }}>
                                                    {importSummary.warnings.map((w, i) => (
                                                        <li key={i}>Строка {w.row}: {w.message}</li>
                                                    ))}
                                                </ul>
                                            </div>
                                        )}

                                        <button className="btn btn-primary" style={{ width: "100%" }} onClick={() => setImportSummary(null)}>
                                            Закрыть
                                        </button>
                                    </div>
                                </div>
                            )}
                        </main>
                    </div>
                </div>
            )}
            {/* ── DASHBOARD TAB ── */}
            {tab === "dashboard" && (
                <div style={{ maxWidth: 720, margin: "0 auto", padding: "16px 16px 0" }}>
                    <DashboardTab
                        stats={dashStats}
                        loading={dashLoading}
                        username={currentUsername}
                        role={currentRole}
                        token={token}
                    />
                </div>
            )}
            {/* ── PROJECTS TAB ── */}
            {tab === "projects" && (
                <div>
                    <ProjectsTab token={token} canManage={canManage}
                        currentUserId={currentUserId} currentRole={currentRole} />
                </div>
            )}
            {/* ── KANBAN TAB ── */}
            {tab === "kanban" && (
                <div>
                    <KanbanTab token={token} />
                </div>
            )}
            {/* ── GROUPS TAB ── */}
            {tab === "groups" && (
                <div>
                    <GroupsTab token={token} currentRole={currentRole} />
                </div>
            )}
            {tab === "templates" && (
                <div>
                    <TemplatesTab token={token} />
                </div>
            )}
            {tab === "tokens" && (
                <div>
                    <TokensTab token={token} />
                </div>
            )}
            {/* ── TRASH TAB ── */}
            {tab === "trash" && (
                <div>
                    <div className="card" style={{ marginTop: 0 }}>
                        <div className="section-header">
                            <div>
                                <div className="section-title">Корзина</div>
                                <div className="section-sub">Мягко удалённые задачи — можно восстановить</div>
                            </div>
                            <button className="btn btn-ghost btn-sm" onClick={() => loadTrash(1)} disabled={loading}>
                                <Icon d={ICONS.refresh} /> Обновить
                            </button>
                        </div>
                        {loading ? (
                            <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                        ) : trashTasks.length === 0 ? (
                            <div className="empty-state"><div className="empty-icon">🗑️</div>Корзина пуста</div>
                        ) : (
                            <>
                                <div className="task-list">
                                    {trashTasks.map(task => (
                                        <TrashCard key={task.id} task={task}
                                            onRestore={handleRestoreTask} onHardDelete={handleHardDelete} />
                                    ))}
                                </div>
                                <Pagination page={trashPage} totalPages={trashTotalPages} onPage={p => loadTrash(p)} />
                            </>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

export default App;
