import { useState, useEffect, useCallback, useMemo } from "react";
import { apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { UserProfileAvatar } from "../components/UserProfileAvatar";
import { ICONS } from "../constants/icons";
import { ROLE_LABELS, ROLE_COLORS } from "../constants/roles";

export function TeamTab({ token, currentUserId }) {
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [query, setQuery] = useState("");

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

    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return users;
        return users.filter(u =>
            u.username.toLowerCase().includes(q) || (u.position || "").toLowerCase().includes(q)
        );
    }, [users, query]);

    return (
        <div className="card">
            <div className="section-header">
                <div>
                    <div className="section-title">👥 Команда</div>
                    <div className="section-sub">{users.length} человек</div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={load} disabled={loading}>
                    <Icon d={ICONS.refresh} /> Обновить
                </button>
            </div>

            <input
                className="input"
                placeholder="Поиск по имени или должности…"
                value={query}
                onChange={e => setQuery(e.target.value)}
                style={{ marginBottom: 14 }}
            />

            {error && <div className="alert">{error}</div>}
            {loading ? (
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
            ) : filtered.length === 0 ? (
                <div className="empty-state"><div className="empty-icon">🔍</div>Никого не нашли</div>
            ) : (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 10 }}>
                    {filtered.map(u => {
                        const rc = ROLE_COLORS[u.role] ?? ROLE_COLORS.user;
                        return (
                            <div key={u.id}
                                onClick={() => window.openUserProfile?.(u.id)}
                                style={{
                                    display: "flex", alignItems: "center", gap: 10,
                                    padding: "10px 12px", borderRadius: 10,
                                    background: "var(--surface2)", border: "1px solid var(--border)",
                                    cursor: "pointer",
                                }}>
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
                                        <span className="role-badge" style={{ color: rc.color, background: rc.bg, fontSize: 11 }}>
                                            {ROLE_LABELS[u.role] ?? u.role}
                                        </span>
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
                                        title="Написать личное сообщение"
                                        onClick={(e) => { e.stopPropagation(); window.openDmWith?.(u.id, u.username); }}
                                        style={{ flexShrink: 0, padding: "4px 8px" }}
                                    >
                                        ✉️
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
