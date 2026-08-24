import { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE, apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { Pagination } from "../components/Pagination";
import { StatsDonut } from "../components/StatsDonut";
import { UserProfileAvatar } from "../components/UserProfileAvatar";
import { AUDIT_ACTION_ICONS } from "../constants/audit";
import { CMDK_TASK_STATUS_LABELS } from "../constants/commandPalette";
import { ICONS } from "../constants/icons";
import { ROLE_LABELS, ROLE_COLORS } from "../constants/roles";
import { describeTimelineEvent } from "../utils/timeline";

export function UserProfilePage({ userId, token, currentUserId, onClose, onOpenTask }) {
    const isOwn = userId === currentUserId;
    const [user, setUser] = useState(null);
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [section, setSection] = useState("tasks"); // "tasks" | "activity"
    const [editingPosition, setEditingPosition] = useState(false);
    const [positionDraft, setPositionDraft] = useState("");
    const [savingPosition, setSavingPosition] = useState(false);
    const [avatarUploading, setAvatarUploading] = useState(false);
    const fileInputRef = useRef(null);

    const [tasksState, setTasksState] = useState({ items: [], total: 0, loading: true });
    const [taskFilterGroup, setTaskFilterGroup] = useState("user"); // "user" | "author"

    const [feedState, setFeedState] = useState({ items: [], total: 0, loading: true, page: 1 });

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const [userResp, statsResp] = await Promise.all([
                apiRequest({ path: `/users/${userId}`, token }),
                apiRequest({ path: `/users/${userId}/stats`, token }),
            ]);
            setUser(userResp);
            setStats(statsResp);
            setPositionDraft(userResp?.position || "");
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [userId, token]);

    useEffect(() => { load(); }, [load]);

    const loadTasks = useCallback(async (group) => {
        setTasksState(s => ({ ...s, loading: true }));
        try {
            const params = new URLSearchParams({
                filter_user_group: group, target_user_id: String(userId), page: "1", size: "10",
            });
            const data = await apiRequest({ path: `/tasks/filter?${params.toString()}`, token });
            setTasksState({ items: Array.isArray(data?.items) ? data.items : [], total: data?.total || 0, loading: false });
        } catch {
            setTasksState({ items: [], total: 0, loading: false });
        }
    }, [userId, token]);

    useEffect(() => { if (section === "tasks") loadTasks(taskFilterGroup); }, [section, taskFilterGroup, loadTasks]);

    const loadFeed = useCallback(async (page = 1) => {
        setFeedState(s => ({ ...s, loading: true }));
        try {
            const params = new URLSearchParams({ user_id: String(userId), page: String(page), size: "20" });
            const data = await apiRequest({ path: `/analytics/activity?${params.toString()}`, token });
            setFeedState({ items: Array.isArray(data?.items) ? data.items : [], total: data?.total || 0, loading: false, page });
        } catch {
            setFeedState({ items: [], total: 0, loading: false, page });
        }
    }, [userId, token]);

    useEffect(() => { if (section === "activity") loadFeed(1); }, [section, loadFeed]);

    async function savePosition() {
        setSavingPosition(true);
        try {
            const updated = await apiRequest({
                path: `/users/${userId}`, token, method: "PATCH",
                body: { position: positionDraft.trim() || null },
            });
            setUser(updated);
            setEditingPosition(false);
        } catch (err) {
            alert(err.message);
        } finally {
            setSavingPosition(false);
        }
    }

    async function handleAvatarPick(e) {
        const file = e.target.files?.[0];
        e.target.value = "";
        if (!file) return;
        setAvatarUploading(true);
        try {
            const form = new FormData();
            form.append("file", file);
            await fetch(`${API_BASE}/users/me/avatar`, {
                method: "POST",
                headers: { Authorization: `Bearer ${token}` },
                body: form,
            });
            // Форсим перезагрузку картинки — меняем query-параметр, чтобы обойти кэш браузера
            setUser(u => ({ ...u, _avatarBust: Date.now() }));
        } catch (err) {
            alert("Не удалось загрузить аватар: " + err.message);
        } finally {
            setAvatarUploading(false);
        }
    }

    if (loading) return <div className="card"><div className="empty-state"><div className="empty-icon">⏳</div>Загрузка профиля…</div></div>;
    if (error || !user) return <div className="card"><div className="alert">{error || "Пользователь не найден"}</div></div>;

    const roleColor = ROLE_COLORS[user.role] ?? ROLE_COLORS.user;
    const completionPercent = stats?.total ? Math.round((stats.done / stats.total) * 100) : 0;

    return (
        <div style={{ maxWidth: 820, margin: "0 auto", padding: "16px 16px 0", display: "flex", flexDirection: "column", gap: 16 }}>
            <button className="btn btn-ghost btn-sm" onClick={onClose} style={{ alignSelf: "flex-start" }}>
                ← Назад
            </button>

            <div className="card" style={{ display: "flex", gap: 20, alignItems: "flex-start", flexWrap: "wrap" }}>
                <div style={{ position: "relative" }}>
                    <UserProfileAvatar userId={user.id} username={user.username} size={80} version={user._avatarBust} />
                    {isOwn && (
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => fileInputRef.current?.click()}
                            disabled={avatarUploading}
                            title="Сменить фото"
                            style={{
                                position: "absolute", bottom: -4, right: -4, borderRadius: "50%",
                                width: 28, height: 28, padding: 0, display: "flex", alignItems: "center", justifyContent: "center",
                            }}
                        >
                            {avatarUploading ? "…" : "✎"}
                        </button>
                    )}
                    {isOwn && <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={handleAvatarPick} />}
                </div>

                <div style={{ flex: 1, minWidth: 200 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <div style={{ fontSize: 20, fontWeight: 700 }}>{user.username}</div>
                        <span className="role-badge" style={{ color: roleColor.color, background: roleColor.bg }}>
                            {ROLE_LABELS[user.role] ?? user.role}
                        </span>
                    </div>

                    {editingPosition ? (
                        <div style={{ display: "flex", gap: 6, marginTop: 8, maxWidth: 320 }}>
                            <input className="input" style={{ marginBottom: 0 }} value={positionDraft}
                                placeholder="Должность"
                                onChange={e => setPositionDraft(e.target.value)}
                                onKeyDown={e => e.key === "Enter" && savePosition()} autoFocus />
                            <button className="btn btn-primary btn-sm" onClick={savePosition} disabled={savingPosition}>✓</button>
                            <button className="btn btn-ghost btn-sm" onClick={() => { setEditingPosition(false); setPositionDraft(user.position || ""); }}>✕</button>
                        </div>
                    ) : (
                        <div style={{ marginTop: 6, color: "var(--text-muted)", fontSize: 14, display: "flex", alignItems: "center", gap: 8 }}>
                            {user.position || (isOwn ? "Должность не указана" : "")}
                            {isOwn && (
                                <button className="btn btn-ghost btn-sm" onClick={() => setEditingPosition(true)} style={{ fontSize: 12 }}>
                                    {user.position ? "изменить" : "добавить"}
                                </button>
                            )}
                        </div>
                    )}

                    {stats && (
                        <div style={{ display: "flex", gap: 20, marginTop: 14, flexWrap: "wrap" }}>
                            <div>
                                <div style={{ fontSize: 22, fontWeight: 700 }}>{stats.total}</div>
                                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>задач назначено</div>
                            </div>
                            <div>
                                <div style={{ fontSize: 22, fontWeight: 700, color: "var(--green)" }}>{stats.done}</div>
                                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>готово</div>
                            </div>
                            <div>
                                <div style={{ fontSize: 22, fontWeight: 700 }}>{completionPercent}%</div>
                                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>выполнено</div>
                            </div>
                        </div>
                    )}
                </div>

                {stats && stats.total > 0 && (
                    <div style={{ width: 180, flexShrink: 0 }}>
                        <StatsDonut total={stats.total} done={stats.done} pending={stats.pending} />
                    </div>
                )}
            </div>

            <div className="tab-bar" style={{ display: "inline-flex" }}>
                <button className={`tab-btn${section === "tasks" ? " active" : ""}`} onClick={() => setSection("tasks")}>
                    <Icon d={ICONS.chart} /> Задачи
                </button>
                <button className={`tab-btn${section === "activity" ? " active" : ""}`} onClick={() => setSection("activity")}>
                    <Icon d={ICONS.clock} /> Активность
                </button>
            </div>

            {section === "tasks" && (
                <div className="card">
                    <div className="section-header">
                        <div className="section-title">Задачи</div>
                        <div style={{ display: "flex", gap: 6 }}>
                            <button className={`btn btn-sm ${taskFilterGroup === "user" ? "btn-primary" : "btn-ghost"}`} onClick={() => setTaskFilterGroup("user")}>Назначены</button>
                            <button className={`btn btn-sm ${taskFilterGroup === "author" ? "btn-primary" : "btn-ghost"}`} onClick={() => setTaskFilterGroup("author")}>Созданы</button>
                        </div>
                    </div>
                    {tasksState.loading ? (
                        <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                    ) : tasksState.items.length === 0 ? (
                        <div className="empty-state"><div className="empty-icon">📋</div>Нет задач</div>
                    ) : (
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                            {tasksState.items.map(t => (
                                <div key={t.id}
                                    onClick={() => onOpenTask && onOpenTask(t.title)}
                                    style={{
                                        display: "flex", justifyContent: "space-between", alignItems: "center",
                                        padding: "8px 12px", borderRadius: 8, background: "var(--surface2)", cursor: "pointer",
                                    }}>
                                    <span style={{ fontSize: 13 }}>{t.title}</span>
                                    <span className="meta-chip">{CMDK_TASK_STATUS_LABELS[t.status] ?? t.status}</span>
                                </div>
                            ))}
                            {tasksState.total > tasksState.items.length && (
                                <div style={{ fontSize: 12, color: "var(--text-muted)", textAlign: "center", marginTop: 4 }}>
                                    ещё {tasksState.total - tasksState.items.length} — полный список во вкладке «Задачи»
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {section === "activity" && (
                <div className="card" style={{ marginTop: 0 }}>
                    <div className="section-title" style={{ marginBottom: 10 }}>Лента активности</div>
                    {feedState.loading ? (
                        <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                    ) : feedState.items.length === 0 ? (
                        <div className="empty-state"><div className="empty-icon">🕒</div>Пока пусто</div>
                    ) : (
                        <>
                            <div className="comment-list">
                                {feedState.items.map(e => (
                                    <div key={`${e.entity_type}-${e.id}`} className="comment-item">
                                        <div className="comment-meta">
                                            <span className="comment-author">
                                                {AUDIT_ACTION_ICONS[e.action] || "📝"} {describeTimelineEvent(e)}
                                            </span>
                                            <span className="comment-date">{new Date(e.changed_at).toLocaleString("ru-RU")}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                            <Pagination page={feedState.page} totalPages={Math.max(1, Math.ceil(feedState.total / 20))} onPage={p => loadFeed(p)} />
                        </>
                    )}
                </div>
            )}
        </div>
    );
}

// ─── ChatPanel — переиспользуемое тело чата (список сообщений + инпут).
// Используется внутри всплывающего окна ChatBubble. Каналы: "Общий чат"
// (group_id=null) и по одному на каждую группу, в которой состоит юзер.
// Плюс личные сообщения (ЛС): activeDm !== null переключает панель в режим
// переписки один-на-один — эндпоинты /chat/dm/... вместо /chat/messages,
// и activeDm имеет приоритет над activeChannel (см. isDm ниже).
