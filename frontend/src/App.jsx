import React, { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest } from "./api";

// ─── Helpers ──────────────────────────────────────────────
const initialForm = { title: "", description: "", deadline: "" };

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
                width: "14px",
                height: "14px",
                minWidth: "14px",
                minHeight: "14px",
                flexShrink: 0,
                display: "inline-block",
                verticalAlign: "middle",
                fill: "currentColor"
            }}
        >
            <path d={d} />
        </svg>
    );
}
const ICONS = {
    check: "M20 6L9 17l-5-5",
    x: "M18 6L6 18M6 6l12 12",
    edit: "M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z",
    trash: "M3 6h18M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2",
    restore: "M3 12a9 9 0 109-9 9 9 0 00-9 9M3 3v6h6",
    hardDel: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
    refresh: "M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15",
    plus: "M12 5v14M5 12h14",
    clock: "M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zM12 6v6l4 2",
    user: "M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2M12 11a4 4 0 100-8 4 4 0 000 8z",
    group: "M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75",
    save: "M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2zM17 21v-8H7v8M7 3v5h8",
    logout: "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9",
    filter: "M22 3H2l8 9.46V19l4 2v-8.54L22 3z",
    comment: "M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z",
    reassign: "M16 3h5v5M4 20L21 3M21 16v5h-5M15 15l6 6M4 4l5 5",
    chevronL: "M15 18l-6-6 6-6",
    chevronR: "M9 18l6-6-6-6",
    userPlus: "M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M12.5 7a4 4 0 100-8 4 4 0 000 8zM20 8v6M23 11h-6",
    userMinus: "M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M12.5 7a4 4 0 100-8 4 4 0 000 8zM23 11h-6",
    shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
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

// ─── TaskCard ─────────────────────────────────────────────
function TaskCard({ task, groups, users, token, onToggle, onDelete, onUpdate, onReassign }) {
    const [editing, setEditing] = useState(false);
    const [showComments, setShowComments] = useState(false);
    const [showReassign, setShowReassign] = useState(false);
    const [saving, setSaving] = useState(false);
    const [editForm, setEditForm] = useState({
        title: task.title, description: task.description || "",
        deadline: task.deadline ? task.deadline.slice(0, 16) : "",
    });
    const [reassignUserId, setReassignUserId] = useState("");
    const [reassignGroupId, setReassignGroupId] = useState("");
    const dl = formatDeadline(task.deadline);

    async function handleSave() {
        setSaving(true);
        await onUpdate(task, {
            title: editForm.title.trim(),
            description: editForm.description.trim() || null,
            deadline: editForm.deadline ? `${editForm.deadline}:00` : null,
        });
        setSaving(false); setEditing(false);
    }

    async function handleReassign() {
        await onReassign(task.id, reassignUserId || null, reassignGroupId || null);
        setShowReassign(false); setReassignUserId(""); setReassignGroupId("");
    }

    return (
        <article className={`task-card${task.is_done ? " done-card" : ""}`}>
            <div className="task-main-info"> {/* НОВЫЙ ИЗОЛИРУЮЩИЙ КОНТЕЙНЕР ДЛЯ ВЕРХНЕЙ ЧАСТИ */}
                <div className="task-top">
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="task-title">
                            <span className="task-id">#{task.id}</span>
                            {task.title}
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
                        </div>
                    </div>
                    <span className={`badge ${task.is_done ? "badge-done" : "badge-active"}`}>
                        {task.is_done ? "Готово" : "В работе"}
                    </span>
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
                <button className={`btn btn-sm ${task.is_done ? "btn-ghost" : "btn-success"}`} onClick={() => onToggle(task)}>
                    <Icon d={ICONS.check} /> {task.is_done ? "Снять отметку" : "Выполнено"}
                </button>
                {!editing && (
                    <button className="btn btn-ghost btn-sm" onClick={() => { setEditing(true); setShowReassign(false); }}>
                        <Icon d={ICONS.edit} /> Изменить
                    </button>
                )}
                <button className="btn btn-ghost btn-sm" onClick={() => { setShowReassign(v => !v); setEditing(false); }}>
                    <Icon d={ICONS.reassign} /> Переназначить
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => setShowComments(v => !v)}>
                    <Icon d={ICONS.comment} /> {showComments ? "Скрыть" : "Комментарии"}
                </button>
                <button className="btn btn-danger btn-sm" onClick={() => onDelete(task)}>
                    <Icon d={ICONS.trash} /> Удалить
                </button>
            </div>

            {showComments && <CommentsPanel taskId={task.id} token={token} />}
        </article>
    );
}

