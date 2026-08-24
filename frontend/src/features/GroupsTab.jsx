import React, { useState, useEffect, useCallback, useRef } from "react";
import { apiRequest } from "../api";
import { GroupPanel } from "../components/GroupPanel";
import { Icon } from "../components/Icon";
import { ICONS } from "../constants/icons";
import { extractItems } from "../utils/extractItems";

export function GroupsTab({ token, currentRole }) {
    const canManage = currentRole === "admin" || currentRole === "manager";
    const [groups, setGroups] = useState([]);
    const [allUsers, setAllUsers] = useState([]);
    const [loading, setLoading] = useState(false);

    const tokenRef = React.useRef(token);
    tokenRef.current = token;
    // loadingRef предотвращает двойной вызов при StrictMode double-mount
    const loadingRef = React.useRef(false);

    const loadGroups = useCallback(async () => {
        setLoading(true);
        try {
            const data = await apiRequest({ path: "/groups?page=1&size=100", token: tokenRef.current });
            setGroups(extractItems(data));
        } catch { setGroups([]); }
        finally { setLoading(false); }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);



    const loadUsers = useCallback(async () => {
        try {
            const data = await apiRequest({ path: "/users?page=1&size=100", token: tokenRef.current });
            setAllUsers(extractItems(data));
        } catch { setAllUsers([]); }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        // Защита от двойного вызова (React StrictMode монтирует дважды)
        if (loadingRef.current) return;
        loadingRef.current = true;
        loadGroups();
        loadUsers();
        return () => { loadingRef.current = false; };
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="content-grid" style={{ gridTemplateColumns: "1fr" }}>
            <div className="card">
                <div className="section-header">
                    <div>
                        <div className="section-title">
                            <Icon d={ICONS.group} size={15} /> Группы
                        </div>
                        <div className="section-sub">
                            {groups.length > 0 ? `${groups.length} групп` : "Нет групп"}
                            {canManage && " · вы можете управлять участниками"}
                        </div>
                    </div>
                    <button className="btn btn-ghost btn-sm" onClick={loadGroups} disabled={loading}>
                        <Icon d={ICONS.refresh} /> Обновить
                    </button>
                </div>

                {loading ? (
                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                ) : groups.length === 0 ? (
                    <div className="empty-state"><div className="empty-icon">👥</div>Групп нет</div>
                ) : (
                    <div className="group-list">
                        {groups.map(g => (
                            <GroupPanel
                                key={g.id}
                                group={g}
                                allUsers={allUsers}
                                token={token}
                                canManage={canManage}
                                onRefresh={loadGroups}
                            />
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}


// ─── Calendar Feed Tab ────────────────────────────────────
