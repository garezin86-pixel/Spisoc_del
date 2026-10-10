import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "../api";
import { ContactsPanel } from "../components/ContactsPanel";
import { Icon } from "../components/Icon";
import { InteractionsPanel } from "../components/InteractionsPanel";
import { ICONS } from "../constants/icons";
import { emptyToNull, formatDateTime } from "../constants/crm";
import { userName } from "../hooks/useUsersMap";
import { DealsBoard } from "./DealsBoard";

const SUBTABS = [
    { key: "overview", label: "Обзор" },
    { key: "contacts", label: "Контакты" },
    { key: "interactions", label: "Взаимодействия" },
    { key: "deals", label: "Сделки" },
];

/**
 * Карточка клиента. Править клиента могут admin, manager и ответственный; менять ответственного и удалять —
 * только admin и manager (как на бэкенде; сервер всё равно перепроверяет).
 */
export function ClientCard({ token, clientId, canManage, currentUserId, users, usersById, onBack, onDeleted }) {
    const [client, setClient] = useState(null);
    const [error, setError] = useState(null);
    const [sub, setSub] = useState("overview");
    const [editing, setEditing] = useState(false);
    const [form, setForm] = useState(null);
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState(null);

    const load = useCallback(async () => {
        try {
            setClient(await apiRequest({ path: `/clients/${clientId}`, token }));
            setError(null);
        } catch (e) {
            setError(e.message);
        }
    }, [token, clientId]);

    useEffect(() => { load(); }, [load]);

    if (error) {
        return (
            <div className="card">
                <button className="btn btn-ghost btn-sm" onClick={onBack}>← К списку</button>
                <div className="alert" style={{ marginTop: 12 }}>{error}</div>
            </div>
        );
    }
    if (!client) return <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>Загрузка…</div>;

    const canEdit = canManage || client.owner_id === currentUserId;
    const set = key => e => setForm(f => ({ ...f, [key]: e.target.value }));

    const startEdit = () => {
        setForm({
            name: client.name, phone: client.phone ?? "", email: client.email ?? "", address: client.address ?? "",
            notes: client.notes ?? "", owner_id: client.owner_id ?? "",
        });
        setFormError(null);
        setEditing(true);
    };

    const save = async e => {
        e.preventDefault();
        setSaving(true);
        setFormError(null);
        try {
            const body = {
                name: form.name.trim(),
                phone: emptyToNull(form.phone),
                email: emptyToNull(form.email),
                address: emptyToNull(form.address),
                notes: emptyToNull(form.notes),
            };
            if (canManage && form.owner_id !== "" && Number(form.owner_id) !== client.owner_id) body.owner_id = Number(form.owner_id);
            await apiRequest({ path: `/clients/${clientId}`, method: "PATCH", token, body });
            setEditing(false);
            await load();
        } catch (err) {
            setFormError(err.message);
        } finally {
            setSaving(false);
        }
    };

    const remove = async () => {
        if (!window.confirm(`Удалить клиента «${client.name}» вместе с контактами, взаимодействиями и сделками?`)) return;
        try {
            await apiRequest({ path: `/clients/${clientId}`, method: "DELETE", token });
            onDeleted();
        } catch (err) {
            setFormError(err.message);
        }
    };

    const row = (label, value) => (
        <div style={{ display: "flex", gap: 12, padding: "6px 0", borderBottom: "1px solid var(--border)", fontSize: 13 }}>
            <div style={{ width: 160, color: "var(--text-muted)", flexShrink: 0 }}>{label}</div>
            <div style={{ flex: 1, wordBreak: "break-word", whiteSpace: "pre-wrap" }}>{value || "—"}</div>
        </div>
    );

    return (
        <div className="card">
            <div className="section-header">
                <div>
                    <button className="btn btn-ghost btn-sm" onClick={onBack} style={{ marginBottom: 6 }}>← К списку</button>
                    <div className="section-title" style={{ fontSize: 18 }}>{client.name}</div>
                    <div className="section-sub">Ответственный: {userName(usersById, client.owner_id)}</div>
                </div>
            </div>

            <div className="tab-bar" style={{ marginBottom: 14 }}>
                {SUBTABS.map(t => (
                    <button key={t.key} className={`tab-btn${sub === t.key ? " active" : ""}`} onClick={() => setSub(t.key)}>{t.label}</button>
                ))}
            </div>

            {sub === "overview" && (editing ? (
                <form className="form" onSubmit={save}>
                    {formError && <div className="alert" style={{ marginBottom: 10 }}>{formError}</div>}
                    <div className="form-group">
                        <label className="form-label">Название</label>
                        <input className="form-input" value={form.name} onChange={set("name")} maxLength={200} required />
                    </div>
                    <div className="form-two-col">
                        <div className="form-group">
                            <label className="form-label">Телефон</label>
                            <input className="form-input" value={form.phone} onChange={set("phone")} maxLength={50} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">Email</label>
                            <input className="form-input" type="email" value={form.email} onChange={set("email")} maxLength={255} />
                        </div>
                    </div>
                    <div className="form-group">
                        <label className="form-label">Адрес</label>
                        <input className="form-input" value={form.address} onChange={set("address")} maxLength={500} />
                    </div>
                    {canManage && users.length > 0 && (
                        <div className="form-group">
                            <label className="form-label">Ответственный</label>
                            <select className="form-input" value={form.owner_id} onChange={set("owner_id")}>
                                {client.owner_id === null && <option value="">—</option>}
                                {users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                            </select>
                        </div>
                    )}
                    <div className="form-group">
                        <label className="form-label">Заметки</label>
                        <textarea className="form-input" rows={3} value={form.notes} onChange={set("notes")} maxLength={5000} />
                    </div>
                    <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Отмена</button>
                        <button type="submit" className="btn btn-primary btn-sm" disabled={saving || !form.name.trim()}>Сохранить</button>
                    </div>
                </form>
            ) : (
                <div>
                    {formError && <div className="alert" style={{ marginBottom: 10 }}>{formError}</div>}
                    {row("Телефон", client.phone)}
                    {row("Email", client.email)}
                    {row("Адрес", client.address)}
                    {row("Последний контакт", client.last_interaction_at ? formatDateTime(client.last_interaction_at) : "ещё не было")}
                    {row("Заметки", client.notes)}
                    <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                        {canEdit && <button className="btn btn-primary btn-sm" onClick={startEdit}><Icon d={ICONS.edit} /> Изменить</button>}
                        {canManage && <button className="btn btn-danger btn-sm" onClick={remove}><Icon d={ICONS.trash} /> Удалить</button>}
                    </div>
                </div>
            ))}

            {sub === "contacts" && <ContactsPanel token={token} clientId={clientId} canEdit={canEdit} />}

            {sub === "interactions" && (
                <InteractionsPanel
                    token={token} clientId={clientId} canEdit={canEdit} canManage={canManage}
                    currentUserId={currentUserId} usersById={usersById} onChanged={load}
                />
            )}

            {sub === "deals" && <DealsBoard token={token} clientId={clientId} canManage={canManage} currentUserId={currentUserId} />}
        </div>
    );
}