// ─── TrashCard ────────────────────────────────────────────
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
        setAdding(true); setError(null);
        try {
            await apiRequest({
                path: `/groups/${group.id}/users/${addUserId}`,
                method: "POST", token,
            });
            setAddUserId("");
            await load();
            onRefresh();
        } catch (err) { setError(err.message); }
        finally { setAdding(false); }
    }

    async function handleRemove(userId) {
        setError(null);
        try {
            await apiRequest({
                path: `/groups/${group.id}/users/${userId}`,
                method: "DELETE", token,
            });
            await load();
            onRefresh();
        } catch (err) { setError(err.message); }
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

// ─── Groups Tab ───────────────────────────────────────────
function GroupsTab({ token, currentRole }) {
    const [groups, setGroups] = useState([]);
    const [allUsers, setAllUsers] = useState([]);
    const [loading, setLoading] = useState(false);

    const canManage = currentRole === "admin" || currentRole === "manager";

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

// ─── Main App ─────────────────────────────────────────────
function App() {
    const [token, setToken] = useState(localStorage.getItem("spisoc_token"));
    const [theme, setTheme] = useState(() => localStorage.getItem("spisoc_theme") || "dark");
    const [tasks, setTasks] = useState([]);
    const [trashTasks, setTrash] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [tab, setTab] = useState("tasks"); // "tasks" | "groups" | "trash"

    const [filterType, setFilterType] = useState("");
    const [isDone, setIsDone] = useState("");
    const [viewMode, setViewMode] = useState("user"); // "user" | "author"

    const [tasksPage, setTasksPage] = useState(1);
    const [tasksTotal, setTasksTotal] = useState(0);
    const PAGE_SIZE = 50;

    const [trashPage, setTrashPage] = useState(1);
    const [trashTotal, setTrashTotal] = useState(0);

    const [groups, setGroups] = useState([]);
    const [users, setUsers] = useState([]);

    const [form, setForm] = useState(initialForm);
    const [assignType, setAssignType] = useState("self");
    const [selectedGroupId, setSelectedGroupId] = useState("");
    const [selectedUserId, setSelectedUserId] = useState("");
    const [taskDone, setTaskDone] = useState(false);

    const tokenPayload = useMemo(() => decodeToken(token), [token]);
    const currentUserId = useMemo(() => tokenPayload?.sub ? Number(tokenPayload.sub) : null, [tokenPayload]);
    const currentUsername = useMemo(() => tokenPayload?.username || tokenPayload?.sub || "Пользователь", [tokenPayload]);
    const currentRole = useMemo(() => tokenPayload?.role ?? "user", [tokenPayload]);

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
    const isDoneRef = React.useRef(isDone);
    const viewModeRef = React.useRef(viewMode);
    tokenRef.current = token;
    filterTypeRef.current = filterType;
    isDoneRef.current = isDone;
    viewModeRef.current = viewMode;

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
            if (isDoneRef.current) q.set("is_done", isDoneRef.current);
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

    const loadUsers = useCallback(async () => {
        try {
            const data = await apiRequest({ path: "/users?page=1&size=100", token: tokenRef.current });
            setUsers(extractItems(data));
        } catch { setUsers([]); }
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
            if (tab === "tasks") loadTasks(1);
            if (tab === "trash") loadTrash(1);
        } else {
            // Смена фильтров/вкладки — только задачи
            if (tab === "tasks") loadTasks(1);
            if (tab === "trash") loadTrash(1);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token, tab, filterType, isDone, viewMode]);

    // ── auth ─────────────────────────────────────────────
    function handleAuthError(err) {
        if (["401", "403", "invalid"].some(s => err.message?.includes(s))) logout();
        else setError(err.message);
    }

    function logout() {
        localStorage.removeItem("spisoc_token");
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
            localStorage.setItem("spisoc_token", resp.access_token);
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
                is_done: taskDone,
                deadline: form.deadline ? `${form.deadline}:00` : null,
            };
            if (assignType === "self") { payload.user_id = currentUserId; payload.group_id = null; }
            else if (assignType === "user") { payload.user_id = selectedUserId ? Number(selectedUserId) : null; payload.group_id = null; }
            else if (assignType === "group") { payload.group_id = selectedGroupId ? Number(selectedGroupId) : null; payload.user_id = null; }
            else { payload.user_id = null; payload.group_id = null; }

            await apiRequest({ path: "/tasks", method: "POST", token, body: payload });
            setForm(initialForm); setAssignType("self");
            setSelectedGroupId(""); setSelectedUserId(""); setTaskDone(false);
            await loadTasks(1);
        } catch (err) { handleAuthError(err); }
    }

    async function handleToggleTask(task) {
        try {
            await apiRequest({ path: `/tasks/${task.id}`, method: "PATCH", token, body: { is_done: !task.is_done } });
            await loadTasks(tasksPage);
        } catch (err) { handleAuthError(err); }
    }

    async function handleUpdateTask(task, updates) {
        try {
            await apiRequest({ path: `/tasks/${task.id}`, method: "PATCH", token, body: updates });
            await loadTasks(tasksPage);
        } catch (err) { handleAuthError(err); }
    }

    async function handleDeleteTask(task) {
        try {
            await apiRequest({ path: `/tasks/${task.id}`, method: "DELETE", token });
            await loadTasks(tasksPage);
        } catch (err) { handleAuthError(err); }
    }

    async function handleReassignTask(taskId, userId, groupId) {
        try {
            const q = new URLSearchParams();
            if (userId) q.set("user_id", userId);
            if (groupId) q.set("group_id", groupId);
            await apiRequest({ path: `/tasks/${taskId}/reassign?${q}`, method: "PATCH", token });
            await loadTasks(tasksPage);
        } catch (err) { handleAuthError(err); }
    }

    async function handleRestoreTask(taskId) {
        try {
            await apiRequest({ path: `/tasks/${taskId}/restore`, method: "PATCH", token });
            await loadTrash(trashPage);
        } catch (err) { handleAuthError(err); }
    }

    async function handleHardDelete(taskId) {
        if (!window.confirm("Удалить задачу навсегда? Это действие нельзя отменить.")) return;
        try {
            await apiRequest({ path: `/tasks/${taskId}/hard`, method: "DELETE", token });
            await loadTrash(trashPage);
        } catch (err) { handleAuthError(err); }
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
                    <div className="tab-bar">
                        <button className={`tab-btn${tab === "tasks" ? " active" : ""}`} onClick={() => setTab("tasks")}>
                            Задачи {tasksTotal > 0 && <span className="count-badge">{tasksTotal}</span>}
                        </button>
                        <button className={`tab-btn${tab === "groups" ? " active" : ""}`} onClick={() => setTab("groups")}>
                            <Icon d={ICONS.group} /> Группы
                        </button>
                        <button className={`tab-btn${tab === "trash" ? " active" : ""}`} onClick={() => setTab("trash")}>
                            <Icon d={ICONS.trash} /> Корзина
                            {trashTotal > 0 && <span className="count-badge">{trashTotal}</span>}
                        </button>
                    </div>
                    <div className="user-chip">
                        {currentUsername}
                        <span className="role-badge" style={{ color: roleColor.color, background: roleColor.bg, marginLeft: 4 }}>
                            {ROLE_LABELS[currentRole] ?? currentRole}
                        </span>
                    </div>
                    <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => setTheme(t => t === "dark" ? "light" : "dark")}
                        title="Переключить тему"
                        style={{ fontSize: "0.85rem" }}
                    >
                        {theme === "dark" ? "☀️" : "🌙"}
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={logout}>
                        <Icon d={ICONS.logout} /> Выйти
                    </button>
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
                                        <select value={isDone} onChange={e => setIsDone(e.target.value)}>
                                            <option value="">Все</option>
                                            <option value="false">Не выполненные</option>
                                            <option value="true">Выполненные</option>
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
                                            <select value={taskDone ? "done" : "new"}
                                                onChange={e => setTaskDone(e.target.value === "done")}>
                                                <option value="new">В работе</option>
                                                <option value="done">Выполнено</option>
                                            </select>
                                        </div>
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
                                                ? `${tasksTotal} задач · стр. ${tasksPage}/${tasksTotalPages}`
                                                : "Нет задач"}
                                        </div>
                                    </div>
                                    <button className="btn btn-ghost btn-sm" onClick={() => loadTasks(tasksPage, viewMode)} disabled={loading}>
                                        <Icon d={ICONS.refresh} /> {loading ? "…" : "Обновить"}
                                    </button>
                                </div>
                                {loading ? (
                                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка задач…</div>
                                ) : tasks.length === 0 ? (
                                    <div className="empty-state"><div className="empty-icon">📋</div>Задач нет. Создайте первую!</div>
                                ) : (
                                    <>
                                        <div className="task-list">
                                            {tasks.map(task => (
                                                <TaskCard key={task.id} task={task}
                                                    groups={groups} users={users} token={token}
                                                    onToggle={handleToggleTask}
                                                    onDelete={handleDeleteTask}
                                                    onUpdate={handleUpdateTask}
                                                    onReassign={handleReassignTask} />
                                            ))}
                                        </div>
                                        <Pagination page={tasksPage} totalPages={tasksTotalPages}
                                            onPage={p => loadTasks(p, viewMode)} />
                                    </>
                                )}
                            </div>
                        </main>
                    </div>
                </div>
            )}
            {/* ── GROUPS TAB ── */}
            {tab === "groups" && (
                <div>
                    <GroupsTab token={token} currentRole={currentRole} />
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
