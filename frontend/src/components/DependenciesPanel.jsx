import React, { useState, useEffect, useCallback, useRef } from "react";
import { apiRequest } from "../api";
import { Icon } from "./Icon";
import { ICONS } from "../constants/icons";

export function DependenciesPanel({ taskId, token }) {
    const [deps, setDeps] = useState({ blockers: [], blocked: [] });
    const [loading, setLoading] = useState(false);
    const [blockerId, setBlockerId] = useState("");
    const [adding, setAdding] = useState(false);
    const [error, setError] = useState(null);

    const loadingRef = React.useRef(false);
    const load = useCallback(async () => {
        if (loadingRef.current) return;
        loadingRef.current = true;
        setLoading(true);
        try {
            const data = await apiRequest({ path: `/tasks/${taskId}/dependencies`, token });
            setDeps({ blockers: data?.blockers ?? [], blocked: data?.blocked ?? [] });
        } catch { /* ignore */ }
        finally { setLoading(false); loadingRef.current = false; }
    }, [taskId, token]);

    useEffect(() => { load(); }, [load]);

    async function handleAdd() {
        const id = Number(blockerId);
        if (!id || id === taskId) return;
        setAdding(true);
        setError(null);
        try {
            await apiRequest({
                path: `/tasks/${taskId}/dependencies`, method: "POST", token,
                body: { blocker_task_id: id },
            });
            setBlockerId("");
            await load();
        } catch (err) {
            setError(err.message);
        } finally {
            setAdding(false);
        }
    }

    async function handleRemove(blocker) {
        setDeps(prev => ({ ...prev, blockers: prev.blockers.filter(b => b.id !== blocker.id) }));
        try {
            await apiRequest({ path: `/tasks/${taskId}/dependencies/${blocker.id}`, method: "DELETE", token });
        } catch {
            await load(); // откат при ошибке
        }
    }

    const statusLabels = {
        backlog: "В очереди", todo: "Новая", in_progress: "В работе", review: "На проверке", done: "Готово",
    };
    const openBlockersCount = deps.blockers.filter(b => b.status !== "done").length;

    return (
        <div className="comments-panel">
            <div className="comments-title">
                🔗 Зависимости
                {openBlockersCount > 0 && (
                    <span className="count-badge" style={{ background: "#ef444422", color: "#ef4444" }}>
                        {openBlockersCount} не закрыт{openBlockersCount === 1 ? "" : "о"}
                    </span>
                )}
            </div>

            {error && <div className="alert" style={{ marginBottom: 8, fontSize: 13 }}>{error}</div>}

            <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                <input
                    type="number"
                    value={blockerId}
                    onChange={e => setBlockerId(e.target.value)}
                    placeholder="ID задачи-блокера"
                    style={{ flex: 1 }}
                />
                <button className="btn btn-sm btn-primary" onClick={handleAdd} disabled={adding || !blockerId}>
                    {adding ? "…" : "Добавить"}
                </button>
            </div>

            {loading ? (
                <div className="comments-empty">Загрузка…</div>
            ) : (
                <>
                    <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>
                        Блокируют эту задачу (должны закрыться раньше):
                    </div>
                    {deps.blockers.length === 0 ? (
                        <div className="comments-empty" style={{ padding: "6px 0" }}>Нет блокеров</div>
                    ) : (
                        <div className="comment-list" style={{ marginBottom: 12 }}>
                            {deps.blockers.map(b => (
                                <div key={b.id} className="comment-item" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                    <span className="meta-chip" style={
                                        b.status === "done"
                                            ? { background: "#22c55e22", color: "#22c55e" }
                                            : { background: "#ef444422", color: "#ef4444" }
                                    }>
                                        {statusLabels[b.status] || b.status}
                                    </span>
                                    <span style={{ flex: 1 }}>#{b.id} {b.title}</span>
                                    <button className="btn btn-ghost btn-sm" style={{ padding: "2px 6px" }}
                                        onClick={() => handleRemove(b)} title="Убрать зависимость">
                                        <Icon d={ICONS.trash} />
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}

                    {deps.blocked.length > 0 && (
                        <>
                            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>
                                Ждут закрытия этой задачи:
                            </div>
                            <div className="comment-list">
                                {deps.blocked.map(b => (
                                    <div key={b.id} className="comment-item" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                        <span className="meta-chip">{statusLabels[b.status] || b.status}</span>
                                        <span style={{ flex: 1 }}>#{b.id} {b.title}</span>
                                    </div>
                                ))}
                            </div>
                        </>
                    )}
                </>
            )}
        </div>
    );
}

// ─── TaskCard ─────────────────────────────────────────────
