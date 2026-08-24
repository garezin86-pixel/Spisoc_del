import { useState, useEffect, useCallback, useRef } from "react";
import { apiRequest } from "../api";

export function NotificationBell({ token, onOpenTask }) {
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
