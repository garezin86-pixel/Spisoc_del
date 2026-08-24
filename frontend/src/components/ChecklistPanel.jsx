import React, { useState, useEffect, useCallback, useRef } from "react";
import { apiRequest } from "../api";
import { Icon } from "./Icon";
import { ICONS } from "../constants/icons";

export function ChecklistPanel({ taskId, token }) {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(false);
    const [newTitle, setNewTitle] = useState("");
    const [adding, setAdding] = useState(false);

    const loadingRef = React.useRef(false);
    const load = useCallback(async () => {
        if (loadingRef.current) return;
        loadingRef.current = true;
        setLoading(true);
        try {
            const data = await apiRequest({ path: `/tasks/${taskId}/checklist`, token });
            setItems(Array.isArray(data) ? data : []);
        } catch { /* ignore */ }
        finally { setLoading(false); loadingRef.current = false; }
    }, [taskId, token]);

    useEffect(() => { load(); }, [load]);

    async function handleAdd() {
        if (!newTitle.trim()) return;
        setAdding(true);
        try {
            await apiRequest({
                path: `/tasks/${taskId}/checklist`, method: "POST", token,
                body: { title: newTitle.trim() },
            });
            setNewTitle("");
            await load();
        } catch { /* ignore */ }
        finally { setAdding(false); }
    }

    async function handleToggleDone(item) {
        // Оптимистичное обновление — не ждём ответа сервера, чтобы галочка отзывалась мгновенно
        setItems(prev => prev.map(i => i.id === item.id ? { ...i, is_done: !i.is_done } : i));
        try {
            await apiRequest({
                path: `/tasks/${taskId}/checklist/${item.id}`, method: "PATCH", token,
                body: { is_done: !item.is_done },
            });
        } catch {
            setItems(prev => prev.map(i => i.id === item.id ? item : i)); // откат при ошибке
        }
    }

    async function handleDelete(item) {
        setItems(prev => prev.filter(i => i.id !== item.id));
        try {
            await apiRequest({ path: `/tasks/${taskId}/checklist/${item.id}`, method: "DELETE", token });
        } catch {
            await load(); // откат — проще перезагрузить, чем восстанавливать позицию в списке
        }
    }

    async function handleMove(item, direction) {
        const idx = items.findIndex(i => i.id === item.id);
        const swapIdx = idx + direction;
        if (swapIdx < 0 || swapIdx >= items.length) return;

        const reordered = [...items];
        [reordered[idx], reordered[swapIdx]] = [reordered[swapIdx], reordered[idx]];
        setItems(reordered);

        try {
            await apiRequest({
                path: `/tasks/${taskId}/checklist/reorder`, method: "PATCH", token,
                body: { items: reordered.map((i, idx2) => ({ id: i.id, order_index: idx2 })) },
            });
        } catch {
            await load();
        }
    }

    const doneCount = items.filter(i => i.is_done).length;

    return (
        <div className="comments-panel">
            <div className="comments-title">
                ☑️ Чек-лист
                {items.length > 0 && <span className="count-badge">{doneCount}/{items.length}</span>}
            </div>
            {loading ? (
                <div className="comments-empty">Загрузка…</div>
            ) : items.length === 0 ? (
                <div className="comments-empty">Пунктов пока нет</div>
            ) : (
                <div className="comment-list">
                    {items.map((item, idx) => (
                        <div key={item.id} className="comment-item" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <input
                                type="checkbox"
                                checked={item.is_done}
                                onChange={() => handleToggleDone(item)}
                                style={{ flexShrink: 0, width: 16, height: 16, cursor: "pointer" }}
                            />
                            <span style={{
                                flex: 1,
                                textDecoration: item.is_done ? "line-through" : "none",
                                color: item.is_done ? "var(--text-muted)" : "var(--text)",
                            }}>
                                {item.title}
                            </span>
                            <button className="btn btn-ghost btn-sm" style={{ padding: "2px 6px" }}
                                disabled={idx === 0} onClick={() => handleMove(item, -1)}>▲</button>
                            <button className="btn btn-ghost btn-sm" style={{ padding: "2px 6px" }}
                                disabled={idx === items.length - 1} onClick={() => handleMove(item, 1)}>▼</button>
                            <button className="btn btn-danger btn-sm" style={{ padding: "2px 6px" }}
                                onClick={() => handleDelete(item)}>
                                <Icon d={ICONS.trash} />
                            </button>
                        </div>
                    ))}
                </div>
            )}
            <div className="comment-form">
                <input
                    value={newTitle}
                    onChange={e => setNewTitle(e.target.value)}
                    placeholder="Новый пункт… (Enter)"
                    onKeyDown={e => { if (e.key === "Enter") handleAdd(); }}
                />
                <button className="btn btn-primary btn-sm" onClick={handleAdd} disabled={adding || !newTitle.trim()}>
                    <Icon d={ICONS.plus} /> {adding ? "…" : "Добавить"}
                </button>
            </div>
        </div>
    );
}


// ─── TagsPanel ─────────────────────────────────────────────
