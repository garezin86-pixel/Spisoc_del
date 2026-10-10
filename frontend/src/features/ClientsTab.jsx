import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { Pagination } from "../components/Pagination";
import { ICONS } from "../constants/icons";
import { emptyToNull } from "../constants/crm";
import { userName, useUsersMap } from "../hooks/useUsersMap";
import { ClientCard } from "./ClientCard";

const EMPTY_FORM = { name: "", phone: "", email: "", address: "", notes: "", owner_id: "" };

// Клиенты: список с поиском и пагинацией + карточка клиента. Создавать клиентов могут admin и manager.
export function ClientsTab({ token, canManage, currentUserId }) {
    const { users, usersById } = useUsersMap(token);
    const [selectedId, setSelectedId] = useState(null);
    const [data, setData] = useState({ items: [], total: 0, pages: 1 });
    const [page, setPage] = useState(1);
    const [search, setSearch] = useState("");
    const [query, setQuery] = useState("");
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [showCreate, setShowCreate] = useState(false);
    const [form, setForm] = useState(EMPTY_FORM);
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState(null);

    // поиск с задержкой, чтобы не слать запрос на каждую букву
    useEffect(() => {
        const timer = setTimeout(() => { setQuery(search.trim()); setPage(1); }, 300);
        return () => clearTimeout(timer);
    }, [search]);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const qs = new URLSearchParams({ page, size: 20 });
            if (query) qs.set("search", query);
            const res = await apiRequest({ path: `/clients?${qs}`, token });
            setData({ items: res?.items ?? [], total: res?.total ?? 0, pages: res?.pages ?? 1 });
            setError(null);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }, [token, page, query]);

    useEffect(() => { if (token) load(); }, [token, load]);

    const set = key => e => setForm(f => ({ ...f, [key]: e.target.value }));

    const create = async e => {
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
            if (form.owner_id !== "") body.owner_id = Number(form.owner_id);
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
                token={token} clientId={selectedId} canManage={canManage} currentUserId={currentUserId}
                users={users} usersById={usersById} onBack={back} onDeleted={back}
            />
        );
    }

    return (
        <div className="card">
            <div className="section-header">
                <div>
                    <div className="section-title"><Icon d={ICONS.user} size={15} /> Клиенты</div>
                    <div className="section-sub">{data.total > 0 ? `${data.total} клиентов` : "Нет клиентов"}</div>
                </div>
                {canManage && (
                    <button className="btn btn-primary btn-sm" onClick={() => { setShowCreate(v => !v); setFormError(null); }}>
                        <Icon d={ICONS.plus} /> Клиент
                    </button>
                )}
            </div>

            {showCreate && (
                <form onSubmit={create} style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: 12, marginBottom: 14 }}>
                    {formError && <div className="alert" style={{ marginBottom: 10 }}>{formError}</div>}
                    <div className="form-group">
                        <label className="form-label">Название</label>
                        <input className="form-input" value={form.name} onChange={set("name")} maxLength={200} required autoFocus />
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
                onChange={e => setSearch(e.target.value)} style={{ marginBottom: 12 }}
            />

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
                                <div style={{ fontWeight: 600 }}>{c.name}</div>
                                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{[c.phone, c.email].filter(Boolean).join(" · ") || "—"}</div>
                            </div>
                            <div style={{ fontSize: 12, color: "var(--text-dim)" }}>{userName(usersById, c.owner_id)}</div>
                        </div>
                    ))}
                </div>
            )}
            <Pagination page={page} totalPages={data.pages} onPage={setPage} />
        </div>
    );
}
