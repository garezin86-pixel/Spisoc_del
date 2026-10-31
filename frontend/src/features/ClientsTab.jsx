import { useCallback, useEffect, useState } from "react";
import { apiRequest, downloadFile } from "../api";
import { Icon } from "../components/Icon";
import { Pagination } from "../components/Pagination";
import { ICONS } from "../constants/icons";
import { PersonFields } from "../components/PersonFields";
import {
    CLIENT_STATUSES, CLIENT_TYPES, INTERACTION_LABELS, clientStatusInfo, clientTypeInfo, emptyToNull, formatDate, formatRelative, isContactDue, plural,
} from "../constants/crm";
import { userName, useUsersMap } from "../hooks/useUsersMap";
import { ClientCard } from "./ClientCard";
import { ClientImportModal } from "../components/ClientImportModal";

const EMPTY_FORM = { name: "", client_type: "company", birth_date: "", gender: "", phone: "", email: "", address: "", notes: "", owner_id: "" };

// Клиенты: список с поиском и пагинацией + карточка клиента. Создавать клиентов могут admin и manager.
export function ClientsTab({ token, canManage, currentUserId, initialClientId = null, onSelectedChange, refreshSignal = 0 }) {
    const { users, usersById } = useUsersMap(token);
    const isAdmin = users.find(u => u.id === currentUserId)?.role === "admin"; // демо-данные загружает и удаляет только admin
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
    const [statusFilter, setStatusFilter] = useState(""); // "" — все, иначе active / inactive / blacklisted
    const [statusCounts, setStatusCounts] = useState({ all: 0, active: 0, inactive: 0, blacklisted: 0 });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [showCreate, setShowCreate] = useState(false);
    const [showImport, setShowImport] = useState(false);
    const [exporting, setExporting] = useState(false);
    const [demo, setDemo] = useState({ loaded: false, clients: 0 }); // есть ли в компании демо-клиенты
    const [demoBusy, setDemoBusy] = useState(false);
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
            if (statusFilter) qs.set("status", statusFilter);
            await downloadFile({ path: `/clients/export?${qs}`, token, fallbackName: "clients_export.csv" });
            setError(null);
        } catch (e) {
            setError(e.message);
        } finally {
            setExporting(false);
        }
    };

    const loadDemoStatus = useCallback(async () => {
        try {
            setDemo(await apiRequest({ path: "/demo", token }));
        } catch { /* статус демо — не критично: без него просто нет кнопок */ }
    }, [token]);
    useEffect(() => { if (token && canManage) loadDemoStatus(); }, [token, canManage, loadDemoStatus]);

    const changeDemo = async (method, confirmText) => {
        if (confirmText && !window.confirm(confirmText)) return;
        setDemoBusy(true);
        try {
            await apiRequest({ path: method === "POST" ? "/demo/load" : "/demo", method, token });
            await loadDemoStatus();
            setPage(1);
            await load();
            setError(null);
        } catch (e) {
            setError(e.message);
        } finally {
            setDemoBusy(false);
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
            // счётчики вкладок считаются при тех же поиске и фильтрах, но без выбранного статуса
            const countQs = new URLSearchParams(qs);
            countQs.delete("page");
            countQs.delete("size");
            if (statusFilter) qs.set("status", statusFilter);
            const [res, counts] = await Promise.all([
                apiRequest({ path: `/clients?${qs}`, token }),
                apiRequest({ path: `/clients/status-counts?${countQs}`, token }).catch(() => null), // счётчики не критичны
            ]);
            setData({ items: res?.items ?? [], total: res?.total ?? 0, pages: res?.pages ?? 1 });
            if (counts) setStatusCounts(counts);
            setError(null);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }, [token, page, query, onlyDue, onlyMine, typeFilter, statusFilter, currentUserId]);

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
        <div className="cl-page">
            <div className="cl-head">
                <div>
                    <h1 className="cl-title">Клиенты</h1>
                    <div className="cl-sub">{data.total > 0 ? `${data.total} ${plural(data.total, "клиент", "клиента", "клиентов")} · ` : ""}Управляйте клиентами, их контактами и связями с задачами.</div>
                </div>
                {canManage && (
                    <div className="cl-actions">
                        <button className="btn btn-ghost" onClick={() => setShowImport(true)}>Импорт</button>
                        <button className="btn btn-ghost" onClick={exportCsv} disabled={exporting} title="Выгрузить клиентов с текущими фильтрами в CSV">
                            {exporting ? "Экспорт…" : "Экспорт"}
                        </button>
                        <button className="btn btn-primary" onClick={() => { setShowCreate(v => !v); setFormError(null); }}>
                            <Icon d={ICONS.plus} /> Добавить клиента
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

            <div className="cl-tabs" role="tablist" aria-label="Статус клиента">
                {[{ key: "", label: "Все", count: statusCounts.all }, ...CLIENT_STATUSES.map(st => ({ key: st.key, label: st.plural, count: statusCounts[st.key] }))].map(opt => (
                    <button
                        key={opt.key} type="button" role="tab" aria-selected={statusFilter === opt.key}
                        onClick={() => { setStatusFilter(opt.key); setPage(1); }}
                        className={`cl-tab${statusFilter === opt.key ? " active" : ""}`}
                    >{opt.label}<span className="cl-tab-count">{opt.count ?? 0}</span></button>
                ))}
            </div>
            <div className="cl-filters">
                <input
                    className="form-input cl-search" placeholder="Поиск по названию, телефону, email…" aria-label="Поиск клиентов"
                    value={search} onChange={e => setSearch(e.target.value)}
                />
                <select
                    className="form-input dl-select" aria-label="Тип клиента" value={typeFilter}
                    onChange={e => { setTypeFilter(e.target.value); setPage(1); }}
                >
                    <option value="">Все типы</option>
                    {CLIENT_TYPES.map(t => <option key={t.key} value={t.key}>{t.icon} {t.label}</option>)}
                </select>
                <label className="cl-check">
                    <input type="checkbox" checked={onlyDue} onChange={e => { setOnlyDue(e.target.checked); setPage(1); }} />
                    Пора связаться
                </label>
                <label className="cl-check">
                    <input type="checkbox" checked={onlyMine} onChange={e => { setOnlyMine(e.target.checked); setPage(1); }} />
                    Мои клиенты
                </label>
            </div>

            {demo.loaded && canManage && (
                <div style={{ display: "flex", gap: 10, alignItems: "center", justifyContent: "space-between", padding: "8px 12px", margin: "8px 0", borderRadius: 8, background: "var(--bg-hover, rgba(124,108,248,0.12))", fontSize: 13 }}>
                    <span>🧪 В списке есть демо-данные ({demo.clients} {plural(demo.clients, "клиент", "клиента", "клиентов")}) — для знакомства с системой.</span>
                    {isAdmin && (
                        <button className="btn btn-ghost btn-sm" disabled={demoBusy} onClick={() => changeDemo("DELETE", "Удалить демо-данные? Будут убраны демо-клиенты, их сделки, задачи и встречи. Ваши настоящие данные не затрагиваются.")}>
                            {demoBusy ? "Удаляю…" : "Удалить демо"}
                        </button>
                    )}
                </div>
            )}

            {error ? (
                <div className="alert">{error}</div>
            ) : loading ? (
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
            ) : data.items.length === 0 ? (
                <div className="empty-state">
                    <div className="empty-icon">🏢</div>{query ? "Ничего не найдено" : "Клиентов пока нет"}
                    {!query && isAdmin && !demo.loaded && (
                        <div style={{ marginTop: 12 }}>
                            <button className="btn btn-ghost btn-sm" disabled={demoBusy} onClick={() => changeDemo("POST")}>
                                {demoBusy ? "Загружаю…" : "Загрузить демо-данные"}
                            </button>
                            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6 }}>
                                Пример клиентов, сделок и задач, чтобы посмотреть систему в деле. Удаляется одной кнопкой.
                            </div>
                        </div>
                    )}
                </div>
            ) : (
                <div className="card cl-table" role="table" aria-label="Список клиентов">
                    <div className="cl-row cl-row--head" role="row">
                        <span role="columnheader">Клиент</span>
                        <span role="columnheader">Контакты</span>
                        <span role="columnheader">Статус</span>
                        <span role="columnheader">Ответственный</span>
                        <span role="columnheader">Последняя активность</span>
                    </div>
                    {data.items.map(c => {
                        const info = clientTypeInfo(c.client_type);
                        const due = c.next_contact_at && isContactDue(c.next_contact_at);
                        const owner = userName(usersById, c.owner_id);
                        return (
                            <button key={c.id} type="button" role="row" className="cl-row cl-row--item" onClick={() => setSelectedId(c.id)}>
                                <span className="cl-cell-main" role="cell">
                                    <span className="cl-avatar" title={info.label}>{(c.name || "?").trim().charAt(0).toUpperCase()}</span>
                                    <span className="cl-name-wrap">
                                        <span className="cl-name">{c.name}{c.is_demo && <span className="cl-demo" title="Демо-данные: удаляются кнопкой «Удалить демо»">демо</span>}</span>
                                        <span className="cl-type">{info.icon} {info.label}</span>
                                    </span>
                                </span>
                                <span className="cl-cell-contacts" role="cell">
                                    <span>{c.phone || "—"}</span>
                                    {c.email && <span className="cl-muted">{c.email}</span>}
                                </span>
                                <span role="cell">
                                    <span className={`cl-status cl-status--${c.status || "active"}`}>{clientStatusInfo(c.status).label}</span>
                                </span>
                                <span className="cl-cell-owner" role="cell">{owner}</span>
                                <span className="cl-cell-activity" role="cell">
                                    {c.last_interaction_at ? (
                                        <>
                                            <span title={formatDate(c.last_interaction_at)}>{formatRelative(c.last_interaction_at)}</span>
                                            {INTERACTION_LABELS[c.last_interaction_type] && (
                                                <span className="cl-muted">{INTERACTION_LABELS[c.last_interaction_type].icon} {INTERACTION_LABELS[c.last_interaction_type].label}</span>
                                            )}
                                        </>
                                    ) : <span className="cl-muted">Контактов не было</span>}
                                    {c.next_contact_at && (
                                        <span className={`cl-pill${due ? " cl-pill--due" : ""}`} title="Связаться снова">
                                            {due ? "Пора связаться" : `Связаться: ${formatDate(c.next_contact_at)}`}
                                        </span>
                                    )}
                                </span>
                            </button>
                        );
                    })}
                </div>
            )}
            <Pagination page={page} totalPages={data.pages} onPage={setPage} />
        </div>
    );
}
