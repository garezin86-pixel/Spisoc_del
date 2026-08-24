import React, { useState, useEffect, useCallback, useRef } from "react";
import { apiRequest } from "../api";
import { Icon } from "./Icon";
import { UserProfileAvatar } from "./UserProfileAvatar";
import { ICONS } from "../constants/icons";
import { ROLE_LABELS, ROLE_COLORS } from "../constants/roles";
import { extractItems } from "../utils/extractItems";

export function GroupPanel({ group, allUsers, token, canManage, onRefresh }) {
    const [members, setMembers] = useState([]);
    const [loading, setLoading] = useState(false);
    const [addUserId, setAddUserId] = useState("");
    const [adding, setAdding] = useState(false);
    const [expanded, setExpanded] = useState(false);
    const [error, setError] = useState(null);

    const loadingRef = React.useRef(false);
    const load = useCallback(async () => {
        if (loadingRef.current) return;
        loadingRef.current = true;
        setLoading(true);
        try {
            const data = await apiRequest({
                path: `/groups/${group.id}/users?page=1&size=100`, token,
            });
            setMembers(extractItems(data));
        } catch { setMembers([]); }
        finally { setLoading(false); loadingRef.current = false; }
    }, [group.id, token]);

    useEffect(() => { if (expanded) load(); }, [expanded, load]);

    async function handleAdd() {
        if (!addUserId) return;
        const newUser = allUsers.find(u => u.id === Number(addUserId));
        if (!newUser) return;
        setMembers(prev => [...prev, newUser]);
        setAddUserId("");
        setAdding(true); setError(null);
        try {
            await apiRequest({
                path: `/groups/${group.id}/users/${addUserId}`,
                method: "POST", token,
            });
        } catch (err) {
            setMembers(prev => prev.filter(m => m.id !== newUser.id));
            setAddUserId(String(newUser.id));
            setError(err.message);
        }
        finally { setAdding(false); }
    }

    async function handleRemove(userId) {
        const removed = members.find(m => m.id === userId);
        setMembers(prev => prev.filter(m => m.id !== userId));
        setError(null);
        try {
            await apiRequest({
                path: `/groups/${group.id}/users/${userId}`,
                method: "DELETE", token,
            });
        } catch (err) {
            setMembers(prev => [...prev, removed]);
            setError(err.message);
        }
    }

    // пользователи не в группе — для селекта добавления
    const memberIds = new Set(members.map(m => m.id));
    const notInGroup = allUsers.filter(u => !memberIds.has(u.id));

    return (
        <div className="group-card">
            <div className="group-card-header" onClick={() => setExpanded(v => !v)}>
                <div className="group-card-title">
                    <Icon d={ICONS.group} size={16} />
                    <span>{group.name}</span>
                    {members.length > 0 && !loading && (
                        <span className="count-badge">{members.length}</span>
                    )}
                </div>
                <Icon d={expanded ? ICONS.chevronL : ICONS.chevronR} size={14} />
            </div>

            {expanded && (
                <div className="group-card-body">
                    {error && <div className="alert" style={{ marginBottom: 10 }}>{error}</div>}

                    {/* Member list */}
                    {loading ? (
                        <div className="comments-empty">Загрузка…</div>
                    ) : members.length === 0 ? (
                        <div className="comments-empty">В группе нет участников</div>
                    ) : (
                        <div className="member-list">
                            {members.map(m => {
                                const rc = ROLE_COLORS[m.role] ?? ROLE_COLORS.user;
                                return (
                                    <div key={m.id} className="member-row">
                                        <div className="member-info" style={{ cursor: "pointer" }} onClick={() => window.openUserProfile?.(m.id)}>
                                            <UserProfileAvatar userId={m.id} username={m.username} size={40} />
                                            <div>
                                                <div className="member-name">
                                                    {m.username}
                                                    {!m.is_active && (
                                                        <span className="inactive-badge">неакт.</span>
                                                    )}
                                                </div>
                                                <div className="member-role-row">
                                                    <span className="role-badge"
                                                        style={{ color: rc.color, background: rc.bg }}>
                                                        {ROLE_LABELS[m.role] ?? m.role}
                                                    </span>
                                                    {m.position && (
                                                        <span className="meta-chip" style={{ fontSize: "0.72rem" }}>
                                                            {m.position}
                                                        </span>
                                                    )}
                                                    {m.telegram_id && (
                                                        <span className="meta-chip" style={{ fontSize: "0.72rem" }}>
                                                            TG: {m.telegram_id}
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                        {canManage && (
                                            <button className="btn btn-danger btn-sm"
                                                onClick={() => handleRemove(m.id)}
                                                title="Удалить из группы">
                                                <Icon d={ICONS.userMinus} />
                                            </button>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    )}

                    {/* Add member — только для manager/admin */}
                    {canManage && (
                        <div className="group-add-row">
                            <select value={addUserId} onChange={e => setAddUserId(e.target.value)}
                                style={{ flex: 1 }}>
                                <option value="">Добавить участника…</option>
                                {notInGroup.map(u => (
                                    <option key={u.id} value={u.id}>
                                        {u.username} ({ROLE_LABELS[u.role] ?? u.role})
                                    </option>
                                ))}
                            </select>
                            <button className="btn btn-primary btn-sm" onClick={handleAdd}
                                disabled={adding || !addUserId}>
                                <Icon d={ICONS.userPlus} /> {adding ? "…" : "Добавить"}
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}


// ─── KanbanTab ────────────────────────────────────────────
