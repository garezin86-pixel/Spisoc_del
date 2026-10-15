import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "../api";
import { EventFormModal } from "./EventFormModal";
import { Icon } from "./Icon";
import { Pagination } from "./Pagination";
import { ICONS } from "../constants/icons";
import { EVENT_STATUS_LABELS, INTERACTION_LABELS, emptyToNull, formatEventWhen } from "../constants/crm";
import { userName } from "../hooks/useUsersMap";

const STATUS_COLORS = { planned: "var(--accent)", done: "var(--green)", cancelled: "var(--text-muted)" };

/**
 * Запланированные встречи и звонки клиента. Права как на бэкенде: планируют admin, manager и ответственный за клиента
 * (canEdit); менять, отменять и отмечать состоявшимися — admin, manager и ответственный за событие; удалять — admin и
 * manager (canManage). «Состоялась» превращает событие во взаимодействие (в одной транзакции на сервере).
 */
export function ScheduledEventsPanel({ token, clientId, canEdit, canManage, currentUserId, users, usersById, onChanged }) {
    const [data, setData] = useState({ items: [], pages: 1 });
    const [page, setPage] = useState(1);
    const [showCancelled, setShowCancelled] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [modal, setModal] = useState(null); // null | { event? }
    const [completing, setCompleting] = useState(null); // { id, summary }
    const [busy, setBusy] = useState(false);

    const load = useCallback(async () => {
        try {
            const qs = new URLSearchParams({ page, size: 20 });
            if (showCancelled) qs.set("status", "cancelled");
            const res = await apiRequest({ path: `/clients/${clientId}/events?${qs}`, token });
            setData({ items: res?.items ?? [], pages: res?.pages ?? 1 });
            setError(null);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }, [token, clientId, page, showCancelled]);

    useEffect(() => { load(); }, [load]);

    const canAct = ev => canManage || ev.assignee_id === currentUserId;

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

    const complete = ev => run(async () => {
        await apiRequest({ path: `/events/${ev.id}/complete`, method: "POST", token, body: { summary: emptyToNull(completing?.summary ?? "") } });
        setCompleting(null);
    });
    const setStatus = (ev, status) => run(() => apiRequest({ path: `/events/${ev.id}`, method: "PATCH", token, body: { status } }));
    const remove = ev => {
        if (!window.confirm("Удалить событие?")) return Promise.resolve();
        return run(() => apiRequest({ path: `/events/${ev.id}`, method: "DELETE", token }));
    };

    // запланированные сверху (ближайшие первыми), состоявшиеся ниже (свежие первыми)
    const items = [...data.items].sort((a, b) => {
        const planned = x => (x.status === "planned" ? 0 : 1);
        if (planned(a) !== planned(b)) return planned(a) - planned(b);
        const diff = new Date(a.starts_at) - new Date(b.starts_at);
        return a.status === "planned" ? diff : -diff;
    });

    if (loading) return <div style={{ color: "var(--text-muted)" }}>Загрузка…</div>;

    return (
        <div>
            {error && <div className="alert" style={{ marginBottom: 10 }}>{error}</div>}
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10, flexWrap: "wrap" }}>
                {canEdit && (
                    <button className="btn btn-primary btn-sm" onClick={() => setModal({})}>
                        <Icon d={ICONS.plus} /> Запланировать
                    </button>
                )}
                <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: "pointer" }}>
                    <input type="checkbox" checked={showCancelled} onChange={e => { setShowCancelled(e.target.checked); setPage(1); }} />
                    Только отменённые
                </label>
            </div>

            {items.length === 0 ? (
                <div className="empty-state"><div className="empty-icon">📅</div>{showCancelled ? "Отменённых событий нет" : "Запланированных встреч и звонков нет"}</div>
            ) : items.map(ev => {
                const t = INTERACTION_LABELS[ev.type] ?? { icon: "•", label: ev.type };
                const late = ev.status === "planned" && new Date(ev.starts_at) < new Date();
                return (
                    <div key={ev.id} style={{ padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
                        <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                            <div style={{ fontSize: 20, lineHeight: 1.2 }} title={t.label}>{t.icon}</div>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 13, fontWeight: 600 }}>
                                    {ev.title || t.label}
                                    <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 600, color: STATUS_COLORS[ev.status] }}>{EVENT_STATUS_LABELS[ev.status]}</span>
                                    {late && <span style={{ marginLeft: 8, fontSize: 11, color: "var(--red)" }}>время прошло — отметьте итог или отмените</span>}
                                </div>
                                <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>
                                    {formatEventWhen(ev.starts_at, ev.duration_minutes)} · {userName(usersById, ev.assignee_id)}
                                </div>
                                {ev.notes && <div style={{ fontSize: 13, marginTop: 5, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{ev.notes}</div>}
                            </div>
                            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", justifyContent: "flex-end" }}>
                                {ev.status === "planned" && canAct(ev) && (
                                    <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => setCompleting({ id: ev.id, summary: ev.notes ?? "" })}>Состоялась</button>
                                )}
                                {ev.status === "planned" && canAct(ev) && (
                                    <button className="btn btn-ghost btn-sm" onClick={() => setModal({ event: ev })} title="Изменить"><Icon d={ICONS.edit} /></button>
                                )}
                                {ev.status === "planned" && canAct(ev) && (
                                    <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setStatus(ev, "cancelled")}>Отменить</button>
                                )}
                                {ev.status === "cancelled" && canAct(ev) && (
                                    <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setStatus(ev, "planned")}>Вернуть</button>
                                )}
                                {canManage && (
                                    <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => remove(ev)} title="Удалить"><Icon d={ICONS.trash} /></button>
                                )}
                            </div>
                        </div>
                        {completing?.id === ev.id && (
                            <div style={{ marginTop: 10, padding: 10, background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
                                <label className="form-label">Итог — станет записью в «Взаимодействиях» (время — сейчас)</label>
                                <textarea className="form-input" rows={3} maxLength={5000} autoFocus value={completing.summary} onChange={e => setCompleting(c => ({ ...c, summary: e.target.value }))} />
                                <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 8 }}>
                                    <button className="btn btn-ghost btn-sm" onClick={() => setCompleting(null)}>Отмена</button>
                                    <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => complete(ev)}>Сохранить</button>
                                </div>
                            </div>
                        )}
                    </div>
                );
            })}
            <Pagination page={page} totalPages={data.pages} onPage={setPage} />

            {modal && (
                <EventFormModal
                    token={token} clientId={clientId} event={modal.event ?? null} users={users} currentUserId={currentUserId}
                    onClose={() => setModal(null)}
                    onSaved={async () => { await load(); await onChanged?.(); }}
                />
            )}
        </div>
    );
}
