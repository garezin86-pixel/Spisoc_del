import QRCode from "qrcode";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bar, BarChart, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
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
    link: "M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z",
    calendar: "M19 4h-1V2h-2v2H8V2H6v2H5c-1.11 0-1.99.9-1.99 2L3 20c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 16H5V9h14v11zM7 11h5v5H7z",
    folder: "M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z",
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

// ─── TimelineTab — глобальная лента активности ────────────────────────────
// Переиспользует бэкенд /analytics/activity (см. ActivityService) — тот же
// audit_log, что и AuditPanel по одной задаче, но по всем задачам/комментариям
// сразу, уже с готовыми человекочитаемыми лейблами полей с бэкенда.
function describeTimelineEvent(e) {
    const who = e.username || "Кто-то";
    if (e.entity_type === "comments") {
        if (e.action === "create") return `${who} прокомментировал(а) «${e.task_title}»`;
        if (e.action === "update") return `${who} отредактировал(а) комментарий к «${e.task_title}»`;
        if (e.action === "delete") return `${who} удалил(а) комментарий к «${e.task_title}»`;
        return `${who} · комментарий к «${e.task_title}»`;
    }
    if (e.action === "create") return `${who} создал(а) задачу «${e.task_title}»`;
    if (e.action === "delete") return `${who} удалил(а) задачу «${e.task_title}»`;
    if (e.action === "restore") return `${who} восстановил(а) задачу «${e.task_title}»`;
    if (e.action === "update") return `${who} изменил(а) задачу «${e.task_title}»`;
    return `${who} · «${e.task_title}»`;
}

// ─── UserProfilePage — карточка профиля: аватар, должность, статистика,
// задачи (через target_user_id) и активность (через Timeline/user_id) ─────
// Кэш ID пользователей без аватара — общий на всю сессию вкладки. Без него
// каждый отдельный <UserProfileAvatar> (например, десяток сообщений одного
// и того же человека в чате) заново бьёт по сети и получает 404.
const _knownNoAvatar = new Set();

function UserProfileAvatar({ userId, username, size = 72, version }) {
    const [broken, setBroken] = useState(() => _knownNoAvatar.has(userId));

    // После успешной загрузки нового аватара (см. handleAvatarPick) родитель
    // передаёт свежий version — сбрасываем broken и убираем из чёрного списка,
    // иначе картинка так и останется заглушкой с инициалами до перезагрузки страницы.
    useEffect(() => {
        if (version) {
            _knownNoAvatar.delete(userId);
            setBroken(false);
        }
    }, [version, userId]);

    const initials = (username || "?").trim().split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase()).join("") || "?";

    if (broken || !userId) {
        return (
            <div style={{
                width: size, height: size, borderRadius: "50%", flexShrink: 0,
                background: "var(--accent)", color: "#fff", display: "flex",
                alignItems: "center", justifyContent: "center",
                fontSize: size * 0.36, fontWeight: 700,
            }}>
                {initials}
            </div>
        );
    }
    return (
        <img
            src={`${API_BASE}/users/${userId}/avatar${version ? `?v=${version}` : ""}`}
            alt={username}
            onError={() => { _knownNoAvatar.add(userId); setBroken(true); }}
            style={{ width: size, height: size, borderRadius: "50%", objectFit: "cover", flexShrink: 0, background: "var(--surface2)" }}
        />
    );
}

