import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "../api";
import { Icon } from "./Icon";
import { ICONS } from "../constants/icons";
import { emptyToNull } from "../constants/crm";

const EMPTY = { name: "", position: "", phone: "", email: "", notes: "" };

function ContactForm({ initial, onSubmit, onCancel, saving, error }) {
    const [form, setForm] = useState({ ...EMPTY, ...initial });
    const set = key => e => setForm(f => ({ ...f, [key]: e.target.value }));
    return (
        <form
            onSubmit={e => { e.preventDefault(); onSubmit(form); }}
            style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: 12, marginBottom: 10 }}
        >
            {error && <div className="alert" style={{ marginBottom: 10 }}>{error}</div>}
            <div className="form-two-col">
                <div className="form-group">
                    <label className="form-label">Имя</label>
                    <input className="form-input" value={form.name} onChange={set("name")} maxLength={200} required />
                </div>
                <div className="form-group">
                    <label className="form-label">Должность</label>
                    <input className="form-input" value={form.position} onChange={set("position")} maxLength={200} />
                </div>
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
                <label className="form-label">Заметки</label>
                <textarea className="form-input" rows={2} value={form.notes} onChange={set("notes")} maxLength={5000} />
            </div>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Отмена</button>
                <button type="submit" className="btn btn-primary btn-sm" disabled={saving || !form.name.trim()}>Сохранить</button>
            </div>
        </form>
    );
}

// Контактные лица клиента. Править может тот, кто правит клиента (canEdit), — так на бэкенде.
export function ContactsPanel({ token, clientId, canEdit }) {
    const [contacts, setContacts] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [adding, setAdding] = useState(false);
    const [editingId, setEditingId] = useState(null);
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState(null);

    const load = useCallback(async () => {
        try {
            setContacts(await apiRequest({ path: `/clients/${clientId}/contacts`, token }) ?? []);
            setError(null);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }, [token, clientId]);

    useEffect(() => { load(); }, [load]);

    const toBody = form => ({
        name: form.name.trim(),
        position: emptyToNull(form.position),
        phone: emptyToNull(form.phone),
        email: emptyToNull(form.email),
        notes: emptyToNull(form.notes),
    });

    const run = async (request, onOk) => {
        setSaving(true);
        setFormError(null);
        try {
            await request();
            onOk?.();
            await load();
        } catch (e) {
            setFormError(e.message);
        } finally {
            setSaving(false);
        }
    };

    const create = form => run(
        () => apiRequest({ path: `/clients/${clientId}/contacts`, method: "POST", token, body: toBody(form) }),
        () => setAdding(false),
    );
    const update = (id, form) => run(
        () => apiRequest({ path: `/clients/${clientId}/contacts/${id}`, method: "PATCH", token, body: toBody(form) }),
        () => setEditingId(null),
    );
    const remove = c => {
        if (!window.confirm(`Удалить контакт «${c.name}»?`)) return;
        run(() => apiRequest({ path: `/clients/${clientId}/contacts/${c.id}`, method: "DELETE", token }));
    };

    if (loading) return <div style={{ color: "var(--text-muted)" }}>Загрузка…</div>;
    if (error) return <div className="alert">{error}</div>;

    return (
        <div>
            {canEdit && !adding && (
                <button className="btn btn-primary btn-sm" style={{ marginBottom: 10 }} onClick={() => { setAdding(true); setEditingId(null); setFormError(null); }}>
                    <Icon d={ICONS.plus} /> Контакт
                </button>
            )}
            {adding && <ContactForm initial={{}} saving={saving} error={formError} onSubmit={create} onCancel={() => setAdding(false)} />}

            {contacts.length === 0 && !adding ? (
                <div className="empty-state"><div className="empty-icon">👤</div>Контактов нет</div>
            ) : contacts.map(c => editingId === c.id ? (
                <ContactForm key={c.id} initial={{ ...c, position: c.position ?? "", phone: c.phone ?? "", email: c.email ?? "", notes: c.notes ?? "" }}
                    saving={saving} error={formError} onSubmit={form => update(c.id, form)} onCancel={() => setEditingId(null)} />
            ) : (
                <div key={c.id} style={{ display: "flex", gap: 12, padding: "10px 0", borderBottom: "1px solid var(--border)", alignItems: "flex-start" }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 600 }}>{c.name}{c.position && <span style={{ color: "var(--text-muted)", fontWeight: 400 }}> · {c.position}</span>}</div>
                        <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 2 }}>
                            {[c.phone, c.email].filter(Boolean).join(" · ") || "Нет данных для связи"}
                        </div>
                        {c.notes && <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4, whiteSpace: "pre-wrap" }}>{c.notes}</div>}
                    </div>
                    {canEdit && (
                        <div style={{ display: "flex", gap: 4 }}>
                            <button className="btn btn-ghost btn-sm" onClick={() => { setEditingId(c.id); setAdding(false); setFormError(null); }} title="Изменить"><Icon d={ICONS.edit} /></button>
                            <button className="btn btn-ghost btn-sm" onClick={() => remove(c)} title="Удалить"><Icon d={ICONS.trash} /></button>
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
}
