import { useState, useEffect, useCallback } from "react";
import { apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { Pagination } from "../components/Pagination";
import { AUDIT_ACTION_ICONS } from "../constants/audit";
import { localizeIsoDateTime } from "../constants/crm";
import { ICONS } from "../constants/icons";
import { describeTimelineEvent } from "../utils/timeline";

export function TimelineTab({ token }) {
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
                    <div className="section-sub">Последние изменения задач, комментариев и сделок — все пользователи</div>
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
                                                    {localizeIsoDateTime(c.old)}
                                                </span>
                                                <span style={{ color: "var(--accent-light)" }}>{localizeIsoDateTime(c.new)}</span>
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
