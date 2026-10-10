import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "../api";
import { Icon } from "./Icon";
import { Pagination } from "./Pagination";
import { ICONS } from "../constants/icons";
import {
    INTERACTION_LABELS, INTERACTION_TYPES, emptyToNull, formatDateTime, isoToLocalInput, localInputToIso,
} from "../constants/crm";
import { userName } from "../hooks/useUsersMap";

/**
 * История взаимодействий с клиентом. Права как на бэкенде:
 * добавляют admin, manager и ответственный за клиента (canEdit);
 * текст и контакт правят автор, ответственный, admin, manager;
 * тип и дату после создания меняют только admin и manager (canManage); удаляют только они.
 */
export function InteractionsPanel({ token, clientId, canEdit, canManage, currentUserId, usersById, onChanged }) {
    const [data, setData] = useState({ items: [], pages: 1 });
    const [page, setPage] = useState(1);
    const [contacts, setContacts] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [editing, setEditing] = useState(null); // null | "new" | id
    const [form, setForm] = useState(null);
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState(null);

    const load = useCallback(async () => {
        try {
            const res = await apiRequest({ path: `/clients/${clientId}/interactions?page=${page}&size=20`, token });
            setData({ items: res?.items ?? [], pages: res?.pages ?? 1 });
            setError(null);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }, [token, clientId, page]);

    useEffect(() => { load(); }, [load]);

    useEffect(() => {
        apiRequest({ path: `/clients/${clientId}/contacts`, token }).then(c => setContacts(c ?? [])).catch(() => setContacts([]));
    }, [token, clientId]);

    const contactName = id => contacts.find(c => c.id === id)?.name;
    const set = key => e => setForm(f => ({ ...f, [key]: e.target.value }));

    const startNew = () => {
        setForm({ type: "call", occurred_at: "", contact_id: "", summary: "" });
        setEditing("new");
        setFormError(null);
    };
    const startEdit = item => {
        setForm({ type: item.type, occurred_at: isoToLocalInput(item.occurred_at), contact_id: item.contact_id ?? "", summary: item.summary ?? "" });
        setEditing(item.id);
        setFormError(null);
    };

    const submit = async e => {
        e.preventDefault();
        setSaving(true);
        setFormError(null);
        try {
            if (editing === "new") {
                const body = { type: form.type, summary: emptyToNull(form.summary), contact_id: form.contact_id ? Number(form.contact_id) : null };
                const when = localInputToIso(form.occurred_at);
                if (when) body.occurred_at = when;
                await apiRequest({ path: `/clients/${clientId}/interactions`, method: "POST", token, body });
                setPage(1);
            } else {
                const original = data.items.find(i => i.id === editing);
                const body = { summary: emptyToNull(form.summary), contact_id: form.contact_id ? Number(form.contact_id) : null };
                if (canManage) { // процессные поля шлём только менеджеру и только если изменились
                    if (form.type !== original.type) body.type = form.type;
                    const when = localInputToIso(form.occurred_at);
                    if (when && new Date(when).getTime() !== new Date(original.occurred_at).getTime()) body.occurred_at = when;
                }
                await apiRequest({ path: `/clients/${clientId}/interactions/${editing}`, method: "PATCH", token, body });
            }
            setEditing(null);
            await load();
            await onChanged?.(); // «последний контакт» в карточке клиента
        } catch (err) {
            setFormError(err.message);
        } finally {
            setSaving(false);
        }
    };

    const remove = async item => {
        if (!window.confirm("Удалить запись о взаимодействии?")) return;
        try {
            await apiRequest({ path: `/clients/${clientId}/interactions/${item.id}`, method: "DELETE", token });
            await load();
            await onChanged?.();
        } catch (err) {
            setError(err.message);
        }
    };

    const processLocked = editing !== "new" && !canManage; // тип и дату при правке менять нельзя

    const renderForm = () => (
        <form onSubmit={submit} style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: 12, marginBottom: 10 }}>
            {formError && <div className="alert" style={{ marginBottom: 10 }}>{formError}</div>}
            <div className="form-two-col">
                <div className="form-group">
                    <label className="form-label">Тип</label>
                    <select className="form-input" value={form.type} onChange={set("type")} disabled={processLocked}>
                        {INTERACTION_TYPES.map(t => <option key={t.key} value={t.key}>{t.icon} {t.label}</option>)}
                    </select>
                </div>
                <div className="form-group">
                    <label className="form-label">Когда {editing === "new" && "(пусто — сейчас)"}</label>
                    <input className="form-input" type="datetime-local" value={form.occurred_at} onChange={set("occurred_at")} disabled={processLocked} />
                </div>
            </div>
            {processLocked && (
                <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 8 }}>Тип и дату после создания меняют только admin и manager</div>
            )}
            <div className="form-group">
                <label className="form-label">Контакт</label>
                <select className="form-input" value={form.contact_id} onChange={set("contact_id")}>
                    <option value="">—</option>
                    {contacts.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
            </div>
            <div className="form-group">
                <label className="form-label">О чём говорили</label>
                <textarea className="form-input" rows={3} value={form.summary} onChange={set("summary")} maxLength={5000} />
            </div>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>Отмена</button>
                <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>Сохранить</button>
            </div>
        </form>
    );

    if (loading) return <div style={{ color: "var(--text-muted)" }}>Загрузка…</div>;

    return (
        <div>
            {error && <div className="alert" style={{ marginBottom: 10 }}>{error}</div>}
            {canEdit && editing === null && (
                <button className="btn btn-primary btn-sm" style={{ marginBottom: 10 }} onClick={startNew}>
                    <Icon d={ICONS.plus} /> Взаимодействие
                </button>
            )}
            {editing === "new" && renderForm()}

            {data.items.length === 0 && editing !== "new" ? (
                <div className="empty-state"><div className="empty-icon">📞</div>Взаимодействий пока нет</div>
            ) : data.items.map(item => {
                const t = INTERACTION_LABELS[item.type] ?? { icon: "•", label: item.type };
                const canEditItem = canEdit || item.author_id === currentUserId;
                if (editing === item.id) return <div key={item.id}>{renderForm()}</div>;
                return (
                    <div key={item.id} style={{ display: "flex", gap: 12, padding: "10px 0", borderBottom: "1px solid var(--border)", alignItems: "flex-start" }}>
                        <div style={{ fontSize: 20, lineHeight: 1.2 }} title={t.label}>{t.icon}</div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 13, fontWeight: 600 }}>
                                {t.label}
                                {contactName(item.contact_id) && <span style={{ color: "var(--text-dim)", fontWeight: 400 }}> · {contactName(item.contact_id)}</span>}
                            </div>
                            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>
                                {formatDateTime(item.occurred_at)} · {userName(usersById, item.author_id)}
                            </div>
                            {item.summary && <div style={{ fontSize: 13, marginTop: 5, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{item.summary}</div>}
                        </div>
                        <div style={{ display: "flex", gap: 4 }}>
                            {canEditItem && <button className="btn btn-ghost btn-sm" onClick={() => startEdit(item)} title="Изменить"><Icon d={ICONS.edit} /></button>}
                            {canManage && <button className="btn btn-ghost btn-sm" onClick={() => remove(item)} title="Удалить"><Icon d={ICONS.trash} /></button>}
                        </div>
                    </div>
                );
            })}
            <Pagination page={page} totalPages={data.pages} onPage={setPage} />
        </div>
    );
}