function UserProfilePage({ userId, token, currentUserId, onClose, onOpenTask }) {
    const isOwn = userId === currentUserId;
    const [user, setUser] = useState(null);
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [section, setSection] = useState("tasks"); // "tasks" | "activity"
    const [editingPosition, setEditingPosition] = useState(false);
    const [positionDraft, setPositionDraft] = useState("");
    const [savingPosition, setSavingPosition] = useState(false);
    const [avatarUploading, setAvatarUploading] = useState(false);
    const fileInputRef = useRef(null);

    const [tasksState, setTasksState] = useState({ items: [], total: 0, loading: true });
    const [taskFilterGroup, setTaskFilterGroup] = useState("user"); // "user" | "author"

    const [feedState, setFeedState] = useState({ items: [], total: 0, loading: true, page: 1 });

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const [userResp, statsResp] = await Promise.all([
                apiRequest({ path: `/users/${userId}`, token }),
                apiRequest({ path: `/users/${userId}/stats`, token }),
            ]);
            setUser(userResp);
            setStats(statsResp);
            setPositionDraft(userResp?.position || "");
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [userId, token]);

    useEffect(() => { load(); }, [load]);

    const loadTasks = useCallback(async (group) => {
        setTasksState(s => ({ ...s, loading: true }));
        try {
            const params = new URLSearchParams({
                filter_user_group: group, target_user_id: String(userId), page: "1", size: "10",
            });
            const data = await apiRequest({ path: `/tasks/filter?${params.toString()}`, token });
            setTasksState({ items: Array.isArray(data?.items) ? data.items : [], total: data?.total || 0, loading: false });
        } catch {
            setTasksState({ items: [], total: 0, loading: false });
        }
    }, [userId, token]);

    useEffect(() => { if (section === "tasks") loadTasks(taskFilterGroup); }, [section, taskFilterGroup, loadTasks]);

    const loadFeed = useCallback(async (page = 1) => {
        setFeedState(s => ({ ...s, loading: true }));
        try {
            const params = new URLSearchParams({ user_id: String(userId), page: String(page), size: "20" });
            const data = await apiRequest({ path: `/analytics/activity?${params.toString()}`, token });
            setFeedState({ items: Array.isArray(data?.items) ? data.items : [], total: data?.total || 0, loading: false, page });
        } catch {
            setFeedState({ items: [], total: 0, loading: false, page });
        }
    }, [userId, token]);

    useEffect(() => { if (section === "activity") loadFeed(1); }, [section, loadFeed]);

    async function savePosition() {
        setSavingPosition(true);
        try {
            const updated = await apiRequest({
                path: `/users/${userId}`, token, method: "PATCH",
                body: { position: positionDraft.trim() || null },
            });
            setUser(updated);
            setEditingPosition(false);
        } catch (err) {
            alert(err.message);
        } finally {
            setSavingPosition(false);
        }
    }

    async function handleAvatarPick(e) {
        const file = e.target.files?.[0];
        e.target.value = "";
        if (!file) return;
        setAvatarUploading(true);
        try {
            const form = new FormData();
            form.append("file", file);
            await fetch(`${API_BASE}/users/me/avatar`, {
                method: "POST",
                headers: { Authorization: `Bearer ${token}` },
                body: form,
            });
            // Форсим перезагрузку картинки — меняем query-параметр, чтобы обойти кэш браузера
            setUser(u => ({ ...u, _avatarBust: Date.now() }));
        } catch (err) {
            alert("Не удалось загрузить аватар: " + err.message);
        } finally {
            setAvatarUploading(false);
        }
    }

    if (loading) return <div className="card"><div className="empty-state"><div className="empty-icon">⏳</div>Загрузка профиля…</div></div>;
    if (error || !user) return <div className="card"><div className="alert">{error || "Пользователь не найден"}</div></div>;

    const roleColor = ROLE_COLORS[user.role] ?? ROLE_COLORS.user;
    const completionPercent = stats?.total ? Math.round((stats.done / stats.total) * 100) : 0;

    return (
        <div style={{ maxWidth: 820, margin: "0 auto", padding: "16px 16px 0", display: "flex", flexDirection: "column", gap: 16 }}>
            <button className="btn btn-ghost btn-sm" onClick={onClose} style={{ alignSelf: "flex-start" }}>
                ← Назад
            </button>

            <div className="card" style={{ display: "flex", gap: 20, alignItems: "flex-start", flexWrap: "wrap" }}>
                <div style={{ position: "relative" }}>
                    <UserProfileAvatar userId={user.id} username={user.username} size={80} version={user._avatarBust} />
                    {isOwn && (
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => fileInputRef.current?.click()}
                            disabled={avatarUploading}
                            title="Сменить фото"
                            style={{
                                position: "absolute", bottom: -4, right: -4, borderRadius: "50%",
                                width: 28, height: 28, padding: 0, display: "flex", alignItems: "center", justifyContent: "center",
                            }}
                        >
                            {avatarUploading ? "…" : "✎"}
                        </button>
                    )}
                    {isOwn && <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={handleAvatarPick} />}
                </div>

                <div style={{ flex: 1, minWidth: 200 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <div style={{ fontSize: 20, fontWeight: 700 }}>{user.username}</div>
                        <span className="role-badge" style={{ color: roleColor.color, background: roleColor.bg }}>
                            {ROLE_LABELS[user.role] ?? user.role}
                        </span>
                    </div>

                    {editingPosition ? (
                        <div style={{ display: "flex", gap: 6, marginTop: 8, maxWidth: 320 }}>
                            <input className="input" style={{ marginBottom: 0 }} value={positionDraft}
                                placeholder="Должность"
                                onChange={e => setPositionDraft(e.target.value)}
                                onKeyDown={e => e.key === "Enter" && savePosition()} autoFocus />
                            <button className="btn btn-primary btn-sm" onClick={savePosition} disabled={savingPosition}>✓</button>
                            <button className="btn btn-ghost btn-sm" onClick={() => { setEditingPosition(false); setPositionDraft(user.position || ""); }}>✕</button>
                        </div>
                    ) : (
                        <div style={{ marginTop: 6, color: "var(--text-muted)", fontSize: 14, display: "flex", alignItems: "center", gap: 8 }}>
                            {user.position || (isOwn ? "Должность не указана" : "")}
                            {isOwn && (
                                <button className="btn btn-ghost btn-sm" onClick={() => setEditingPosition(true)} style={{ fontSize: 12 }}>
                                    {user.position ? "изменить" : "добавить"}
                                </button>
                            )}
                        </div>
                    )}

                    {stats && (
                        <div style={{ display: "flex", gap: 20, marginTop: 14, flexWrap: "wrap" }}>
                            <div>
                                <div style={{ fontSize: 22, fontWeight: 700 }}>{stats.total}</div>
                                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>задач назначено</div>
                            </div>
                            <div>
                                <div style={{ fontSize: 22, fontWeight: 700, color: "var(--green)" }}>{stats.done}</div>
                                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>готово</div>
                            </div>
                            <div>
                                <div style={{ fontSize: 22, fontWeight: 700 }}>{completionPercent}%</div>
                                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>выполнено</div>
                            </div>
                        </div>
                    )}
                </div>

                {stats && stats.total > 0 && (
                    <div style={{ width: 180, flexShrink: 0 }}>
                        <StatsDonut total={stats.total} done={stats.done} pending={stats.pending} />
                    </div>
                )}
            </div>

            <div className="tab-bar" style={{ display: "inline-flex" }}>
                <button className={`tab-btn${section === "tasks" ? " active" : ""}`} onClick={() => setSection("tasks")}>
                    <Icon d={ICONS.chart} /> Задачи
                </button>
                <button className={`tab-btn${section === "activity" ? " active" : ""}`} onClick={() => setSection("activity")}>
                    <Icon d={ICONS.clock} /> Активность
                </button>
            </div>

            {section === "tasks" && (
                <div className="card">
                    <div className="section-header">
                        <div className="section-title">Задачи</div>
                        <div style={{ display: "flex", gap: 6 }}>
                            <button className={`btn btn-sm ${taskFilterGroup === "user" ? "btn-primary" : "btn-ghost"}`} onClick={() => setTaskFilterGroup("user")}>Назначены</button>
                            <button className={`btn btn-sm ${taskFilterGroup === "author" ? "btn-primary" : "btn-ghost"}`} onClick={() => setTaskFilterGroup("author")}>Созданы</button>
                        </div>
                    </div>
                    {tasksState.loading ? (
                        <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                    ) : tasksState.items.length === 0 ? (
                        <div className="empty-state"><div className="empty-icon">📋</div>Нет задач</div>
                    ) : (
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                            {tasksState.items.map(t => (
                                <div key={t.id}
                                    onClick={() => onOpenTask && onOpenTask(t.title)}
                                    style={{
                                        display: "flex", justifyContent: "space-between", alignItems: "center",
                                        padding: "8px 12px", borderRadius: 8, background: "var(--surface2)", cursor: "pointer",
                                    }}>
                                    <span style={{ fontSize: 13 }}>{t.title}</span>
                                    <span className="meta-chip">{CMDK_TASK_STATUS_LABELS[t.status] ?? t.status}</span>
                                </div>
                            ))}
                            {tasksState.total > tasksState.items.length && (
                                <div style={{ fontSize: 12, color: "var(--text-muted)", textAlign: "center", marginTop: 4 }}>
                                    ещё {tasksState.total - tasksState.items.length} — полный список во вкладке «Задачи»
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {section === "activity" && (
                <div className="card" style={{ marginTop: 0 }}>
                    <div className="section-title" style={{ marginBottom: 10 }}>Лента активности</div>
                    {feedState.loading ? (
                        <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                    ) : feedState.items.length === 0 ? (
                        <div className="empty-state"><div className="empty-icon">🕒</div>Пока пусто</div>
                    ) : (
                        <>
                            <div className="comment-list">
                                {feedState.items.map(e => (
                                    <div key={`${e.entity_type}-${e.id}`} className="comment-item">
                                        <div className="comment-meta">
                                            <span className="comment-author">
                                                {AUDIT_ACTION_ICONS[e.action] || "📝"} {describeTimelineEvent(e)}
                                            </span>
                                            <span className="comment-date">{new Date(e.changed_at).toLocaleString("ru-RU")}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                            <Pagination page={feedState.page} totalPages={Math.max(1, Math.ceil(feedState.total / 20))} onPage={p => loadFeed(p)} />
                        </>
                    )}
                </div>
            )}
        </div>
    );
}

// ─── ChatPanel — переиспользуемое тело чата (список сообщений + инпут).
// Используется внутри всплывающего окна ChatBubble. Каналы: "Общий чат"
// (group_id=null) и по одному на каждую группу, в которой состоит юзер.
function ChatPanel({ token, currentUserId, channels, activeChannel, setActiveChannel, wsEvent, onClose }) {
    const [messages, setMessages] = useState([]);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [hasMore, setHasMore] = useState(true);
    const [draft, setDraft] = useState("");
    const [sending, setSending] = useState(false);
    const [error, setError] = useState(null);
    const listRef = useRef(null);
    const shouldStickToBottom = useRef(true);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = new URLSearchParams({ limit: "50" });
            if (activeChannel != null) params.set("group_id", activeChannel);
            const data = await apiRequest({ path: `/chat/messages?${params.toString()}`, token });
            const items = Array.isArray(data) ? data : [];
            setMessages(items);
            setHasMore(items.length === 50);
            shouldStickToBottom.current = true;
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [token, activeChannel]);

    useEffect(() => { load(); }, [load]);

    useEffect(() => {
        if (shouldStickToBottom.current && listRef.current) {
            listRef.current.scrollTop = listRef.current.scrollHeight;
        }
    }, [messages]);

    function onScroll() {
        const el = listRef.current;
        if (!el) return;
        shouldStickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    }

    async function loadMore() {
        if (!messages.length || loadingMore) return;
        setLoadingMore(true);
        try {
            const el = listRef.current;
            const prevHeight = el?.scrollHeight || 0;
            const params = new URLSearchParams({ limit: "50", before_id: String(messages[0].id) });
            if (activeChannel != null) params.set("group_id", activeChannel);
            const data = await apiRequest({ path: `/chat/messages?${params.toString()}`, token });
            const older = Array.isArray(data) ? data : [];
            setHasMore(older.length === 50);
            setMessages(prev => [...older, ...prev]);
            requestAnimationFrame(() => {
                if (el) el.scrollTop = el.scrollHeight - prevHeight;
            });
        } catch {
            // не критично — просто не подгрузили
        } finally {
            setLoadingMore(false);
        }
    }

    // Живые обновления: событие приходит для ЛЮБОГО канала — фильтруем по
    // текущему активному, чтобы сообщения из чужого канала сюда не попадали.
    useEffect(() => {
        if (!wsEvent) return;
        const { event, data } = wsEvent;
        const eventChannel = data?.group_id ?? null;
        if (eventChannel !== (activeChannel ?? null)) return;
        if (event === "chat_message") {
            setMessages(prev => (prev.some(m => m.id === data.id) ? prev : [...prev, data]));
        } else if (event === "chat_message_deleted") {
            setMessages(prev => prev.filter(m => m.id !== data.id));
        }
    }, [wsEvent, activeChannel]);

    // Подстраховка на случай проблем с доставкой WS (например, если сокет
    // незаметно отвалился): пока попап открыт, раз в 5 сек тихо подтягиваем
    // самые свежие сообщения канала и домешиваем недостающие (дедуп по id,
    // как и в WS-обработчике выше) — без сброса скролла и без "моргания".
    useEffect(() => {
        const interval = setInterval(async () => {
            try {
                const params = new URLSearchParams({ limit: "50" });
                if (activeChannel != null) params.set("group_id", activeChannel);
                const data = await apiRequest({ path: `/chat/messages?${params.toString()}`, token });
                if (!Array.isArray(data) || data.length === 0) return;
                setMessages(prev => {
                    const known = new Set(prev.map(m => m.id));
                    const fresh = data.filter(m => !known.has(m.id));
                    if (fresh.length === 0) return prev;
                    return [...prev, ...fresh].sort((a, b) => a.id - b.id);
                });
            } catch {
                // тихо игнорируем — это просто подстраховка, не основной путь
            }
        }, 5000);
        return () => clearInterval(interval);
    }, [token, activeChannel]);

    async function send() {
        const content = draft.trim();
        if (!content || sending) return;
        setSending(true);
        setDraft("");
        try {
            const saved = await apiRequest({
                path: "/chat/messages", token, method: "POST",
                body: { content, group_id: activeChannel },
            });
            shouldStickToBottom.current = true;
            // Добавляем сразу из ответа POST, не дожидаясь WS — надёжнее, чем
            // полагаться только на broadcast (задержки/потеря сети и т.п.).
            // Если следом всё же прилетит WS-событие на то же сообщение —
            // дедуп по id (см. эффект ниже) не даст задвоить.
            if (saved?.id) {
                setMessages(prev => (prev.some(m => m.id === saved.id) ? prev : [...prev, saved]));
            }
        } catch (err) {
            setError(err.message);
            setDraft(content);
        } finally {
            setSending(false);
        }
    }

    async function handleDelete(id) {
        try {
            await apiRequest({ path: `/chat/messages/${id}`, token, method: "DELETE" });
            setMessages(prev => prev.filter(m => m.id !== id));
        } catch (err) {
            alert(err.message);
        }
    }

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 12px", borderBottom: "1px solid var(--border)" }}>
                <div style={{ display: "flex", gap: 4, overflowX: "auto", flex: 1, minWidth: 0 }}>
                    {channels.map(c => (
                        <button
                            key={c.group_id ?? "general"}
                            className={`tab-btn${(activeChannel ?? null) === (c.group_id ?? null) ? " active" : ""}`}
                            style={{ fontSize: 12, padding: "4px 10px", flexShrink: 0, whiteSpace: "nowrap" }}
                            onClick={() => setActiveChannel(c.group_id)}
                        >
                            {c.group_id == null ? "💬" : "👥"} {c.name}
                        </button>
                    ))}
                </div>
                {onClose && (
                    <button className="btn btn-ghost btn-sm" onClick={onClose} style={{ flexShrink: 0 }}>✕</button>
                )}
            </div>

            <div ref={listRef} onScroll={onScroll} style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 10, padding: "10px 12px" }}>
                {loading ? (
                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                ) : messages.length === 0 ? (
                    <div className="empty-state"><div className="empty-icon">💬</div>Пока никто ничего не написал</div>
                ) : (
                    <>
                        {hasMore && (
                            <button className="btn btn-ghost btn-sm" onClick={loadMore} disabled={loadingMore}
                                style={{ alignSelf: "center", marginBottom: 6 }}>
                                {loadingMore ? "Загрузка…" : "Загрузить более раннюю историю"}
                            </button>
                        )}
                        {messages.map(m => {
                            const isOwn = m.user_id === currentUserId;
                            return (
                                <div key={m.id} style={{ display: "flex", gap: 8, alignItems: "flex-start", flexDirection: isOwn ? "row-reverse" : "row" }}>
                                    <div style={{ cursor: "pointer" }} onClick={() => window.openUserProfile?.(m.user_id)}>
                                        <UserProfileAvatar userId={m.user_id} username={m.username} size={28} />
                                    </div>
                                    <div style={{ maxWidth: "72%" }}>
                                        <div style={{ display: "flex", gap: 6, alignItems: "baseline", flexDirection: isOwn ? "row-reverse" : "row" }}>
                                            <span
                                                style={{ fontSize: 12, fontWeight: 600, cursor: "pointer" }}
                                                onClick={() => window.openUserProfile?.(m.user_id)}
                                            >
                                                {m.username}
                                            </span>
                                            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                                                {new Date(m.created_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}
                                            </span>
                                        </div>
                                        <div style={{
                                            marginTop: 3, padding: "7px 11px", borderRadius: 12,
                                            background: isOwn ? "var(--accent)" : "var(--surface2)",
                                            color: isOwn ? "#fff" : "var(--text)",
                                            fontSize: 13, whiteSpace: "pre-wrap", wordBreak: "break-word",
                                        }}>
                                            {m.content}
                                        </div>
                                        {isOwn && (
                                            <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(m.id)}
                                                style={{ fontSize: 11, padding: "2px 6px", marginTop: 2, color: "var(--text-muted)" }}>
                                                удалить
                                            </button>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </>
                )}
            </div>

            {error && <div className="alert" style={{ margin: "0 12px 8px" }}>{error}</div>}

            <div style={{ display: "flex", gap: 8, padding: "10px 12px", borderTop: "1px solid var(--border)" }}>
                <input
                    className="input"
                    placeholder="Написать сообщение…"
                    value={draft}
                    onChange={e => setDraft(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                    style={{ marginBottom: 0, flex: 1 }}
                />
                <button className="btn btn-primary" onClick={send} disabled={sending || !draft.trim()}>
                    ➤
                </button>
            </div>
        </div>
    );
}

// ─── ChatBubble — плавающий перетаскиваемый кружок в углу экрана. Клик (не
// перетаскивание) открывает всплывающее окно с ChatPanel. Позиция и
// последний открытый канал запоминаются в localStorage. ───────────────────
function ChatBubble({ token, currentUserId, wsEvent }) {
    const [open, setOpen] = useState(false);
    const [pos, setPos] = useState(() => {
        try {
            const saved = JSON.parse(localStorage.getItem("spisoc_chat_bubble_pos") || "null");
            if (saved && typeof saved.x === "number" && typeof saved.y === "number") return saved;
        } catch { /* ignore */ }
        return { x: window.innerWidth - 76, y: window.innerHeight - 96 };
    });
    const [channels, setChannels] = useState([{ group_id: null, name: "Общий чат" }]);
    const [activeChannel, setActiveChannel] = useState(null);
    const [unread, setUnread] = useState(0);

    const draggingRef = useRef(false);
    const movedRef = useRef(false);
    const dragStartRef = useRef({ x: 0, y: 0, posX: 0, posY: 0 });
    const bubbleRef = useRef(null);
    const openRef = useRef(open);
    openRef.current = open;
    const activeChannelRef = useRef(activeChannel);
    activeChannelRef.current = activeChannel;

    useEffect(() => {
        apiRequest({ path: "/chat/channels", token }).then(data => {
            if (Array.isArray(data) && data.length) setChannels(data);
        }).catch(() => { /* тихо игнорируем — останется хотя бы общий канал */ });
    }, [token]);

    useEffect(() => {
        try { localStorage.setItem("spisoc_chat_bubble_pos", JSON.stringify(pos)); } catch { /* ignore */ }
    }, [pos]);

    // Бейдж непрочитанных — считаем только пока попап закрыт и только чужие сообщения.
    useEffect(() => {
        if (!wsEvent || wsEvent.event !== "chat_message") return;
        if (wsEvent.data?.user_id === currentUserId) return;
        if (openRef.current && (wsEvent.data?.group_id ?? null) === (activeChannelRef.current ?? null)) return;
        setUnread(u => u + 1);
    }, [wsEvent, currentUserId]);

    function clampPos(x, y) {
        return {
            x: Math.min(Math.max(8, x), window.innerWidth - 64),
            y: Math.min(Math.max(8, y), window.innerHeight - 64),
        };
    }

    function onPointerDown(e) {
        draggingRef.current = true;
        movedRef.current = false;
        dragStartRef.current = { x: e.clientX, y: e.clientY, posX: pos.x, posY: pos.y };
        bubbleRef.current?.setPointerCapture?.(e.pointerId);
    }
    function onPointerMove(e) {
        if (!draggingRef.current) return;
        const dx = e.clientX - dragStartRef.current.x;
        const dy = e.clientY - dragStartRef.current.y;
        if (Math.abs(dx) > 4 || Math.abs(dy) > 4) movedRef.current = true;
        setPos(clampPos(dragStartRef.current.posX + dx, dragStartRef.current.posY + dy));
    }
    function onPointerUp() {
        draggingRef.current = false;
        if (!movedRef.current) {
            setOpen(o => {
                const next = !o;
                if (next) setUnread(0);
                return next;
            });
        }
    }

    const openLeft = pos.x > window.innerWidth / 2;
    const openTop = pos.y > window.innerHeight / 2;
    const popupStyle = {
        position: "fixed",
        ...(openLeft ? { right: window.innerWidth - pos.x + 16 } : { left: pos.x }),
        ...(openTop ? { bottom: window.innerHeight - pos.y + 16 } : { top: pos.y + 60 }),
    };

    return (
        <>
            <div
                ref={bubbleRef}
                className="chat-bubble"
                style={{ left: pos.x, top: pos.y }}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                title="Командный чат"
            >
                💬
                {unread > 0 && <span className="notif-badge">{unread > 99 ? "99+" : unread}</span>}
            </div>
            {open && (
                <div className="chat-popup" style={popupStyle}>
                    <ChatPanel
                        token={token}
                        currentUserId={currentUserId}
                        channels={channels}
                        activeChannel={activeChannel}
                        setActiveChannel={setActiveChannel}
                        wsEvent={wsEvent}
                        onClose={() => setOpen(false)}
                    />
                </div>
            )}
        </>
    );
}


function TimelineTab({ token }) {
    const [entries, setEntries] = useState([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const PAGE_SIZE = 30;

    const load = useCallback(async (p = 1) => {
        setLoading(true);
        setError(null);
        try {
            const data = await apiRequest({ path: `/analytics/activity?page=${p}&size=${PAGE_SIZE}`, token });
            setEntries(Array.isArray(data?.items) ? data.items : []);
            setTotal(data?.total || 0);
            setPage(p);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => { load(1); }, [load]);

    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

    return (
        <div className="card" style={{ marginTop: 0 }}>
            <div className="section-header">
                <div>
                    <div className="section-title">🕒 Лента активности</div>
                    <div className="section-sub">Последние изменения задач и комментариев — все пользователи</div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={() => load(page)} disabled={loading}>
                    <Icon d={ICONS.refresh} /> Обновить
                </button>
            </div>
            {error && <div className="alert">{error}</div>}
            {loading ? (
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
            ) : entries.length === 0 ? (
                <div className="empty-state"><div className="empty-icon">🕒</div>Пока ничего не происходило</div>
            ) : (
                <>
                    <div className="comment-list">
                        {entries.map(e => (
                            <div key={`${e.entity_type}-${e.id}`} className="comment-item">
                                <div className="comment-meta">
                                    <span className="comment-author">
                                        {AUDIT_ACTION_ICONS[e.action] || "📝"} {describeTimelineEvent(e)}
                                    </span>
                                    <span className="comment-date">
                                        {new Date(e.changed_at).toLocaleString("ru-RU")}
                                    </span>
                                </div>
                                {e.entity_type === "comments" && e.action === "create" && e.comment_preview && (
                                    <div style={{ marginTop: 4, fontSize: 13, color: "var(--text-muted)" }}>
                                        «{e.comment_preview}»
                                    </div>
                                )}
                                {e.changes && e.changes.length > 0 && (
                                    <div style={{ marginTop: 4, display: "flex", flexDirection: "column", gap: 2 }}>
                                        {e.changes.map(c => (
                                            <div key={c.field} style={{ fontSize: 12, color: "var(--text-muted)" }}>
                                                <span style={{ color: "var(--text-dim)" }}>{c.label}:</span>{" "}
                                                <span style={{ textDecoration: "line-through", marginRight: 4 }}>
                                                    {c.old}
                                                </span>
                                                <span style={{ color: "var(--accent-light)" }}>{c.new}</span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                    <Pagination page={page} totalPages={totalPages} onPage={p => load(p)} />
                </>
            )}
        </div>
    );
}

// ─── NotificationBell — колокольчик уведомлений в шапке ───────────────────
function NotificationBell({ token, onOpenTask }) {
    const [open, setOpen] = useState(false);
    const [items, setItems] = useState([]);
    const [unread, setUnread] = useState(0);
    const [loading, setLoading] = useState(false);
    const wrapRef = useRef(null);

    const loadUnread = useCallback(async () => {
        try {
            const data = await apiRequest({ path: "/notifications/unread-count", token });
            setUnread(data?.count || 0);
        } catch {
            // тихо игнорируем — бейдж не критичен для остального приложения
        }
    }, [token]);

    useEffect(() => {
        loadUnread();
        const id = setInterval(loadUnread, 30000);
        return () => clearInterval(id);
    }, [loadUnread]);

    useEffect(() => {
        function onClickOutside(e) {
            if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
        }
        document.addEventListener("mousedown", onClickOutside);
        return () => document.removeEventListener("mousedown", onClickOutside);
    }, []);

    async function loadList() {
        setLoading(true);
        try {
            const data = await apiRequest({ path: "/notifications?page=1&size=10", token });
            setItems(Array.isArray(data?.items) ? data.items : []);
        } catch {
            setItems([]);
        } finally {
            setLoading(false);
        }
    }

    async function toggle() {
        const next = !open;
        setOpen(next);
        if (next) await loadList();
    }

    async function handleItemClick(item) {
        if (!item.is_read) {
            try {
                await apiRequest({ path: `/notifications/${item.id}/read`, token, method: "POST" });
                setItems(prev => prev.map(i => (i.id === item.id ? { ...i, is_read: true } : i)));
                setUnread(u => Math.max(0, u - 1));
            } catch {
                // не критично — просто оставим как есть
            }
        }
        setOpen(false);
        if (item.task_title && onOpenTask) onOpenTask(item.task_title);
    }

    async function markAllRead() {
        try {
            await apiRequest({ path: "/notifications/read-all", token, method: "POST" });
            setItems(prev => prev.map(i => ({ ...i, is_read: true })));
            setUnread(0);
        } catch {
            // не критично
        }
    }

    return (
        <div className="notif-bell-wrap" ref={wrapRef}>
            <button className="btn btn-ghost btn-sm" onClick={toggle} title="Уведомления">
                🔔
                {unread > 0 && <span className="notif-badge">{unread > 99 ? "99+" : unread}</span>}
            </button>
            {open && (
                <div className="notif-dropdown">
                    <div className="notif-dropdown-header">
                        <span>Уведомления</span>
                        {unread > 0 && <button onClick={markAllRead}>Отметить всё прочитанным</button>}
                    </div>
                    {loading ? (
                        <div className="empty-state" style={{ padding: 16 }}>Загрузка…</div>
                    ) : items.length === 0 ? (
                        <div className="empty-state" style={{ padding: 16 }}>Пока пусто</div>
                    ) : (
                        <div className="notif-list">
                            {items.map(item => (
                                <div
                                    key={item.id}
                                    className={`notif-item${item.is_read ? "" : " unread"}`}
                                    onClick={() => handleItemClick(item)}
                                >
                                    <div className="notif-content">{item.content}</div>
                                    {item.task_title && <div className="notif-task">📋 {item.task_title}</div>}
                                    <div className="notif-date">{new Date(item.sent_at).toLocaleString("ru-RU")}</div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

// ─── CommandPalette — Ctrl/Cmd+K: команды навигации + поиск по задачам ────
const COMMAND_LIST = [
    { id: "nav-dashboard", label: "Перейти: Дашборд", icon: "📊", tab: "dashboard" },
    { id: "nav-timeline", label: "Перейти: Лента активности", icon: "🕒", tab: "timeline" },
    { id: "nav-tasks", label: "Перейти: Задачи", icon: "📋", tab: "tasks" },
    { id: "nav-projects", label: "Перейти: Проекты", icon: "📁", tab: "projects" },
    { id: "nav-kanban", label: "Перейти: Канбан", icon: "🗂️", tab: "kanban" },
    { id: "nav-templates", label: "Перейти: Шаблоны", icon: "📄", tab: "templates" },
    { id: "nav-groups", label: "Перейти: Группы", icon: "👥", tab: "groups" },
    { id: "nav-trash", label: "Перейти: Корзина", icon: "🗑️", tab: "trash" },
    { id: "nav-settings-profile", label: "Настройки: Профиль и 2FA", icon: "🔒", tab: "2fa" },
    { id: "nav-settings-tokens", label: "Настройки: Токены", icon: "🔑", tab: "tokens" },
    { id: "nav-settings-webhooks", label: "Настройки: Вебхуки", icon: "🔗", tab: "webhooks" },
    { id: "nav-settings-calendar", label: "Настройки: Календарь", icon: "📅", tab: "calendar" },
    { id: "new-task", label: "Создать задачу", icon: "➕", tab: "tasks" },
    { id: "toggle-theme", label: "Переключить тему", icon: "🌓" },
    { id: "logout", label: "Выйти из аккаунта", icon: "🚪" },
];

const CMDK_TASK_STATUS_LABELS = { backlog: "Очередь", todo: "Новые", in_progress: "В работе", review: "На проверке", done: "Готово" };

function CommandPalette({ open, onClose, token, setTab, setSearchQuery, setTheme, onLogout }) {
    const [query, setQuery] = useState("");
    const [taskResults, setTaskResults] = useState([]);
    const [taskLoading, setTaskLoading] = useState(false);
    const [activeIndex, setActiveIndex] = useState(0);
    const inputRef = useRef(null);

    useEffect(() => {
        if (open) {
            setQuery("");
            setTaskResults([]);
            setActiveIndex(0);
            setTimeout(() => inputRef.current?.focus(), 0);
        }
    }, [open]);

    const filteredCommands = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return COMMAND_LIST;
        return COMMAND_LIST.filter(c => c.label.toLowerCase().includes(q));
    }, [query]);

    useEffect(() => {
        if (!open) return undefined;
        const q = query.trim();
        if (q.length < 2) {
            setTaskResults([]);
            return undefined;
        }
        let cancelled = false;
        setTaskLoading(true);
        const timer = setTimeout(async () => {
            try {
                const params = new URLSearchParams({ search: q, page: "1", size: "5" });
                const data = await apiRequest({ path: `/tasks/filter?${params.toString()}`, token });
                if (!cancelled) setTaskResults(Array.isArray(data?.items) ? data.items : []);
            } catch {
                if (!cancelled) setTaskResults([]);
            } finally {
                if (!cancelled) setTaskLoading(false);
            }
        }, 300);
        return () => { cancelled = true; clearTimeout(timer); };
    }, [query, open, token]);

    const combined = useMemo(
        () => [
            ...filteredCommands.map(c => ({ type: "command", ...c })),
            ...taskResults.map(t => ({ type: "task", ...t })),
        ],
        [filteredCommands, taskResults],
    );

    useEffect(() => { setActiveIndex(0); }, [combined.length]);

    function runCommand(cmd) {
        if (cmd.id === "toggle-theme") setTheme(t => (t === "dark" ? "light" : "dark"));
        else if (cmd.id === "logout") onLogout();
        else setTab(cmd.tab);
        onClose();
    }

    function runTask(t) {
        setTab("tasks");
        setSearchQuery(t.title);
        onClose();
    }

    function runItem(item) {
        if (item.type === "command") runCommand(item);
        else runTask(item);
    }

    function onKeyDown(e) {
        if (e.key === "ArrowDown") {
            e.preventDefault();
            setActiveIndex(i => Math.min(i + 1, combined.length - 1));
        } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActiveIndex(i => Math.max(i - 1, 0));
        } else if (e.key === "Enter") {
            e.preventDefault();
            if (combined[activeIndex]) runItem(combined[activeIndex]);
        } else if (e.key === "Escape") {
            onClose();
        }
    }

    if (!open) return null;

    return (
        <div className="cmdk-overlay" onMouseDown={onClose}>
            <div className="cmdk-panel" onMouseDown={e => e.stopPropagation()}>
                <input
                    ref={inputRef}
                    className="cmdk-input"
                    value={query}
                    onChange={e => setQuery(e.target.value)}
                    onKeyDown={onKeyDown}
                    placeholder="Команда или название задачи…"
                />
                <div className="cmdk-list">
                    {combined.length === 0 && <div className="cmdk-empty">Ничего не найдено</div>}
                    {filteredCommands.length > 0 && <div className="cmdk-group-label">Команды</div>}
                    {filteredCommands.map((c, i) => (
                        <div
                            key={c.id}
                            className={`cmdk-item${activeIndex === i ? " active" : ""}`}
                            onMouseEnter={() => setActiveIndex(i)}
                            onClick={() => runItem({ type: "command", ...c })}
                        >
                            <span className="cmdk-icon">{c.icon}</span> {c.label}
                        </div>
                    ))}
                    {taskLoading && <div className="cmdk-group-label">Задачи · загрузка…</div>}
                    {!taskLoading && taskResults.length > 0 && <div className="cmdk-group-label">Задачи</div>}
                    {taskResults.map((t, i) => {
                        const idx = filteredCommands.length + i;
                        return (
                            <div
                                key={`task-${t.id}`}
                                className={`cmdk-item${activeIndex === idx ? " active" : ""}`}
                                onMouseEnter={() => setActiveIndex(idx)}
                                onClick={() => runItem({ type: "task", ...t })}
                            >
                                <span className="cmdk-icon">📋</span> {t.title}
                                {t.status && <span className="cmdk-hint">{CMDK_TASK_STATUS_LABELS[t.status] ?? t.status}</span>}
                            </div>
                        );
                    })}
                </div>
                <div className="cmdk-footer">
                    <span>↑↓ навигация</span><span>Enter выбрать</span><span>Esc закрыть</span>
                </div>
            </div>
        </div>
    );
}

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


// Простая клиентская подсветка @упоминаний в тексте комментария. Не знает
// о реальных username (в т.ч. с пробелами — см. backend/src/utils/mentions.py) —
// подсвечивает любой "@токен" визуально, backend сам решает, кому реально
// слать уведомление. Это чисто косметика: если "@куда-то" не существующий
// пользователь, подсветка ничего не сломает — уведомление просто не уйдёт.
function renderCommentText(text) {
    if (!text) return null;
    const parts = text.split(/(@\S+)/g);
    return parts.map((part, i) =>
        part.startsWith("@") && part.length > 1
            ? <span key={i} className="comment-mention">{part}</span>
            : <React.Fragment key={i}>{part}</React.Fragment>
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
                                <div className="comment-text">{renderCommentText(c.content)}</div>
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
                <div style={{ fontSize: 12, color: "var(--text-muted)", margin: "4px 0" }}>
                    Упомяните коллегу через @имя_пользователя — он получит уведомление
                </div>
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

// ─── DependenciesPanel ─────────────────────────────────────
function DependenciesPanel({ taskId, token }) {
    const [deps, setDeps] = useState({ blockers: [], blocked: [] });
    const [loading, setLoading] = useState(false);
    const [blockerId, setBlockerId] = useState("");
    const [adding, setAdding] = useState(false);
    const [error, setError] = useState(null);

    const loadingRef = React.useRef(false);
    const load = useCallback(async () => {
        if (loadingRef.current) return;
        loadingRef.current = true;
        setLoading(true);
        try {
            const data = await apiRequest({ path: `/tasks/${taskId}/dependencies`, token });
            setDeps({ blockers: data?.blockers ?? [], blocked: data?.blocked ?? [] });
        } catch { /* ignore */ }
        finally { setLoading(false); loadingRef.current = false; }
    }, [taskId, token]);

    useEffect(() => { load(); }, [load]);

    async function handleAdd() {
        const id = Number(blockerId);
        if (!id || id === taskId) return;
        setAdding(true);
        setError(null);
        try {
            await apiRequest({
                path: `/tasks/${taskId}/dependencies`, method: "POST", token,
                body: { blocker_task_id: id },
            });
            setBlockerId("");
            await load();
        } catch (err) {
            setError(err.message);
        } finally {
            setAdding(false);
        }
    }

    async function handleRemove(blocker) {
        setDeps(prev => ({ ...prev, blockers: prev.blockers.filter(b => b.id !== blocker.id) }));
        try {
            await apiRequest({ path: `/tasks/${taskId}/dependencies/${blocker.id}`, method: "DELETE", token });
        } catch {
            await load(); // откат при ошибке
        }
    }

    const statusLabels = {
        backlog: "В очереди", todo: "Новая", in_progress: "В работе", review: "На проверке", done: "Готово",
    };
    const openBlockersCount = deps.blockers.filter(b => b.status !== "done").length;

    return (
        <div className="comments-panel">
            <div className="comments-title">
                🔗 Зависимости
                {openBlockersCount > 0 && (
                    <span className="count-badge" style={{ background: "#ef444422", color: "#ef4444" }}>
                        {openBlockersCount} не закрыт{openBlockersCount === 1 ? "" : "о"}
                    </span>
                )}
            </div>

            {error && <div className="alert" style={{ marginBottom: 8, fontSize: 13 }}>{error}</div>}

            <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                <input
                    type="number"
                    value={blockerId}
                    onChange={e => setBlockerId(e.target.value)}
                    placeholder="ID задачи-блокера"
                    style={{ flex: 1 }}
                />
                <button className="btn btn-sm btn-primary" onClick={handleAdd} disabled={adding || !blockerId}>
                    {adding ? "…" : "Добавить"}
                </button>
            </div>

            {loading ? (
                <div className="comments-empty">Загрузка…</div>
            ) : (
                <>
                    <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>
                        Блокируют эту задачу (должны закрыться раньше):
                    </div>
                    {deps.blockers.length === 0 ? (
                        <div className="comments-empty" style={{ padding: "6px 0" }}>Нет блокеров</div>
                    ) : (
                        <div className="comment-list" style={{ marginBottom: 12 }}>
                            {deps.blockers.map(b => (
                                <div key={b.id} className="comment-item" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                    <span className="meta-chip" style={
                                        b.status === "done"
                                            ? { background: "#22c55e22", color: "#22c55e" }
                                            : { background: "#ef444422", color: "#ef4444" }
                                    }>
                                        {statusLabels[b.status] || b.status}
                                    </span>
                                    <span style={{ flex: 1 }}>#{b.id} {b.title}</span>
                                    <button className="btn btn-ghost btn-sm" style={{ padding: "2px 6px" }}
                                        onClick={() => handleRemove(b)} title="Убрать зависимость">
                                        <Icon d={ICONS.trash} />
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}

                    {deps.blocked.length > 0 && (
                        <>
                            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>
                                Ждут закрытия этой задачи:
                            </div>
                            <div className="comment-list">
                                {deps.blocked.map(b => (
                                    <div key={b.id} className="comment-item" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                        <span className="meta-chip">{statusLabels[b.status] || b.status}</span>
                                        <span style={{ flex: 1 }}>#{b.id} {b.title}</span>
                                    </div>
                                ))}
                            </div>
                        </>
                    )}
                </>
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
    const [showDependencies, setShowDependencies] = useState(false);
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
                    <span className="meta-chip task-row-user"
                        onClick={e => { e.stopPropagation(); window.openUserProfile?.(task.user.id); }}
                        style={{
                        fontSize: 11, cursor: "pointer",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        flexShrink: 0, display: "inline-flex", alignItems: "center", gap: 4,
                    }}>
                        <UserProfileAvatar userId={task.user.id} username={task.user.username} size={14} />
                        {task.user.username}
                    </span>
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
                                <span className="meta-chip" style={{ cursor: "pointer" }}
                                    onClick={e => { e.stopPropagation(); window.openUserProfile?.(task.author.id); }}>
                                    <UserProfileAvatar userId={task.author.id} username={task.author.username} size={14} /> {task.author.username}
                                </span>
                            )}
                            {task.user?.username && task.user.username !== task.author?.username && (
                                <span className="meta-chip" style={{ cursor: "pointer" }}
                                    onClick={e => { e.stopPropagation(); window.openUserProfile?.(task.user.id); }}>
                                    → <UserProfileAvatar userId={task.user.id} username={task.user.username} size={14} /> {task.user.username}
                                </span>
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
                <button className="btn btn-ghost btn-sm" onClick={() => setShowDependencies(v => !v)}>
                    <Icon d={ICONS.link} /> {showDependencies ? "Скрыть" : "Зависимости"}
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
            {showDependencies && <DependenciesPanel taskId={task.id} token={token} />}
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
                                <span className="meta-chip" style={{ cursor: "pointer" }}
                                    onClick={e => { e.stopPropagation(); window.openUserProfile?.(task.author.id); }}>
                                    <UserProfileAvatar userId={task.author.id} username={task.author.username} size={14} /> {task.author.username}
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
                                        <div className="member-info" style={{ cursor: "pointer" }} onClick={() => window.openUserProfile?.(m.id)}>
                                            <UserProfileAvatar userId={m.id} username={m.username} size={40} />
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
                                                    {m.position && (
                                                        <span className="meta-chip" style={{ fontSize: "0.72rem" }}>
                                                            {m.position}
                                                        </span>
                                                    )}
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
    const [moveError, setMoveError] = useState(null);

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

    useEffect(() => {
        if (!moveError) return;
        const timer = setTimeout(() => setMoveError(null), 6000);
        return () => clearTimeout(timer);
    }, [moveError]);

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
        setMoveError(null);
        try {
            await apiRequest({
                path: `/tasks/${taskId}/status`,
                method: "PATCH",
                token,
                body: { status: toCol },
            });
        } catch (err) {
            // Откат при ошибке — и обязательно показываем причину: без этого
            // карточка молча дёргается назад, и непонятно, почему (например,
            // задачу нельзя закрыть, пока не закрыты её блокеры — см. фичу
            // зависимостей между задачами).
            setMoveError(err.message);
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
            {moveError && (
                <div className="alert" style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <span>{moveError}</span>
                    <button className="btn btn-ghost btn-sm" onClick={() => setMoveError(null)}>✕</button>
                </div>
            )}
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
                        gap: 4,
                        cursor: "pointer",
                    }}
                        onClick={e => { e.stopPropagation(); window.openUserProfile?.(task.user.id); }}
                        title={task.user.username}
                    >
                        <UserProfileAvatar userId={task.user.id} username={task.user.username} size={16} />
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
    const [expandedItems, setExpandedItems] = useState(new Set());
    const dragIdx = useRef(null);

    function toggleExpanded(idx) {
        setExpandedItems(prev => {
            const next = new Set(prev);
            if (next.has(idx)) next.delete(idx); else next.add(idx);
            return next;
        });
    }

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
            .map(it => ({
                title: it.title,
                description: it.description || "",
                priority: it.priority,
                deadline_offset_days: it.deadline_offset_days ?? "",
                tagsText: (it.tags || []).join(", "),
                checklistText: (it.checklist || []).join("\n"),
                order_index: it.order_index,
            })));
        setView("edit");
    }

    function addItem() {
        setItems(prev => [...prev, {
            title: "", description: "", priority: "medium",
            deadline_offset_days: "", tagsText: "", checklistText: "",
            order_index: prev.length,
        }]);
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
                .map((it, i) => ({
                    title: it.title.trim(),
                    description: it.description?.trim() || null,
                    priority: it.priority,
                    deadline_offset_days: it.deadline_offset_days === "" || it.deadline_offset_days == null
                        ? null : Number(it.deadline_offset_days),
                    tags: (it.tagsText || "").split(",").map(t => t.trim()).filter(Boolean),
                    checklist: (it.checklistText || "").split("\n").map(t => t.trim()).filter(Boolean),
                    order_index: i,
                })),
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
                        <div key={idx}
                            style={{
                                marginBottom: 8, padding: "8px 10px", background: "var(--bg-card2)",
                                borderRadius: 8, border: "1px solid var(--border)",
                            }}>
                            <div draggable
                                onDragStart={() => onDragStart(idx)}
                                onDragOver={e => onDragOver(e, idx)}
                                onDragEnd={onDragEnd}
                                style={{ display: "flex", alignItems: "center", gap: 8, cursor: "grab" }}>
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
                                <button type="button" className="btn btn-ghost btn-sm" onClick={() => toggleExpanded(idx)}
                                    title="Описание, дедлайн, теги, чек-лист" style={{ flexShrink: 0 }}>
                                    {expandedItems.has(idx) ? "▲" : "⚙"}
                                </button>
                                <button className="btn btn-ghost btn-sm" onClick={() => removeItem(idx)}
                                    style={{ flexShrink: 0, color: "var(--red)" }}>
                                    <Icon d={ICONS.x} />
                                </button>
                            </div>
                            {expandedItems.has(idx) && (
                                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8, paddingLeft: 24 }}>
                                    <textarea className="input" rows={2} placeholder="Описание задачи (необязательно)"
                                        value={item.description || ""} onChange={e => updateItem(idx, "description", e.target.value)}
                                        style={{ marginBottom: 0, resize: "vertical" }} />
                                    <div style={{ display: "flex", gap: 8 }}>
                                        <div style={{ flex: 1 }}>
                                            <label className="field-label">ДЕДЛАЙН, ДНЕЙ ОТ ПРИМЕНЕНИЯ</label>
                                            <input className="input" type="number" min={0} max={3650}
                                                placeholder="Например: 3"
                                                value={item.deadline_offset_days}
                                                onChange={e => updateItem(idx, "deadline_offset_days", e.target.value)}
                                                style={{ marginBottom: 0 }} />
                                        </div>
                                        <div style={{ flex: 1 }}>
                                            <label className="field-label">ТЕГИ ЧЕРЕЗ ЗАПЯТУЮ</label>
                                            <input className="input" placeholder="срочно, клиент"
                                                value={item.tagsText || ""}
                                                onChange={e => updateItem(idx, "tagsText", e.target.value)}
                                                style={{ marginBottom: 0 }} />
                                        </div>
                                    </div>
                                    <div>
                                        <label className="field-label">ЧЕК-ЛИСТ — ПО ПУНКТУ НА СТРОКУ</label>
                                        <textarea className="input" rows={3} placeholder={"Подготовить материалы\nСогласовать с руководителем"}
                                            value={item.checklistText || ""} onChange={e => updateItem(idx, "checklistText", e.target.value)}
                                            style={{ marginBottom: 0, resize: "vertical" }} />
                                    </div>
                                </div>
                            )}
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
                                                        {item.deadline_offset_days != null && ` · ⏰${item.deadline_offset_days}д`}
                                                        {item.tags && item.tags.length > 0 && ` · 🏷${item.tags.length}`}
                                                        {item.checklist && item.checklist.length > 0 && ` · ☑${item.checklist.length}`}
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
                                    <span key={m.id} className="meta-chip" style={{ cursor: "pointer" }}
                                        onClick={() => window.openUserProfile?.(m.id)}>
                                        <UserProfileAvatar userId={m.id} username={m.username} size={14} />
                                        {m.username}{m.position ? ` · ${m.position}` : ""}
                                    </span>
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
                                                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer" }}
                                                            onClick={() => window.openUserProfile?.(m.id)}>
                                                            <UserProfileAvatar userId={m.id} username={m.username} size={14} />
                                                            {m.username}{m.position ? ` · ${m.position}` : ""}
                                                        </span>
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
// ─── TeamTab — справочник всей команды (плоский список, в отличие от
// "Группы", где пользователи сгруппированы и есть управление составом) ────
function TeamTab({ token }) {
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [query, setQuery] = useState("");

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await apiRequest({ path: "/users?page=1&size=100", token });
            setUsers(Array.isArray(data?.items) ? data.items : []);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => { load(); }, [load]);

    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return users;
        return users.filter(u =>
            u.username.toLowerCase().includes(q) || (u.position || "").toLowerCase().includes(q)
        );
    }, [users, query]);

    return (
        <div className="card">
            <div className="section-header">
                <div>
                    <div className="section-title">👥 Команда</div>
                    <div className="section-sub">{users.length} человек</div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={load} disabled={loading}>
                    <Icon d={ICONS.refresh} /> Обновить
                </button>
            </div>

            <input
                className="input"
                placeholder="Поиск по имени или должности…"
                value={query}
                onChange={e => setQuery(e.target.value)}
                style={{ marginBottom: 14 }}
            />

            {error && <div className="alert">{error}</div>}
            {loading ? (
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
            ) : filtered.length === 0 ? (
                <div className="empty-state"><div className="empty-icon">🔍</div>Никого не нашли</div>
            ) : (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 10 }}>
                    {filtered.map(u => {
                        const rc = ROLE_COLORS[u.role] ?? ROLE_COLORS.user;
                        return (
                            <div key={u.id}
                                onClick={() => window.openUserProfile?.(u.id)}
                                style={{
                                    display: "flex", alignItems: "center", gap: 10,
                                    padding: "10px 12px", borderRadius: 10,
                                    background: "var(--surface2)", border: "1px solid var(--border)",
                                    cursor: "pointer",
                                }}>
                                <UserProfileAvatar userId={u.id} username={u.username} size={40} />
                                <div style={{ minWidth: 0, flex: 1 }}>
                                    <div style={{
                                        fontWeight: 600, fontSize: 14,
                                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                                    }}>
                                        {u.username}
                                        {!u.is_active && <span className="inactive-badge" style={{ marginLeft: 6 }}>неакт.</span>}
                                    </div>
                                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 3, flexWrap: "wrap" }}>
                                        <span className="role-badge" style={{ color: rc.color, background: rc.bg, fontSize: 11 }}>
                                            {ROLE_LABELS[u.role] ?? u.role}
                                        </span>
                                        {u.position && (
                                            <span style={{
                                                fontSize: 12, color: "var(--text-muted)",
                                                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                                            }}>
                                                {u.position}
                                            </span>
                                        )}
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

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


// ─── Calendar Feed Tab ────────────────────────────────────
function CalendarTab({ token }) {
    const [feedUrl, setFeedUrl] = useState(null);
    const [loading, setLoading] = useState(true);
    const [creating, setCreating] = useState(false);
    const [copied, setCopied] = useState(false);
    const [error, setError] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await apiRequest({ path: "/calendar/token", token });
            setFeedUrl(data?.feed_url ?? null);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => { load(); }, [load]);

    async function handleCreateOrRotate() {
        setCreating(true);
        setError(null);
        try {
            const data = await apiRequest({ path: "/calendar/token", method: "POST", token });
            setFeedUrl(data.feed_url);
            setCopied(false);
        } catch (err) {
            setError(err.message);
        } finally {
            setCreating(false);
        }
    }

    async function handleCopy() {
        try {
            await navigator.clipboard.writeText(feedUrl);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch { /* clipboard недоступен — пользователь скопирует вручную */ }
    }

    // webcal:// — специальная схема, по которой Google Calendar/Outlook/Apple
    // Calendar понимают "это ссылка на подписку", а не просто файл для скачивания.
    const webcalUrl = feedUrl ? feedUrl.replace(/^https?:\/\//, "webcal://") : null;
    const googleCalendarUrl = webcalUrl ? `https://calendar.google.com/calendar/r?cid=${encodeURIComponent(webcalUrl)}` : null;

    return (
        <div>
            <div className="card" style={{ marginTop: 0 }}>
                <div className="section-header">
                    <div>
                        <div className="section-title"><Icon d={ICONS.calendar} /> Календарь дедлайнов</div>
                        <div className="section-sub">
                            Подпишитесь на дедлайны своих задач в Google Calendar, Outlook или Apple Calendar —
                            они будут показываться в вашем основном календаре без захода в приложение.
                            Календарь сам периодически перечитывает ссылку, ничего обновлять вручную не нужно.
                        </div>
                    </div>
                </div>

                {error && <div className="alert" style={{ marginBottom: 12 }}>{error}</div>}

                {loading ? (
                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                ) : !feedUrl ? (
                    <div className="empty-state">
                        <div className="empty-icon">📅</div>
                        Ссылка ещё не создана
                        <div style={{ marginTop: 12 }}>
                            <button className="btn btn-primary" onClick={handleCreateOrRotate} disabled={creating}>
                                <Icon d={ICONS.plus} /> {creating ? "Создание…" : "Создать ссылку"}
                            </button>
                        </div>
                    </div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                            <code style={{
                                flex: 1, padding: "8px 12px", background: "var(--surface2)",
                                borderRadius: 6, fontSize: 13, wordBreak: "break-all",
                            }}>
                                {feedUrl}
                            </code>
                            <button type="button" className="btn btn-sm btn-primary" onClick={handleCopy}>
                                {copied ? "✓ Скопировано" : "Скопировать"}
                            </button>
                        </div>

                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                            <a className="btn btn-sm" href={googleCalendarUrl} target="_blank" rel="noreferrer">
                                Добавить в Google Calendar
                            </a>
                            <a className="btn btn-sm" href={webcalUrl}>
                                Добавить в Outlook / Apple Calendar
                            </a>
                            <button className="btn btn-sm" onClick={handleCreateOrRotate} disabled={creating}>
                                {creating ? "…" : "Перевыпустить ссылку"}
                            </button>
                        </div>

                        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                            Ссылку не стоит выкладывать публично — по ней доступны дедлайны ваших задач без
                            дополнительного пароля. Если она куда-то утекла — нажмите «Перевыпустить», старая
                            сразу перестанет работать.
                            <br />
                            В Google Calendar: «Другие календари» → «+» → «По URL» — если кнопка выше не сработала
                            автоматически, вставьте ссылку туда вручную.
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}


// ─── Принудительная смена пароля (после автосоздания через бота) ──
function ForceChangePasswordScreen({ token, onDone, onLogout }) {
    const [currentPassword, setCurrentPassword] = useState("");
    const [newPassword, setNewPassword] = useState("");
    const [newPassword2, setNewPassword2] = useState("");
    const [error, setError] = useState(null);
    const [saving, setSaving] = useState(false);

    async function handleSubmit(e) {
        e.preventDefault();
        if (newPassword !== newPassword2) {
            setError("Новые пароли не совпадают");
            return;
        }
        if (newPassword.length < 6) {
            setError("Пароль должен быть не короче 6 символов");
            return;
        }
        setSaving(true);
        setError(null);
        try {
            await apiRequest({
                path: "/users/me/password", method: "POST", token,
                body: { current_password: currentPassword, new_password: newPassword },
            });
            onDone();
        } catch (err) {
            setError(err.message);
        } finally {
            setSaving(false);
        }
    }

    return (
        <div className="login-page">
            <div className="auth-card">
                <div className="auth-title">Смените пароль</div>
                <div className="auth-sub">
                    Ваш текущий пароль был автоматически сгенерирован и прислан в Telegram —
                    задайте свой перед тем, как продолжить.
                </div>
                <form className="form" onSubmit={handleSubmit}>
                    <div className="form-group">
                        <label className="form-label">Текущий (временный) пароль</label>
                        <input type="password" value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} required />
                    </div>
                    <div className="form-group">
                        <label className="form-label">Новый пароль</label>
                        <input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} required minLength={6} />
                    </div>
                    <div className="form-group">
                        <label className="form-label">Повторите новый пароль</label>
                        <input type="password" value={newPassword2} onChange={e => setNewPassword2(e.target.value)} required minLength={6} />
                    </div>
                    <button type="submit" className="btn btn-primary" disabled={saving}>
                        {saving ? "…" : "Сменить пароль"}
                    </button>
                    {error && <div className="alert">{error}</div>}
                </form>
                <button className="btn btn-ghost btn-sm" style={{ marginTop: 8 }} onClick={onLogout}>
                    Выйти
                </button>
            </div>
        </div>
    );
}


// ─── Смена пароля (по желанию, не только принудительно) ────
function ChangePasswordCard({ token }) {
    const [currentPassword, setCurrentPassword] = useState("");
    const [newPassword, setNewPassword] = useState("");
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    const [success, setSuccess] = useState(false);

    async function handleSubmit(e) {
        e.preventDefault();
        setSaving(true);
        setError(null);
        setSuccess(false);
        try {
            await apiRequest({
                path: "/users/me/password", method: "POST", token,
                body: { current_password: currentPassword, new_password: newPassword },
            });
            setSuccess(true);
            setCurrentPassword("");
            setNewPassword("");
        } catch (err) {
            setError(err.message);
        } finally {
            setSaving(false);
        }
    }

    return (
        <div className="card" style={{ maxWidth: 520 }}>
            <div className="section-header">
                <div className="section-title">🔑 Сменить пароль</div>
            </div>
            {success && <div className="alert" style={{ borderColor: "#22c55e", background: "#22c55e11", marginBottom: 12 }}>Пароль изменён</div>}
            {error && <div className="alert" style={{ marginBottom: 12 }}>{error}</div>}
            <form className="form" onSubmit={handleSubmit}>
                <div className="form-group">
                    <label className="form-label">Текущий пароль</label>
                    <input type="password" value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} required />
                </div>
                <div className="form-group">
                    <label className="form-label">Новый пароль</label>
                    <input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} required minLength={6} />
                </div>
                <button className="btn btn-primary btn-sm" type="submit" disabled={saving}>
                    {saving ? "…" : "Сменить"}
                </button>
            </form>
        </div>
    );
}


// ─── Two-Factor Auth Tab ──────────────────────────────────
function TwoFactorTab({ token }) {
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Состояние процесса настройки
    const [setupData, setSetupData] = useState(null); // { secret, otpauth_url }
    const [confirmCode, setConfirmCode] = useState("");
    const [confirming, setConfirming] = useState(false);
    const [recoveryCodes, setRecoveryCodes] = useState(null); // показываются один раз
    const [starting, setStarting] = useState(false);

    // Состояние отключения
    const [disablePassword, setDisablePassword] = useState("");
    const [disableCode, setDisableCode] = useState("");
    const [disabling, setDisabling] = useState(false);
    const [showDisableForm, setShowDisableForm] = useState(false);

    const canvasRef = useRef(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await apiRequest({ path: "/auth/2fa/status", token });
            setStatus(data);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => { load(); }, [load]);

    useEffect(() => {
        if (setupData?.otpauth_url && canvasRef.current) {
            QRCode.toCanvas(canvasRef.current, setupData.otpauth_url, { width: 220 }, () => { });
        }
    }, [setupData]);

    async function handleStartSetup() {
        setStarting(true);
        setError(null);
        try {
            const data = await apiRequest({ path: "/auth/2fa/setup", method: "POST", token });
            setSetupData(data);
            setRecoveryCodes(null);
        } catch (err) {
            setError(err.message);
        } finally {
            setStarting(false);
        }
    }

    async function handleConfirm(e) {
        e.preventDefault();
        setConfirming(true);
        setError(null);
        try {
            const data = await apiRequest({
                path: "/auth/2fa/confirm", method: "POST", token,
                body: { code: confirmCode.trim() },
            });
            setRecoveryCodes(data.recovery_codes);
            setSetupData(null);
            setConfirmCode("");
            await load();
        } catch (err) {
            setError(err.message);
        } finally {
            setConfirming(false);
        }
    }

    async function handleDisable(e) {
        e.preventDefault();
        setDisabling(true);
        setError(null);
        try {
            await apiRequest({
                path: "/auth/2fa/disable", method: "POST", token,
                body: { password: disablePassword, code: disableCode },
            });
            setShowDisableForm(false);
            setDisablePassword("");
            setDisableCode("");
            await load();
        } catch (err) {
            setError(err.message);
        } finally {
            setDisabling(false);
        }
    }

    return (
        <div className="card" style={{ marginTop: 0, maxWidth: 520 }}>
            <div className="section-header">
                <div>
                    <div className="section-title">🔒 Двухфакторная аутентификация</div>
                    <div className="section-sub">
                        Дополнительный код из приложения-аутентификатора (Google Authenticator, Authy и т.п.)
                        при каждом входе — даже если пароль утечёт, войти без телефона не получится.
                    </div>
                </div>
            </div>

            {error && <div className="alert" style={{ marginBottom: 12 }}>{error}</div>}

            {recoveryCodes && (
                <div className="alert" style={{
                    marginBottom: 16, borderColor: "#22c55e", background: "#22c55e11",
                    display: "flex", flexDirection: "column", gap: 8,
                }}>
                    <div>
                        <strong>2FA включена!</strong> Сохраните эти recovery-коды — каждый работает один раз
                        и пригодится, если телефон с аутентификатором потеряется. Больше они не покажутся.
                    </div>
                    <div style={{
                        display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6,
                        fontFamily: "monospace", fontSize: 14, background: "var(--surface2)",
                        padding: 12, borderRadius: 6,
                    }}>
                        {recoveryCodes.map(c => <div key={c}>{c}</div>)}
                    </div>
                    <button
                        className="btn btn-sm btn-primary" style={{ alignSelf: "flex-start" }}
                        onClick={() => navigator.clipboard.writeText(recoveryCodes.join("\n")).catch(() => { })}
                    >
                        Скопировать все
                    </button>
                </div>
            )}

            {loading ? (
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
            ) : status?.enabled ? (
                <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                        <span className="meta-chip" style={{ background: "#22c55e22", color: "#22c55e" }}>включена</span>
                    </div>
                    {!showDisableForm ? (
                        <button className="btn btn-sm" onClick={() => setShowDisableForm(true)}>Отключить 2FA</button>
                    ) : (
                        <form className="form" onSubmit={handleDisable}>
                            <div className="form-group">
                                <label className="form-label">Пароль</label>
                                <input type="password" value={disablePassword} onChange={e => setDisablePassword(e.target.value)} required />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Код из аутентификатора (или recovery-код)</label>
                                <input value={disableCode} onChange={e => setDisableCode(e.target.value)} required />
                            </div>
                            <div style={{ display: "flex", gap: 8 }}>
                                <button className="btn btn-danger btn-sm" type="submit" disabled={disabling}>
                                    {disabling ? "…" : "Подтвердить отключение"}
                                </button>
                                <button className="btn btn-ghost btn-sm" type="button" onClick={() => setShowDisableForm(false)}>
                                    Отмена
                                </button>
                            </div>
                        </form>
                    )}
                </div>
            ) : setupData ? (
                <div>
                    <div style={{ marginBottom: 12 }}>
                        Отсканируйте QR-код приложением-аутентификатором, затем введите 6-значный код:
                    </div>
                    <canvas ref={canvasRef} style={{ marginBottom: 12, background: "#fff", padding: 8, borderRadius: 8 }} />
                    <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>
                        Не получается отсканировать? Введите секрет вручную: <code>{setupData.secret}</code>
                    </div>
                    <form className="form" onSubmit={handleConfirm}>
                        <div className="form-group">
                            <input
                                value={confirmCode} onChange={e => setConfirmCode(e.target.value)}
                                placeholder="123456" inputMode="numeric" maxLength={6} required autoFocus
                            />
                        </div>
                        <div style={{ display: "flex", gap: 8 }}>
                            <button className="btn btn-primary btn-sm" type="submit" disabled={confirming}>
                                {confirming ? "…" : "Подтвердить и включить"}
                            </button>
                            <button className="btn btn-ghost btn-sm" type="button" onClick={() => setSetupData(null)}>
                                Отмена
                            </button>
                        </div>
                    </form>
                </div>
            ) : (
                <div>
                    <span className="meta-chip" style={{ marginBottom: 12, display: "inline-block" }}>отключена</span>
                    <div>
                        <button className="btn btn-primary btn-sm" onClick={handleStartSetup} disabled={starting}>
                            {starting ? "…" : "Настроить 2FA"}
                        </button>
                    </div>
                </div>
            )}
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
    const [scope, setScope] = useState("read_write");
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
            const body = { name: newName.trim(), scope };
            if (expiresInDays) body.expires_in_days = Number(expiresInDays);
            const created = await apiRequest({ path: "/tokens", method: "POST", token, body });
            setJustCreated({ token: created.token, name: created.name, scope: created.scope });
            setNewName("");
            setExpiresInDays("");
            setScope("read_write");
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
                            <strong>Токен «{justCreated.name}» создан</strong>
                            {" "}({justCreated.scope === "read_only" ? "read-only" : "read-write"}). Сохраните его сейчас —
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
                    <div className="form-group">
                        <label className="form-label">Уровень доступа</label>
                        <select value={scope} onChange={e => setScope(e.target.value)}>
                            <option value="read_write">Read-write — как обычная веб-сессия (создание, изменение, удаление)</option>
                            <option value="read_only">Read-only — только чтение (GET). Безопасно для разовых интеграций</option>
                        </select>
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
                                            <span className="meta-chip" style={
                                                t.scope === "read_only"
                                                    ? { background: "#3b82f622", color: "#3b82f6" }
                                                    : { background: "#22c55e22", color: "#22c55e" }
                                            }>
                                                {t.scope === "read_only" ? "read-only" : "read-write"}
                                            </span>
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


// ─── Webhooks Tab ─────────────────────────────────────────
const WEBHOOK_EVENT_LABELS = {
    "task.created": "Задача создана",
    "task.updated": "Задача изменена",
    "task.status_changed": "Статус задачи изменён",
    "task.done": "Задача переведена в «Готово»",
    "task.deleted": "Задача удалена",
    "comment.added": "Добавлен комментарий",
};
const WEBHOOK_EVENTS = Object.keys(WEBHOOK_EVENT_LABELS);

function WebhooksTab({ token }) {
    const [webhooks, setWebhooks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [newUrl, setNewUrl] = useState("");
    const [newEvents, setNewEvents] = useState([]);
    const [creating, setCreating] = useState(false);
    const [justCreated, setJustCreated] = useState(null); // { id, secret } — показываем один раз
    const [copied, setCopied] = useState(false);
    const [testResults, setTestResults] = useState({}); // webhookId -> { delivered, status_code, error }
    const [testingId, setTestingId] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await apiRequest({ path: "/webhooks", token });
            setWebhooks(Array.isArray(data) ? data : []);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => { load(); }, [load]);

    function toggleNewEvent(ev) {
        setNewEvents(prev => prev.includes(ev) ? prev.filter(e => e !== ev) : [...prev, ev]);
    }

    async function handleCreate(e) {
        e.preventDefault();
        if (!newUrl.trim() || newEvents.length === 0) return;
        setCreating(true);
        setError(null);
        try {
            const created = await apiRequest({
                path: "/webhooks", method: "POST", token,
                body: { url: newUrl.trim(), events: newEvents },
            });
            setJustCreated({ id: created.id, secret: created.secret });
            setNewUrl("");
            setNewEvents([]);
            setCopied(false);
            await load();
        } catch (err) {
            setError(err.message);
        } finally {
            setCreating(false);
        }
    }

    async function handleDelete(id, url) {
        if (!window.confirm(`Удалить вебхук на «${url}»? События на этот URL больше не будут отправляться.`)) return;
        try {
            await apiRequest({ path: `/webhooks/${id}`, method: "DELETE", token });
            if (justCreated?.id === id) setJustCreated(null);
            await load();
        } catch (err) {
            setError(err.message);
        }
    }

    async function handleToggleActive(hook) {
        try {
            await apiRequest({ path: `/webhooks/${hook.id}`, method: "PATCH", token, body: { is_active: !hook.is_active } });
            await load();
        } catch (err) {
            setError(err.message);
        }
    }

    async function handleRotateSecret(id) {
        if (!window.confirm("Перевыпустить secret? Старый сразу перестанет проходить проверку подписи на вашей стороне.")) return;
        try {
            const rotated = await apiRequest({ path: `/webhooks/${id}/rotate-secret`, method: "POST", token });
            setJustCreated({ id: rotated.id, secret: rotated.secret });
            setCopied(false);
            await load();
        } catch (err) {
            setError(err.message);
        }
    }

    async function handleTest(id) {
        setTestingId(id);
        try {
            const result = await apiRequest({ path: `/webhooks/${id}/test`, method: "POST", token });
            setTestResults(prev => ({ ...prev, [id]: result }));
        } catch (err) {
            setTestResults(prev => ({ ...prev, [id]: { delivered: false, status_code: null, error: err.message } }));
        } finally {
            setTestingId(null);
        }
    }

    async function handleCopy() {
        try {
            await navigator.clipboard.writeText(justCreated.secret);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch { /* clipboard недоступен — пользователь скопирует вручную */ }
    }

    return (
        <div>
            <div className="card" style={{ marginTop: 0 }}>
                <div className="section-header">
                    <div>
                        <div className="section-title"><Icon d={ICONS.link} /> Исходящие вебхуки</div>
                        <div className="section-sub">
                            Противоположность API-токенам: не вы стучитесь к нам, а мы — POST-запросом —
                            уведомляем ваш URL, когда что-то произошло (задача готова, новый комментарий и т.д.).
                        </div>
                    </div>
                </div>

                {error && <div className="alert" style={{ marginBottom: 12 }}>{error}</div>}

                {justCreated && (
                    <div className="alert" style={{
                        marginBottom: 16, display: "flex", flexDirection: "column", gap: 8,
                        borderColor: "#22c55e", background: "#22c55e11",
                    }}>
                        <div>
                            <strong>Secret сохранён</strong> — покажем его только сейчас. Настройте проверку
                            подписи на своей стороне: заголовок <code>X-Webhook-Signature</code> содержит
                            <code> sha256=HMAC-SHA256(secret, raw_body)</code>.
                        </div>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                            <code style={{
                                flex: 1, padding: "8px 12px", background: "var(--surface2)",
                                borderRadius: 6, fontSize: 13, wordBreak: "break-all",
                            }}>
                                {justCreated.secret}
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
                    <div className="form-group">
                        <label className="form-label">URL</label>
                        <input
                            value={newUrl}
                            onChange={e => setNewUrl(e.target.value)}
                            placeholder="https://example.com/webhooks/spisok-del"
                        />
                    </div>
                    <div className="form-group">
                        <label className="form-label">На какие события отправлять</label>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                            {WEBHOOK_EVENTS.map(ev => (
                                <label key={ev} style={{
                                    display: "flex", alignItems: "center", gap: 6,
                                    padding: "6px 10px", borderRadius: 8, cursor: "pointer",
                                    background: newEvents.includes(ev) ? "#22c55e22" : "var(--surface2)",
                                    border: `1px solid ${newEvents.includes(ev) ? "#22c55e" : "var(--border)"}`,
                                    fontSize: 13,
                                }}>
                                    <input type="checkbox" checked={newEvents.includes(ev)} onChange={() => toggleNewEvent(ev)} />
                                    {WEBHOOK_EVENT_LABELS[ev]}
                                </label>
                            ))}
                        </div>
                    </div>
                    <button className="btn btn-primary" type="submit" disabled={creating || !newUrl.trim() || newEvents.length === 0}>
                        <Icon d={ICONS.plus} /> {creating ? "Создание…" : "Создать вебхук"}
                    </button>
                </form>

                {loading ? (
                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                ) : webhooks.length === 0 ? (
                    <div className="empty-state"><div className="empty-icon">🔗</div>Вебхуков пока нет</div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        {webhooks.map(w => {
                            const result = testResults[w.id];
                            return (
                                <div key={w.id} style={{
                                    display: "flex", flexDirection: "column", gap: 8,
                                    padding: "10px 14px", borderRadius: 8,
                                    background: "var(--surface2)", border: "1px solid var(--border)",
                                }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 8, wordBreak: "break-all" }}>
                                                {w.url}
                                                <span className="meta-chip" style={
                                                    w.is_active
                                                        ? { background: "#22c55e22", color: "#22c55e" }
                                                        : { background: "#ef444422", color: "#ef4444" }
                                                }>
                                                    {w.is_active ? "включён" : "отключён"}
                                                </span>
                                                {w.failure_count >= 5 && w.is_active && (
                                                    <span className="meta-chip" style={{ background: "#f59e0b22", color: "#f59e0b" }}>
                                                        {w.failure_count} сбоев подряд
                                                    </span>
                                                )}
                                            </div>
                                            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4, display: "flex", flexWrap: "wrap", gap: 6 }}>
                                                {w.events.map(ev => (
                                                    <span key={ev} className="meta-chip">{WEBHOOK_EVENT_LABELS[ev] || ev}</span>
                                                ))}
                                            </div>
                                            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
                                                <code>{w.secret_prefix}…</code>
                                                {" · последняя доставка: "}
                                                {w.last_triggered_at
                                                    ? `${formatTokenDate(w.last_triggered_at)} (${w.last_status_code ?? "ошибка"})`
                                                    : "ни разу"}
                                            </div>
                                            {result && (
                                                <div style={{ fontSize: 12, marginTop: 4, color: result.delivered ? "#22c55e" : "#ef4444" }}>
                                                    Тест: {result.delivered ? `✓ доставлено (${result.status_code})` : `✗ ${result.error || result.status_code || "не доставлено"}`}
                                                </div>
                                            )}
                                        </div>
                                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                                            <button className="btn btn-sm" onClick={() => handleTest(w.id)} disabled={testingId === w.id}>
                                                {testingId === w.id ? "…" : "Тест"}
                                            </button>
                                            <button className="btn btn-sm" onClick={() => handleToggleActive(w)}>
                                                {w.is_active ? "Отключить" : "Включить"}
                                            </button>
                                            <button className="btn btn-sm" onClick={() => handleRotateSecret(w.id)}>
                                                Перевыпустить secret
                                            </button>
                                            <button className="btn btn-danger btn-sm" onClick={() => handleDelete(w.id, w.url)}>
                                                <Icon d={ICONS.trash} />
                                            </button>
                                        </div>
                                    </div>
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

// ─── StatsDonut — маленький пончиковый график для личной статистики ──────
function StatsDonut({ total, done, pending, doneLabel = "Готово", pendingLabel = "В работе" }) {
    const rest = Math.max(0, (total ?? 0) - (done ?? 0) - (pending ?? 0));
    const data = [
        { name: doneLabel, value: done ?? 0, color: "var(--green)" },
        { name: pendingLabel, value: pending ?? 0, color: "var(--accent-light)" },
        { name: "Остальное", value: rest, color: "var(--border-hover)" },
    ].filter(d => d.value > 0);

    if (!total) {
        return (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 170, color: "var(--text-muted)", fontSize: 13 }}>
                Нет задач
            </div>
        );
    }

    return (
        <ResponsiveContainer width="100%" height={170}>
            <PieChart>
                <Pie data={data} dataKey="value" nameKey="name" innerRadius={38} outerRadius={58} paddingAngle={2} stroke="none">
                    {data.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Pie>
                <Tooltip contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
            </PieChart>
        </ResponsiveContainer>
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
                <StatsDonut total={stats.total} done={stats.done} pending={stats.pending} />
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
                <StatsDonut total={stats.a_total} done={stats.a_done} pending={(stats.a_total ?? 0) - (stats.a_done ?? 0)} doneLabel="Закрыто" pendingLabel="Открыто" />
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
                    <ResponsiveContainer width="100%" height={Math.max(120, executors.length * 42)}>
                        <BarChart data={executors} layout="vertical" margin={{ left: 8, right: 24 }}>
                            <XAxis type="number" domain={[0, 100]} tick={{ fill: "var(--text-muted)", fontSize: 12 }} unit="%" />
                            <YAxis type="category" dataKey="username" width={110} tick={{ fill: "var(--text)", fontSize: 12 }} />
                            <Tooltip
                                contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                                formatter={(value, _name, item) => [`${item.payload.on_time}/${item.payload.total_completed} в срок (${value}%)`, "Вовремя"]}
                            />
                            <Bar dataKey="on_time_rate" radius={[0, 6, 6, 0]}>
                                {executors.map((e, i) => (
                                    <Cell key={i} fill={e.on_time_rate >= 80 ? "var(--green)" : e.on_time_rate >= 50 ? "var(--amber)" : "var(--red)"} />
                                ))}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
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
                    <ResponsiveContainer width="100%" height={Math.max(160, projects.length * 50)}>
                        <BarChart data={projects} margin={{ left: -10, right: 12, top: 8 }}>
                            <XAxis dataKey="project_name" tick={{ fill: "var(--text-muted)", fontSize: 11 }} interval={0} angle={-20} textAnchor="end" height={60} />
                            <YAxis tick={{ fill: "var(--text-muted)", fontSize: 12 }} unit=" дн." />
                            <Tooltip
                                contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                                formatter={(value, _name, item) => [`${item.payload.completed_late}/${item.payload.total_completed} с опозданием`, `+${value} дн.`]}
                            />
                            <Bar dataKey="avg_overdue_days" radius={[6, 6, 0, 0]}>
                                {projects.map((p, i) => (
                                    <Cell key={i} fill={p.avg_overdue_days === 0 ? "var(--green)" : p.avg_overdue_days > 3 ? "var(--red)" : "var(--amber)"} />
                                ))}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>
        </>
    );
}

// ─── Main App ─────────────────────────────────────────────
function App() {
    const [token, setToken] = useState(localStorage.getItem("spisoc_token"));
    const [tab, setTab] = useState("tasks"); // "tasks" | "projects" | "groups" | "trash" | "dashboard" | "templates"
    const [mfaPending, setMfaPending] = useState(null); // { mfaToken } — ждём код 2FA перед выдачей токенов
    const [show2faNudge, setShow2faNudge] = useState(false);
    const [mustChangePassword, setMustChangePassword] = useState(false);

    // ── WebSocket realtime ────────────────────────────────────────────────────
    const [chatWsEvent, setChatWsEvent] = useState(null);

    // handleWsEvent должен иметь СТАБИЛЬНУЮ ссылку (useCallback с пустыми deps) —
    // иначе useWebSocket(token, handleWsEvent) пересоздаёт соединение на каждое
    // изменение `tab`/`tasksPage`/`viewMode` (они были в deps раньше), а это
    // рвёт WS ровно в момент переключения вкладок и роняет "живые" события —
    // отсюда и жалоба "сообщения приходят с опозданием, иногда нужно
    // перезагружать страницу". Вместо deps читаем актуальные значения из рефов.
    const tabRef = useRef(tab);
    tabRef.current = tab;
    // Синхронизируются чуть ниже, сразу после объявления соответствующих
    // useState (tasksPage/viewMode объявлены позже в этом компоненте) —
    // до тех пор просто держат дефолт, handleWsEvent их читает лениво,
    // только когда реально прилетает WS-событие.
    const tasksPageRef = useRef(1);

    const handleWsEvent = useCallback((event, data) => {
        const currentTab = tabRef.current;
        if (event === "task_created" || event === "task_updated" || event === "kanban_moved" || event === "task_deleted") {
            if (currentTab === "tasks") loadTasks(tasksPageRef.current, viewModeRef.current);
            // Канбан обновляет список сам при монтировании/действиях пользователя —
            // отдельного live-refresh для него пока нет (не относится к этой правке).
        } else if (event === "task_restored") {
            if (currentTab === "trash") loadTrash();
        } else if (event === "comment_added") {
            // Комментарии обновятся при следующем открытии задачи
        } else if (event === "chat_message" || event === "chat_message_deleted") {
            setChatWsEvent({ event, data, ts: Date.now() });
        }
    }, []);  // eslint-disable-line

    useWebSocket(token, handleWsEvent);
    const [theme, setTheme] = useState(() => localStorage.getItem("spisoc_theme") || "dark");

    const [paletteOpen, setPaletteOpen] = useState(false);
    const [profileUserId, setProfileUserId] = useState(null);
    // window.openUserProfile — чтобы открывать профиль клика по имени из глубоко
    // вложенных компонентов (TaskCard, комментарии, участники проекта) без
    // протаскивания callback через десяток слоёв пропсов.
    useEffect(() => {
        window.openUserProfile = (id) => setProfileUserId(id);
        return () => { delete window.openUserProfile; };
    }, []);
    useEffect(() => {
        function onKeyDown(e) {
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
                e.preventDefault();
                setPaletteOpen(open => !open);
            }
        }
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, []);
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
    tasksPageRef.current = tasksPage;
    const [tasksTotal, setTasksTotal] = useState(null); // null = ещё не загружено (см. count-badge ниже — резервируем место, чтобы бейдж не "впрыгивал" и не сдвигал вкладки)
    const PAGE_SIZE = 50;

    const [trashPage, setTrashPage] = useState(1);
    const [trashTotal, setTrashTotal] = useState(null); // null = ещё не загружено

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
            // Первый вход или смена токена — грузим всё.
            // loadTrash(1) грузим сразу, а не только при открытии вкладки "Корзина" —
            // иначе счётчик-бейдж появляется с опозданием и весь ряд вкладок
            // сдвигается по ширине (см. баг-репорт про "прыгающие" отступы).
            didInitRef.current = true;
            loadGroups();
            loadUsers();
            loadTags();
            loadFilterPresets();
            if (tab === "tasks") loadTasks(1);
            loadTrash(1);
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
            if (resp.mfa_required) {
                setMfaPending({ mfaToken: resp.mfa_token });
                return;
            }
            saveTokens(resp.access_token, resp.refresh_token);
            setToken(resp.access_token);
            setShow2faNudge(!!resp.requires_2fa_setup);
            setMustChangePassword(!!resp.must_change_password);
        } catch (err) { setError(err.message); }
    }

    async function handleLogin2fa(e) {
        e.preventDefault();
        const fd = new FormData(e.target);
        try {
            setError(null);
            const resp = await apiRequest({
                path: "/auth/login/2fa", method: "POST",
                body: { mfa_token: mfaPending.mfaToken, code: fd.get("code").trim() },
            });
            saveTokens(resp.access_token, resp.refresh_token);
            setToken(resp.access_token);
            setMfaPending(null);
            setMustChangePassword(!!resp.must_change_password);
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
        setTasksTotal(prev => (prev ?? 0) - 1);
        try {
            await apiRequest({ path: `/tasks/${task.id}`, method: "DELETE", token });
        } catch (err) {
            setTasks(prev => [...prev, task].sort((a, b) => a.id - b.id));
            setTasksTotal(prev => (prev ?? 0) + 1);
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
        setTrashTotal(prev => (prev ?? 0) - 1);
        try {
            await apiRequest({ path: `/tasks/${task.id}/restore`, method: "PATCH", token });
        } catch (err) {
            setTrash(prev => [...prev, task].sort((a, b) => a.id - b.id));
            setTrashTotal(prev => (prev ?? 0) + 1);
            handleAuthError(err);
        }
    }

    async function handleHardDelete(task) {
        if (!window.confirm("Удалить задачу навсегда? Это действие нельзя отменить.")) return;
        setTrash(prev => prev.filter(t => t.id !== task.id));
        setTrashTotal(prev => (prev ?? 0) - 1);
        try {
            await apiRequest({ path: `/tasks/${task.id}/hard`, method: "DELETE", token });
        } catch (err) {
            setTrash(prev => [...prev, task].sort((a, b) => a.id - b.id));
            setTrashTotal(prev => (prev ?? 0) + 1);
            handleAuthError(err);
        }
    }

    const stats = useMemo(() => {
        const total = tasks.length;
        const done = tasks.filter(t => t.is_done).length;
        return { total, done, pending: total - done, percent: total > 0 ? Math.round((done / total) * 100) : 0 };
    }, [tasks]);

    const tasksTotalPages = Math.ceil((tasksTotal ?? 0) / PAGE_SIZE);
    const trashTotalPages = Math.ceil((trashTotal ?? 0) / PAGE_SIZE);

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
                    {mfaPending ? (
                        <form className="form" onSubmit={handleLogin2fa}>
                            <div className="form-group">
                                <label className="form-label">Код из приложения-аутентификатора</label>
                                <input
                                    name="code" placeholder="123456" required minLength={6} maxLength={11}
                                    inputMode="numeric" autoFocus
                                />
                                <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
                                    Нет доступа к приложению? Введите один из recovery-кодов вместо этого.
                                </div>
                            </div>
                            <button type="submit" className="btn btn-primary" style={{ marginTop: 4 }}>
                                Подтвердить
                            </button>
                            <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setMfaPending(null); setError(null); }}>
                                ← Назад
                            </button>
                            {error && <div className="alert">{error}</div>}
                        </form>
                    ) : (
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
                    )}
                </div>
            </div>
        );
    }

    if (mustChangePassword) {
        return <ForceChangePasswordScreen token={token} onDone={() => setMustChangePassword(false)} onLogout={() => { clearTokens(); setToken(null); }} />;
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
                        <button className="cmdk-trigger" onClick={() => setPaletteOpen(true)} title="Command Palette">
                            🔍 <span>Поиск</span> <kbd>Ctrl K</kbd>
                        </button>
                        <div className="user-chip"
                            ref={chipRef}
                            onClick={() => currentUserId != null && setProfileUserId(currentUserId)}
                            style={{ cursor: currentUserId != null ? "pointer" : "default" }}
                            onMouseEnter={() => {
                                const rect = chipRef.current?.getBoundingClientRect();
                                if (rect) setTooltipPos({
                                    top: rect.bottom + 8,
                                    right: window.innerWidth - rect.right,
                                });
                                setShowTooltip(true);
                            }}
                            onMouseLeave={() => setShowTooltip(false)}>
                            {currentUserId != null && <UserProfileAvatar userId={currentUserId} username={currentUsername} size={22} />}
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
                        <NotificationBell
                            token={token}
                            onOpenTask={(title) => { setTab("tasks"); setSearchQuery(title); }}
                        />
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
                            <button className={`tab-btn${tab === "timeline" ? " active" : ""}`} onClick={() => setTab("timeline")}>
                                <Icon d={ICONS.clock} /> Лента
                            </button>
                            <button className={`tab-btn${tab === "tasks" ? " active" : ""}`} onClick={() => setTab("tasks")}>
                                Задачи <span className="count-badge" style={{ visibility: tasksTotal ? "visible" : "hidden" }}>{tasksTotal || 0}</span>
                            </button>
                            <button className={`tab-btn${tab === "projects" ? " active" : ""}`} onClick={() => setTab("projects")}>
                                <Icon d={ICONS.folder} /> Проекты
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
                            <button className={`tab-btn${tab === "team" ? " active" : ""}`} onClick={() => setTab("team")}>
                                <Icon d={ICONS.user} /> Команда
                            </button>
                            <button className={`tab-btn${tab === "trash" ? " active" : ""}`} onClick={() => setTab("trash")}>
                                <Icon d={ICONS.trash} /> Корзина
                                <span className="count-badge" style={{ visibility: trashTotal ? "visible" : "hidden" }}>{trashTotal || 0}</span>
                            </button>
                            <button className={`tab-btn${tab === "tokens" || tab === "webhooks" || tab === "calendar" || tab === "2fa" ? " active" : ""}`} onClick={() => setTab("2fa")}>
                                <Icon d={ICONS.shield} /> Настройки
                            </button>
                        </div>
                    </div>
                </div>
            </header>

            <CommandPalette
                open={paletteOpen}
                onClose={() => setPaletteOpen(false)}
                token={token}
                setTab={setTab}
                setSearchQuery={setSearchQuery}
                setTheme={setTheme}
                onLogout={logout}
            />

            <ChatBubble token={token} currentUserId={currentUserId} wsEvent={chatWsEvent} />

            {show2faNudge && (
                <div className="alert" style={{
                    margin: "12px 16px 0", display: "flex", justifyContent: "space-between",
                    alignItems: "center", gap: 12, borderColor: "#f59e0b", background: "#f59e0b11",
                }}>
                    <span>
                        🔒 У вашей роли расширенные права — рекомендуем включить двухфакторную аутентификацию.
                    </span>
                    <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                        <button className="btn btn-sm btn-primary" onClick={() => { setTab("2fa"); setShow2faNudge(false); }}>
                            Настроить
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={() => setShow2faNudge(false)}>✕</button>
                    </div>
                </div>
            )}

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
                                        <div className="stat-value">{tasksTotal ?? "–"}</div>
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
                                            {tasksTotal == null
                                                ? "Загрузка…"
                                                : tasksTotal > 0
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
                                                    <option value="backlog">Очередь</option>
                                                    <option value="todo">Новые</option>
                                                    <option value="in_progress">В работе</option>
                                                    <option value="review">На проверке</option>
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
            {profileUserId != null ? (
                <UserProfilePage
                    userId={profileUserId}
                    token={token}
                    currentUserId={currentUserId}
                    onClose={() => setProfileUserId(null)}
                    onOpenTask={(title) => { setProfileUserId(null); setTab("tasks"); setSearchQuery(title); }}
                />
            ) : (
            <>
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
            {/* ── TIMELINE TAB ── */}
            {tab === "timeline" && (
                <div style={{ maxWidth: 720, margin: "0 auto", padding: "16px 16px 0" }}>
                    <TimelineTab token={token} />
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
            {/* ── TEAM TAB ── */}
            {tab === "team" && (
                <div style={{ maxWidth: 860, margin: "0 auto", padding: "16px 16px 0" }}>
                    <TeamTab token={token} />
                </div>
            )}
            {tab === "templates" && (
                <div>
                    <TemplatesTab token={token} />
                </div>
            )}
            {/* ── SETTINGS (Токены / Вебхуки / Календарь / 2FA) ── */}
            {(tab === "tokens" || tab === "webhooks" || tab === "calendar" || tab === "2fa") && (
                <div style={{ maxWidth: 860, margin: "0 auto", padding: "16px 16px 0" }}>
                    <div className="tab-bar" style={{ marginBottom: 16, display: "inline-flex" }}>
                        <button className={`tab-btn${tab === "2fa" ? " active" : ""}`} onClick={() => setTab("2fa")}>
                            🔒 Профиль и 2FA
                        </button>
                        <button className={`tab-btn${tab === "tokens" ? " active" : ""}`} onClick={() => setTab("tokens")}>
                            🔑 Токены
                        </button>
                        <button className={`tab-btn${tab === "webhooks" ? " active" : ""}`} onClick={() => setTab("webhooks")}>
                            <Icon d={ICONS.link} /> Вебхуки
                        </button>
                        <button className={`tab-btn${tab === "calendar" ? " active" : ""}`} onClick={() => setTab("calendar")}>
                            <Icon d={ICONS.calendar} /> Календарь
                        </button>
                    </div>
                    {tab === "2fa" && (
                        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                            <TwoFactorTab token={token} />
                            <ChangePasswordCard token={token} />
                        </div>
                    )}
                    {tab === "tokens" && <TokensTab token={token} />}
                    {tab === "webhooks" && <WebhooksTab token={token} />}
                    {tab === "calendar" && <CalendarTab token={token} />}
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
            </>
            )}
        </div>
    );
}

export default App;
