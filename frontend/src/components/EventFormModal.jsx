import { useEffect, useState } from "react";
import { apiRequest } from "../api";
import { Modal } from "./Modal";
import { EVENT_TYPES, defaultEventStart, emptyToNull, isoToLocalInput, localInputToIso } from "../constants/crm";

/**
 * Планирование встречи/звонка: создание (event = null) или правка. Если clientId не задан (календарь), клиента
 * выбирают поиском. Права проверяет сервер: создают admin, manager и ответственный за клиента; меняют — admin, manager и
 * ответственный за событие; ошибку (403 и т.п.) показываем в форме.
 */
export function EventFormModal({ token, event = null, clientId = null, defaultDay = null, users, currentUserId, onClose, onSaved }) {
    const [client, setClient] = useState(clientId ? { id: clientId, name: event?.client_name ?? "" } : null);
    const [search, setSearch] = useState("");
    const [found, setFound] = useState([]);
    const [contacts, setContacts] = useState([]);
    const [form, setForm] = useState(() => event ? {
        type: event.type,
        starts_at: isoToLocalInput(event.starts_at),
        duration_minutes: event.duration_minutes ?? "",
        title: event.title ?? "",
        notes: event.notes ?? "",
        contact_id: event.contact_id ?? "",
        assignee_id: event.assignee_id ?? currentUserId ?? "",
    } : {
        type: "meeting",
        starts_at: defaultEventStart(defaultDay),
        duration_minutes: "",
        title: "",
        notes: "",
        contact_id: "",
        assignee_id: currentUserId ?? "",
    });
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    const set = key => e => setForm(f => ({ ...f, [key]: e.target.value }));

    // поиск клиента с задержкой (только когда клиент ещё не выбран)
    useEffect(() => {
        if (client) return undefined;
        const timer = setTimeout(() => {
            const qs = new URLSearchParams({ page: 1, size: 8 });
            if (search.trim()) qs.set("search", search.trim());
            apiRequest({ path: `/clients?${qs}`, token }).then(r => setFound(r?.items ?? [])).catch(() => setFound([]));
        }, 250);
        return () => clearTimeout(timer);
    }, [client, search, token]);

    useEffect(() => {
        if (!client) { setContacts([]); return; }
        apiRequest({ path: `/clients/${client.id}/contacts`, token }).then(c => setContacts(c ?? [])).catch(() => setContacts([]));
    }, [client, token]);

    const submit = async e => {
        e.preventDefault();
        if (!client) { setError("Выберите клиента"); return; }
        const startsAt = localInputToIso(form.starts_at);
        if (!startsAt) { setError("Укажите дату и время"); return; }
        const duration = form.duration_minutes === "" ? null : Number(form.duration_minutes);
        if (duration !== null && (!Number.isInteger(duration) || duration < 1 || duration > 1440)) {
            setError("Длительность — целое число минут от 1 до 1440");
            return;
        }
        const body = {
            type: form.type,
            starts_at: startsAt,
            duration_minutes: duration,
            title: emptyToNull(form.title),
            notes: emptyToNull(form.notes),
            contact_id: form.contact_id ? Number(form.contact_id) : null,
            assignee_id: form.assignee_id ? Number(form.assignee_id) : currentUserId,
        };
        setSaving(true);
        setError(null);
        try {
            const saved = event
                ? await apiRequest({ path: `/events/${event.id}`, method: "PATCH", token, body })
                : await apiRequest({ path: `/clients/${client.id}/events`, method: "POST", token, body });
            await onSaved?.(saved);
            onClose();
        } catch (err) {
            setError(err.message);
            setSaving(false);
        }
    };

    return (
        <Modal title={event ? "Изменить событие" : "Запланировать встречу или звонок"} onClose={onClose} width={520}>
            <form className="form" onSubmit={submit}>
                {error && <div className="alert" style={{ marginBottom: 10 }}>{error}</div>}

                <div className="form-group">
                    <label className="form-label">Клиент</label>
                    {client ? (
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <span style={{ fontWeight: 600 }}>{client.name || `#${client.id}`}</span>
                            {!clientId && !event && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setClient(null)}>Сменить</button>}
                        </div>
                    ) : (
                        <>
                            <input className="form-input" placeholder="Найти клиента…" value={search} onChange={e => setSearch(e.target.value)} autoFocus />
                            <div style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 6, maxHeight: 180, overflowY: "auto" }}>
                                {found.map(c => (
                                    <button key={c.id} type="button" className="home-row" onClick={() => setClient({ id: c.id, name: c.name })}>
                                        <span className="home-row-main"><span className="home-row-title">{c.name}</span></span>
                                    </button>
                                ))}
                                {found.length === 0 && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Ничего не найдено</div>}
                            </div>
                        </>
                    )}
                </div>

                <div className="form-two-col">
                    <div className="form-group">
                        <label className="form-label">Тип</label>
                        <select className="form-input" value={form.type} onChange={set("type")}>
                            {EVENT_TYPES.map(t => <option key={t.key} value={t.key}>{t.icon} {t.label}</option>)}
                        </select>
                    </div>
                    <div className="form-group">
                        <label className="form-label">Когда</label>
                        <input className="form-input" type="datetime-local" value={form.starts_at} onChange={set("starts_at")} required />
                    </div>
                </div>

                <div className="form-two-col">
                    <div className="form-group">
                        <label className="form-label">Длительность, мин</label>
                        <input className="form-input" type="number" min={1} max={1440} value={form.duration_minutes} onChange={set("duration_minutes")} placeholder="необязательно" />
                    </div>
                    <div className="form-group">
                        <label className="form-label">Ответственный</label>
                        <select className="form-input" value={form.assignee_id} onChange={set("assignee_id")}>
                            {users.length === 0 && <option value={form.assignee_id}>Я</option>}
                            {users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                        </select>
                    </div>
                </div>

                <div className="form-group">
                    <label className="form-label">Тема</label>
                    <input className="form-input" value={form.title} onChange={set("title")} maxLength={200} placeholder="Например: демо продукта" />
                </div>
                <div className="form-group">
                    <label className="form-label">Контакт</label>
                    <select className="form-input" value={form.contact_id} onChange={set("contact_id")} disabled={!client}>
                        <option value="">—</option>
                        {contacts.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                </div>
                <div className="form-group">
                    <label className="form-label">Заметки (станут итогом, если не указать другой)</label>
                    <textarea className="form-input" rows={3} value={form.notes} onChange={set("notes")} maxLength={5000} />
                </div>

                <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>Отмена</button>
                    <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>{saving ? "Сохраняю…" : "Сохранить"}</button>
                </div>
            </form>
        </Modal>
    );
}
