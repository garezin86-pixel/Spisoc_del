import { useState, useEffect, useCallback, useMemo } from "react";
import { apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { UserProfileAvatar } from "../components/UserProfileAvatar";
import { ChatIcon } from "../components/layout/shellIcons";
import { ICONS } from "../constants/icons";
import { ROLE_LABELS, ROLE_COLORS } from "../constants/roles";

export function TeamTab({ token, currentUserId, currentRole }) {
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [query, setQuery] = useState("");
    const [savingId, setSavingId] = useState(null);
    // Менять роли может только админ компании; себе роль не меняем (защита от случайного
    // самоотстранения — сервер дополнительно не даёт понизить единственного админа).
    const canChangeRoles = currentRole === "admin";

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await apiRequest({ path: "/users?page=1&size=100", token });
            setUsers(Array.isArray(data?.items) ? data.items : []);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => { load(); }, [load]);

    const changeRole = useCallback(async (u, role) => {
        if (role === u.role) return;
        let question = null;
        if (role === "admin") {
            question = `Сделать «${u.username}» администратором? Он получит полный доступ к компании.`;
        } else if (u.role === "admin") {
            question = `Забрать у «${u.username}» права администратора?`;
        }
        if (question && !window.confirm(question)) return;
        setSavingId(u.id);
        setError(null);
        try {
            const updated = await apiRequest({
                path: `/users/${u.id}/role`, method: "PATCH", token, body: { role },
            });
            setUsers(prev => prev.map(x => (x.id === u.id ? { ...x, role: updated.role } : x)));
        } catch (err) {
            setError(err.message);
        } finally {
            setSavingId(null);
        }
    }, [token]);

    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return users;
        return users.filter(u =>
            u.username.toLowerCase().includes(q) || (u.position || "").toLowerCase().includes(q)
        );
    }, [users, query]);

    return (
        <div className="cl-page">
            <div className="cl-head">
                <div>
                    <h1 className="cl-title">Команда</h1>
                    <div className="cl-sub">{users.length} человек</div>
                </div>
                <div className="cl-actions">
                    <button className="btn btn-ghost" onClick={load} disabled={loading}>
                        <Icon d={ICONS.refresh} /> Обновить
                    </button>
                </div>
            </div>

            <div className="cl-filters">
                <input
                    className="form-input cl-search" aria-label="Поиск по имени или должности"
                    placeholder="Поиск по имени или должности…"
                    value={query}
                    onChange={e => setQuery(e.target.value)}
                />
            </div>

            {error && <div className="alert">{error}</div>}
            {loading ? (
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
            ) : filtered.length === 0 ? (
                <div className="empty-state"><div className="empty-icon">🔍</div>Никого не нашли</div>
            ) : (
                <div className="tm-grid">
                    {filtered.map(u => {
                        const rc = ROLE_COLORS[u.role] ?? ROLE_COLORS.user;
                        return (
                            <div key={u.id} className="tm-card" role="button" tabIndex={0}
                                onClick={() => window.openUserProfile?.(u.id)}
                                onKeyDown={e => { if (e.key === "Enter") window.openUserProfile?.(u.id); }}>
                                <UserProfileAvatar userId={u.id} username={u.username} size={40} />
                                <div style={{ minWidth: 0, flex: 1 }}>
                                    <div style={{
                                        fontWeight: 600, fontSize: 14,
                                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                                    }}>
                                        {u.username}
                                        {!u.is_active && <span className="inactive-badge" style={{ marginLeft: 6 }}>неакт.</span>}
                                    </div>
                                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 3, flexWrap: "wrap" }}>
                                        {canChangeRoles && u.id !== currentUserId ? (
                                            <select
                                                className="form-input"
                                                aria-label={`Роль: ${u.username}`}
                                                value={u.role}
                                                disabled={savingId === u.id}
                                                onClick={e => e.stopPropagation()}
                                                onKeyDown={e => e.stopPropagation()}
                                                onChange={e => changeRole(u, e.target.value)}
                                                style={{ width: "auto", padding: "2px 6px", fontSize: 12, color: rc.color }}
                                            >
                                                {Object.entries(ROLE_LABELS).map(([value, label]) => (
                                                    <option key={value} value={value}>{label}</option>
                                                ))}
                                            </select>
                                        ) : (
                                            <span className="role-badge" style={{ color: rc.color, background: rc.bg, fontSize: 11 }}>
                                                {ROLE_LABELS[u.role] ?? u.role}
                                            </span>
                                        )}
                                        {u.position && (
                                            <span style={{
                                                fontSize: 12, color: "var(--text-muted)",
                                                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                                            }}>
                                                {u.position}
                                            </span>
                                        )}
                                    </div>
                                </div>
                                {u.id !== currentUserId && (
                                    <button
                                        className="btn btn-ghost btn-sm"
                                        title="Написать личное сообщение" aria-label={`Написать сообщение: ${u.username}`}
                                        onClick={(e) => { e.stopPropagation(); window.openDmWith?.(u.id, u.username); }}
                                        style={{ flexShrink: 0, padding: "4px 8px" }}
                                    >
                                        <ChatIcon size={16} />
                                    </button>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
