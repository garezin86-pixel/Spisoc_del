import { useEffect, useState } from "react";
import { apiRequest } from "../api";
import { Modal } from "./Modal";
import { emptyToNull, formatDate, formatDateTime, formatMoney } from "../constants/crm";
import { userName } from "../hooks/useUsersMap";

/**
 * Карточка сделки: правка полей и история смены стадий.
 * Права (как на бэкенде): название и заметки правят ответственный по сделке, admin и manager;
 * сумму, ответственного и срок — только admin и manager; удаляет только admin/manager.
 */
export function DealModal({ deal, stages, users, usersById, token, canManage, currentUserId, onClose, onChanged }) {
    const [form, setForm] = useState({
        title: deal.title,
        notes: deal.notes ?? "",
        amount: deal.amount ?? "",
        expected_close_date: deal.expected_close_date ?? "",
        owner_id: deal.owner_id ?? "",
    });
    const [history, setHistory] = useState([]);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);

    const isOwner = deal.owner_id === currentUserId;
    const canEditRef = canManage || isOwner;
    const stageName = id => stages.find(s => s.id === id)?.name ?? `#${id}`;
    const set = key => e => setForm(f => ({ ...f, [key]: e.target.value }));

    useEffect(() => {
        let cancelled = false;
        apiRequest({ path: `/deals/${deal.id}/history`, token })
            .then(data => { if (!cancelled) setHistory(data ?? []); })
            .catch(() => { if (!cancelled) setHistory([]); });
        return () => { cancelled = true; };
    }, [deal.id, deal.stage_id, token]);

    const save = async e => {
        e.preventDefault();
        const body = {};
        const title = form.title.trim();
        if (title === "") { setError("Название не может быть пустым"); return; }
        if (title !== deal.title) body.title = title;
        if (emptyToNull(form.notes) !== (deal.notes ?? null)) body.notes = emptyToNull(form.notes);
        if (canManage) {
            const amount = form.amount === "" ? null : Number(form.amount);
            if (amount !== (deal.amount ?? null)) body.amount = amount;
            const date = form.expected_close_date || null;
            if (date !== (deal.expected_close_date ?? null)) body.expected_close_date = date;
            if (form.owner_id !== "" && Number(form.owner_id) !== deal.owner_id) body.owner_id = Number(form.owner_id);
        }
        if (Object.keys(body).length === 0) { onClose(); return; }
        setSaving(true);
        setError(null);
        try {
            await apiRequest({ path: `/deals/${deal.id}`, method: "PATCH", token, body });
            await onChanged();
            onClose();
        } catch (err) {
            setError(err.message);
        } finally {
            setSaving(false);
        }
    };

    const remove = async () => {
        if (!window.confirm(`Удалить сделку «${deal.title}»?`)) return;
        setSaving(true);
        setError(null);
        try {
            await apiRequest({ path: `/deals/${deal.id}`, method: "DELETE", token });
            await onChanged();
            onClose();
        } catch (err) {
            setError(err.message);
            setSaving(false);
        }
    };

    return (
        <Modal title={`Сделка #${deal.id}`} onClose={onClose} width={620}>
            {error && <div className="alert" style={{ marginBottom: 12 }}>{error}</div>}
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>
                Стадия: <b style={{ color: "var(--text)" }}>{stageName(deal.stage_id)}</b>
                {deal.closed_at && <> · закрыта {formatDateTime(deal.closed_at)}</>}
                {deal.lost_reason && <> · причина отказа: {deal.lost_reason}</>}
            </div>

            <form onSubmit={save}>
                <div className="form-group">
                    <label className="form-label">Название</label>
                    <input className="form-input" value={form.title} onChange={set("title")} disabled={!canEditRef} maxLength={200} />
                </div>
                <div className="form-two-col">
                    <div className="form-group">
                        <label className="form-label">Сумма</label>
                        <input className="form-input" type="number" min="0" step="0.01" value={form.amount}
                            onChange={set("amount")} disabled={!canManage} title={canManage ? "" : "Сумму меняют admin и manager"} />
                    </div>
                    <div className="form-group">
                        <label className="form-label">Ожидаемая дата закрытия</label>
                        <input className="form-input" type="date" value={form.expected_close_date}
                            onChange={set("expected_close_date")} disabled={!canManage} />
                    </div>
                </div>
                <div className="form-group">
                    <label className="form-label">Ответственный</label>
                    {canManage && users.length > 0 ? (
                        <select className="form-input" value={form.owner_id} onChange={set("owner_id")}>
                            {deal.owner_id === null && <option value="">—</option>}
                            {users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                        </select>
                    ) : (
                        <input className="form-input" value={userName(usersById, deal.owner_id)} disabled />
                    )}
                </div>
                <div className="form-group">
                    <label className="form-label">Заметки</label>
                    <textarea className="form-input" rows={3} value={form.notes} onChange={set("notes")} disabled={!canEditRef} maxLength={5000} />
                </div>
                <div style={{ display: "flex", gap: 8, justifyContent: "space-between" }}>
                    <div>
                        {canManage && <button type="button" className="btn btn-danger btn-sm" onClick={remove} disabled={saving}>Удалить</button>}
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>Закрыть</button>
                        {canEditRef && <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>Сохранить</button>}
                    </div>
                </div>
            </form>

            <div style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
                <div className="section-title" style={{ fontSize: 13, marginBottom: 8 }}>История стадий</div>
                {history.length === 0 ? (
                    <div style={{ color: "var(--text-muted)", fontSize: 12 }}>Стадия ещё не менялась</div>
                ) : history.map(h => (
                    <div key={h.id} style={{ fontSize: 12, padding: "4px 0", color: "var(--text-dim)" }}>
                        <b style={{ color: "var(--text)" }}>{h.from_stage_name ?? "—"} → {h.to_stage_name ?? "—"}</b>
                        {" · "}{h.username ?? "система"}{" · "}{formatDateTime(h.changed_at)}
                        {h.lost_reason && <> · причина: {h.lost_reason}</>}
                    </div>
                ))}
            </div>
            <div style={{ marginTop: 8, fontSize: 11, color: "var(--text-muted)" }}>
                Создана {formatDateTime(deal.created_at)}{deal.amount != null && <> · сумма {formatMoney(deal.amount)}</>}
                {deal.expected_close_date && <> · срок {formatDate(deal.expected_close_date)}</>}
            </div>
        </Modal>
    );
}
