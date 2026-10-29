import { useState, useEffect, useCallback } from "react";
import { apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { Pagination } from "../components/Pagination";
import { AUDIT_ACTION_ICONS, formatAuditValue } from "../constants/audit";
import { ICONS } from "../constants/icons";
import { describeTimelineEvent } from "../utils/timeline";

const PAGE_SIZE = 30;

function dayLabel(date) {
    const today = new Date();
    const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
    if (date.toDateString() === today.toDateString()) return "Сегодня";
    if (date.toDateString() === yesterday.toDateString()) return "Вчера";
    return date.toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long" });
}

export function TimelineTab({ token }) {
    const [entries, setEntries] = useState([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

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

    // Группируем по дням, порядок записей сохраняем (сервер отдаёт от новых к старым)
    const days = [];
    entries.forEach(e => {
        const d = new Date(e.changed_at);
        const key = d.toDateString();
        let day = days[days.length - 1];
        if (!day || day.key !== key) { day = { key, label: dayLabel(d), items: [] }; days.push(day); }
        day.items.push(e);
    });

    return (
        <div className="cl-page">
            <div className="cl-head">
                <div>
                    <h1 className="cl-title">Лента активности</h1>
                    <div className="cl-sub">Последние изменения задач, комментариев и сделок — все пользователи</div>
                </div>
                <div className="cl-actions">
                    <button className="btn btn-ghost" onClick={() => load(page)} disabled={loading}>
                        <Icon d={ICONS.refresh} /> Обновить
                    </button>
                </div>
            </div>
            {error && <div className="alert">{error}</div>}
            {loading ? (
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
            ) : entries.length === 0 ? (
                <div className="empty-state"><div className="empty-icon">🕒</div>Пока ничего не происходило</div>
            ) : (
                <div className="card tl-card">
                    {days.map(day => (
                        <section key={day.key} className="tl-day">
                            <h2 className="tl-day-label">{day.label}</h2>
                            {day.items.map(e => (
                                <div key={`${e.entity_type}-${e.id}`} className="tl-item">
                                    <span className="tl-dot" aria-hidden="true">{AUDIT_ACTION_ICONS[e.action] || "📝"}</span>
                                    <div className="tl-body">
                                        <div className="tl-text">{describeTimelineEvent(e)}</div>
                                        {e.entity_type === "comments" && e.action === "create" && e.comment_preview && (
                                            <div className="tl-sub">«{e.comment_preview}»</div>
                                        )}
                                        {e.changes && e.changes.length > 0 && (
                                            <div className="tl-changes">
                                                {e.changes.map(c => (
                                                    <div key={c.field} className="tl-sub">
                                                        <span className="tl-field">{c.label}:</span>{" "}
                                                        <span className="tl-old">{formatAuditValue(c.field, c.old)}</span>
                                                        <span className="tl-new">{formatAuditValue(c.field, c.new)}</span>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                    <time className="tl-time" dateTime={e.changed_at}>
                                        {new Date(e.changed_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}
                                    </time>
                                </div>
                            ))}
                        </section>
                    ))}
                    <Pagination page={page} totalPages={totalPages} onPage={p => load(p)} />
                </div>
            )}
        </div>
    );
}

// ─── NotificationBell — колокольчик уведомлений в шапке ───────────────────
