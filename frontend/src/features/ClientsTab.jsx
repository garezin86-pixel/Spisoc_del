import { useCallback, useEffect, useState } from "react";
import { apiRequest, downloadFile } from "../api";
import { Icon } from "../components/Icon";
import { Pagination } from "../components/Pagination";
import { ICONS } from "../constants/icons";
import { PersonFields } from "../components/PersonFields";
import { CLIENT_TYPES, clientTypeInfo, emptyToNull, formatDate, isContactDue, plural } from "../constants/crm";
import { userName, useUsersMap } from "../hooks/useUsersMap";
import { ClientCard } from "./ClientCard";
import { ClientImportModal } from "../components/ClientImportModal";

const EMPTY_FORM = { name: "", client_type: "company", birth_date: "", gender: "", phone: "", email: "", address: "", notes: "", owner_id: "" };

// Клиенты: список с поиском и пагинацией + карточка клиента. Создавать клиентов могут admin и manager.
export function ClientsTab({ token, canManage, currentUserId, initialClientId = null, onSelectedChange, refreshSignal = 0 }) {
    const { users, usersById } = useUsersMap(token);
    const [selectedId, setSelectedId] = useState(initialClientId); // с главной можно сразу открыть карточку клиента

    // Просят открыть другую карточку, пока вкладка уже открыта (например, «открой клиента X» в панели ассистента)
    useEffect(() => {
        if (initialClientId) setSelectedId(initialClientId);
    }, [initialClientId]);

    // Сообщаем наверх, какая карточка открыта (ассистент берёт её как контекст); при уходе с вкладки — «ничего»
    useEffect(() => {
        onSelectedChange?.(selectedId);
        return () => onSelectedChange?.(null);
    }, [selectedId, onSelectedChange]);
    const [data, setData] = useState({ items: [], total: 0, pages: 1 });
    const [page, setPage] = useState(1);
    const [search, setSearch] = useState("");
    const [query, setQuery] = useState("");
    const [onlyDue, setOnlyDue] = useState(false);
    const [onlyMine, setOnlyMine] = useState(false);
    const [typeFilter, setTypeFilter] = useState(""); // "" — все, "company" — B2B, "person" — B2C
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [showCreate, setShowCreate] = useState(false);
    const [showImport, setShowImport] = useState(false);
    const [exporting, setExporting] = useState(false);
    const [form, setForm] = useState(EMPTY_FORM);
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState(null);

    // поиск с задержкой, чтобы не слать запрос на каждую букву
    useEffect(() => {
        const timer = setTimeout(() => { setQuery(search.trim()); setPage(1); }, 300);
        return () => clearTimeout(timer);
    }, [search]);

    const exportCsv = async () => {
        setExporting(true);
        try {
            const qs = new URLSearchParams();
            if (query) qs.set("search", query);
            if (onlyDue) qs.set("contact_due", "true");
            if (onlyMine && currentUserId) qs.set("owner_id", currentUserId);
            if (typeFilter) qs.set("client_type", typeFilter);
            await downloadFile({ path: `/clients/export?${qs}`, token, fallbackName: "clients_export.csv" });
            setError(null);
        } catch (e) {
            setError(e.message);
        } finally {
            setExporting(false);
        }
    };

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const qs = new URLSearchParams({ page, size: 20 });
            if (query) qs.set("search", query);
            if (onlyDue) qs.set("contact_due", "true");
            if (onlyMine && currentUserId) qs.set("owner_id", currentUserId);
            if (typeFilter) qs.set("client_type", typeFilter);
            const res = await apiRequest({ path: `/clients?${qs}`, token });
            setData({ items: res?.items ?? [], total: res?.total ?? 0, pages: res?.pages ?? 1 });
            setError(null);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }, [token, page, query, onlyDue, onlyMine, typeFilter, currentUserId]);

    useEffect(() => { if (token) load(); }, [token, load]);

    const set = key => e => setForm(f => ({ ...f, [key]: e.target.value }));

    const create = async e => {
        e.preventDefault();
        setSaving(true);
        setFormError(null);
        try {
            const body = {
                name: form.name.trim(),
                client_type: form.client_type,
                phone: emptyToNull(form.phone),
                email: emptyToNull(form.email),
                address: emptyToNull(form.address),
                notes: emptyToNull(form.notes),
            };
            if (form.owner_id !== "") body.owner_id = Number(form.owner_id);
            if (form.client_type === "person") {
                if (form.birth_date) body.birth_date = form.birth_date;
                if (form.gender) body.gender = form.gender;
            }
            const created = await apiRequest({ path: "/clients", method: "POST", token, body });
            setForm(EMPTY_FORM);
            setShowCreate(false);
            setSelectedId(created.id);
        } catch (err) {
            setFormError(err.message);
        } finally {
            setSaving(false);
        }
    };

    if (selectedId !== null) {
        const back = () => { setSelectedId(null); load(); };
        return (
            <ClientCard
                token={token} clientId={selectedId} refreshSignal={refreshSignal} canManage={canManage} currentUserId={currentUserId}
                users={users} usersById={usersById} onBack={back} onDeleted={back}
            />
        );
    }

    return (
        <div className="card">
            <div className="section-header">
                <div>
                    <div className="section-title"><Icon d={ICONS.user} size={15} /> Клиенты</div>
                    <div className="section-sub">{data.total > 0 ? `${data.total} ${plural(data.total, "клиент", "клиента", "клиентов")}` : "Нет клиентов"}</div>
                </div>
                {canManage && (
                    <div style={{ display: "flex", gap: 8 }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => setShowImport(true)}>Импорт</button>
                        <button className="btn btn-ghost btn-sm" onClick={exportCsv} disabled={exporting} title="Выгрузить клиентов с текущими фильтрами в CSV">
                            {exporting ? "Экспорт…" : "Экспорт"}
                        </button>
                        <button className="btn btn-primary btn-sm" onClick={() => { setShowCreate(v => !v); setFormError(null); }}>
                            <Icon d={ICONS.plus} /> Клиент
                        </button>
                    </div>
                )}
            </div>

            {showImport && (
                <ClientImportModal token={token} onClose={() => setShowImport(false)} onImported={() => { setPage(1); load(); }} />
            )}

            {showCreate && (
                <form className="form" onSubmit={create} style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: 12, marginBottom: 14 }}>
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
                        <input
                            className="form-input" value={form.name} onChange={set("name")} maxLength={200} required autoFocus
                            placeholder={clientTypeInfo(form.client_type).namePlaceholder}
                        />
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
                        <label className="form-label">Адрес</label>
                        <input className="form-input" value={form.address} onChange={set("address")} maxLength={500} />
                    </div>
                    <div className="form-group">
                        <label className="form-label">Ответственный (пусто — я)</label>
                        <select className="form-input" value={form.owner_id} onChange={set("owner_id")}>
                            <option value="">Я</option>
                            {users.filter(u => u.id !== currentUserId).map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                        </select>
                    </div>
                    <div className="form-group">
                        <label className="form-label">Заметки</label>
                        <textarea className="form-input" rows={2} value={form.notes} onChange={set("notes")} maxLength={5000} />
                    </div>
                    <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowCreate(false)}>Отмена</button>
                        <button type="submit" className="btn btn-primary btn-sm" disabled={saving || !form.name.trim()}>Создать</button>
                    </div>
                </form>
            )}

            <input
                className="form-input" placeholder="Поиск по названию, телефону, email…" value={search}
                onChange={e => setSearch(e.target.value)} style={{ marginBottom: 10 }}
            />
            <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
                {[{ key: "", label: "Все" }, ...CLIENT_TYPES.map(t => ({ key: t.key, label: `${t.icon} ${t.short === "B2B" ? "Компании" : "Люди"} (${t.short})` }))].map(opt => (
                    <button
                        key={opt.key} type="button" onClick={() => { setTypeFilter(opt.key); setPage(1); }}
                        className={`btn btn-sm ${typeFilter === opt.key ? "btn-primary" : "btn-ghost"}`}
                    >{opt.label}</button>
                ))}
            </div>
            <div style={{ display: "flex", gap: 16, marginBottom: 12, fontSize: 13 }}>
                <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", width: "auto" }}>
                    <input type="checkbox" style={{ width: "auto" }} checked={onlyDue} onChange={e => { setOnlyDue(e.target.checked); setPage(1); }} />
                    Пора связаться
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", width: "auto" }}>
                    <input type="checkbox" style={{ width: "auto" }} checked={onlyMine} onChange={e => { setOnlyMine(e.target.checked); setPage(1); }} />
                    Мои клиенты
                </label>
            </div>

            {error ? (
                <div className="alert">{error}</div>
            ) : loading ? (
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
            ) : data.items.length === 0 ? (
                <div className="empty-state"><div className="empty-icon">🏢</div>{query ? "Ничего не найдено" : "Клиентов пока нет"}</div>
            ) : (
                <div>
                    {data.items.map(c => (
                        <div
                            key={c.id} onClick={() => setSelectedId(c.id)}
                            style={{ display: "flex", gap: 12, padding: "10px 4px", borderBottom: "1px solid var(--border)", cursor: "pointer", alignItems: "center" }}
                        >
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontWeight: 600 }}><span title={clientTypeInfo(c.client_type).label}>{clientTypeInfo(c.client_type).icon}</span> {c.name}</div>
                                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{[c.phone, c.email].filter(Boolean).join(" · ") || "—"}</div>
                            </div>
                            {c.next_contact_at && (
                                <span title="Связаться снова" style={{
                                    fontSize: 11, padding: "2px 8px", borderRadius: 10,
                                    color: isContactDue(c.next_contact_at) ? "var(--red)" : "var(--text-dim)",
                                    background: isContactDue(c.next_contact_at) ? "var(--red-dim)" : "var(--surface2)",
                                }}>
                                    📞 {formatDate(c.next_contact_at)}
                                </span>
                            )}
                            <div style={{ fontSize: 12, color: "var(--text-dim)" }}>{userName(usersById, c.owner_id)}</div>
                        </div>
                    ))}
                </div>
            )}
            <Pagination page={page} totalPages={data.pages} onPage={setPage} />
        </div>
    );
}
