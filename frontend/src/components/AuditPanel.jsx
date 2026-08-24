import { useState, useEffect } from "react";
import { apiRequest } from "../api";
import { AUDIT_ACTION_ICONS, AUDIT_ACTION_LABELS, AUDIT_FIELD_LABELS } from "../constants/audit";

export function AuditPanel({ taskId, token }) {
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
