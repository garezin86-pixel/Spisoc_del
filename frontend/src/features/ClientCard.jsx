import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "../api";
import { ContactsPanel } from "../components/ContactsPanel";
import { Icon } from "../components/Icon";
import { InteractionsPanel } from "../components/InteractionsPanel";
import { ClientTasksPanel } from "../components/ClientTasksPanel";
import { ScheduledEventsPanel } from "../components/ScheduledEventsPanel";
import { ICONS } from "../constants/icons";
import { PersonFields } from "../components/PersonFields";
import {
    CLIENT_TYPES, ageFromDate, clientTypeInfo, emptyToNull, formatDate, formatDateTime, genderLabel, isContactDue, plural, todayInput,
} from "../constants/crm";
import { userName } from "../hooks/useUsersMap";
import { DealsBoard } from "./DealsBoard";

const SUBTABS = [
    { key: "overview", label: "Обзор" },
    { key: "contacts", label: "Контакты" },
    { key: "interactions", label: "Взаимодействия" },
    { key: "events", label: "Встречи" },
    { key: "tasks", label: "Задачи" },
    { key: "deals", label: "Сделки" },
];

/**
 * Карточка клиента. Править клиента могут admin, manager и ответственный; менять ответственного и удалять —
 * только admin и manager (как на бэкенде; сервер всё равно перепроверяет).
 */
export function ClientCard({ token, clientId, canManage, currentUserId, users, usersById, onBack, onDeleted, refreshSignal = 0 }) {
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
    // Ассистент что-то изменил: перечитываем карточку; панели вкладок перемонтируются по key={refreshSignal}
    useEffect(() => { if (refreshSignal) load(); }, [refreshSignal]); // eslint-disable-line react-hooks/exhaustive-deps

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
            name: client.name, client_type: client.client_type ?? "company", birth_date: client.birth_date ?? "", gender: client.gender ?? "", phone: client.phone ?? "", email: client.email ?? "", address: client.address ?? "",
            notes: client.notes ?? "", owner_id: client.owner_id ?? "", next_contact_at: client.next_contact_at ?? "",
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
                client_type: form.client_type,
                ...(form.client_type === "person" ? { birth_date: form.birth_date || null, gender: form.gender || null } : {}),
                phone: emptyToNull(form.phone),
                email: emptyToNull(form.email),
                address: emptyToNull(form.address),
                notes: emptyToNull(form.notes),
                next_contact_at: form.next_contact_at || null,
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

    // «Связались»: напоминание больше не нужно — дату очищаем (новую можно поставить в «Изменить»)
    const markContacted = async () => {
        setFormError(null);
        try {
            await apiRequest({ path: `/clients/${clientId}`, method: "PATCH", token, body: { next_contact_at: null } });
            await load();
        } catch (err) {
            setFormError(err.message);
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
        <div className="cl-kv">
            <div className="cl-kv-label">{label}</div>
            <div className="cl-kv-value">{value || "—"}</div>
        </div>
    );

    const typeInfo = clientTypeInfo(client.client_type);
    const due = client.next_contact_at && isContactDue(client.next_contact_at);

    return (
        <div className="cl-page">
            <nav className="cl-crumbs" aria-label="Путь">
                <button type="button" className="cl-crumb-link" onClick={onBack}>Клиенты</button>
                <span aria-hidden="true">/</span>
                <span aria-current="page">{client.name}</span>
            </nav>

            <div className="cl-head">
                <div className="cl-head-main">
                    <div className="cl-avatar cl-avatar--lg" title={typeInfo.label}>{(client.name || "?").trim().charAt(0).toUpperCase()}</div>
                    <div>
                        <h1 className="cl-title">{client.name}</h1>
                        <div className="cl-sub">{typeInfo.icon} {typeInfo.label} · Ответственный: {userName(usersById, client.owner_id)}{due && <span className="cl-pill cl-pill--due" style={{ marginLeft: 8 }}>пора связаться</span>}</div>
                    </div>
                </div>
                <div className="cl-actions">
                    <button className="btn btn-ghost" onClick={onBack}>← К списку</button>
                    {canEdit && <button className="btn btn-primary" onClick={() => { setSub("overview"); startEdit(); }}><Icon d={ICONS.edit} /> Изменить</button>}
                    {canManage && <button className="btn btn-danger" onClick={remove}><Icon d={ICONS.trash} /> Удалить</button>}
                </div>
            </div>

            <div className="cl-tabs" role="tablist" aria-label="Разделы клиента">
                {SUBTABS.map(t => (
                    <button key={t.key} type="button" role="tab" aria-selected={sub === t.key} className={`cl-tab${sub === t.key ? " active" : ""}`} onClick={() => setSub(t.key)}>{t.label}</button>
                ))}
            </div>

            <div className="card cl-body">
            {sub === "overview" && (editing ? (
                <form className="form" onSubmit={save}>
                    {formError && <div className="alert" style={{ marginBottom: 10 }}>{formError}</div>}
                    <div className="form-group">
                        <label className="form-label">Тип клиента</label>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                            {CLIENT_TYPES.map(t => (
                                <button
                                    key={t.key} type="button" onClick={() => setForm(f => ({ ...f, client_type: t.key }))}
                                    className={`btn btn-sm ${form.client_type === t.key ? "btn-primary" : "btn-ghost"}`}
                                >{t.icon} {t.label}</button>
                            ))}
                        </div>
                    </div>
                    <div className="form-group">
                        <label className="form-label">{clientTypeInfo(form.client_type).nameLabel}</label>
                        <input className="form-input" value={form.name} onChange={set("name")} maxLength={200} required />
                    </div>
                    {form.client_type === "person" && <PersonFields form={form} set={set} />}
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
                        <label className="form-label">Связаться снова (напомним ответственному в этот день)</label>
                        <input type="date" min={todayInput()} value={form.next_contact_at} onChange={set("next_contact_at")} />
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
                    <div className="cl-grid">
                        <section className="cl-panel">
                            <h3 className="cl-panel-title">Основное</h3>
                            {client.client_type === "person" && row("Дата рождения", client.birth_date ? (() => {
                                const age = ageFromDate(client.birth_date);
                                return `${formatDate(client.birth_date)}${age !== null ? ` · ${age} ${plural(age, "год", "года", "лет")}` : ""}`;
                            })() : null)}
                            {client.client_type === "person" && row("Пол", genderLabel(client.gender))}
                            {row("Телефон", client.phone)}
                            {row("Email", client.email)}
                            {row("Адрес", client.address)}
                        </section>
                        <section className="cl-panel">
                            <h3 className="cl-panel-title">Связь с клиентом</h3>
                            {row("Последний контакт", client.last_interaction_at ? formatDateTime(client.last_interaction_at) : "ещё не было")}
                            {row("Связаться снова", client.next_contact_at ? (
                                <span className="cl-inline">
                                    <span style={{ color: due ? "var(--red)" : "inherit", fontWeight: due ? 600 : 400 }}>
                                        {formatDate(client.next_contact_at)}{due && " — пора связаться"}
                                    </span>
                                    {canEdit && (
                                        <button className="btn btn-ghost btn-sm" onClick={markContacted} title="Убрать напоминание">Связались</button>
                                    )}
                                </span>
                            ) : null)}
                            {row("Заметки", client.notes)}
                        </section>
                    </div>
                </div>
            ))}

            {sub === "contacts" && <ContactsPanel key={refreshSignal} token={token} clientId={clientId} canEdit={canEdit} />}

            {sub === "interactions" && (
                <InteractionsPanel key={refreshSignal}
                    token={token} clientId={clientId} canEdit={canEdit} canManage={canManage}
                    currentUserId={currentUserId} usersById={usersById} onChanged={load}
                />
            )}

            {sub === "events" && (
                <ScheduledEventsPanel key={refreshSignal}
                    token={token} clientId={clientId} canEdit={canEdit} canManage={canManage}
                    currentUserId={currentUserId} users={users} usersById={usersById} onChanged={load}
                />
            )}

            {sub === "tasks" && (
                <ClientTasksPanel key={refreshSignal} token={token} clientId={clientId} users={users} currentUserId={currentUserId} />
            )}

            {sub === "deals" && <DealsBoard key={refreshSignal} token={token} clientId={clientId} canManage={canManage} currentUserId={currentUserId} />}
            </div>
        </div>
    );
}
