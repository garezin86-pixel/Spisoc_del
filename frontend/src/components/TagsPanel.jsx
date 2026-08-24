import { useState } from "react";
import { apiRequest } from "../api";
import { Icon } from "./Icon";
import { ICONS } from "../constants/icons";

export function TagsPanel({ task, allTags, token, onTagsCreated, onSaved }) {
    const [selectedIds, setSelectedIds] = useState(new Set((task.tags || []).map(t => t.id)));
    const [saving, setSaving] = useState(false);
    const [newTagName, setNewTagName] = useState("");
    const [creating, setCreating] = useState(false);
    const [error, setError] = useState(null);

    function toggle(tagId) {
        setSelectedIds(prev => {
            const next = new Set(prev);
            if (next.has(tagId)) next.delete(tagId); else next.add(tagId);
            return next;
        });
    }

    async function handleSave() {
        setSaving(true);
        setError(null);
        try {
            const updated = await apiRequest({
                path: `/tags/tasks/${task.id}`, method: "PUT", token,
                body: { tag_ids: Array.from(selectedIds) },
            });
            onSaved?.(updated.tags || []);
        } catch (err) {
            setError(err.message);
        } finally {
            setSaving(false);
        }
    }

    async function handleCreateTag() {
        if (!newTagName.trim()) return;
        setCreating(true);
        setError(null);
        try {
            const tag = await apiRequest({
                path: "/tags", method: "POST", token,
                body: { name: newTagName.trim() },
            });
            setNewTagName("");
            await onTagsCreated?.();
            setSelectedIds(prev => new Set(prev).add(tag.id));
        } catch (err) {
            setError(err.message);
        } finally {
            setCreating(false);
        }
    }

    return (
        <div className="comments-panel">
            <div className="comments-title">🏷️ Теги</div>
            {allTags.length === 0 ? (
                <div className="comments-empty">В команде пока нет ни одного тега — создайте первый ниже</div>
            ) : (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
                    {allTags.map(tag => {
                        const isSelected = selectedIds.has(tag.id);
                        return (
                            <button
                                key={tag.id}
                                type="button"
                                onClick={() => toggle(tag.id)}
                                style={{
                                    padding: "5px 12px",
                                    borderRadius: 14,
                                    fontSize: 12,
                                    fontWeight: 600,
                                    cursor: "pointer",
                                    border: `1px solid ${isSelected ? tag.color : "var(--border)"}`,
                                    background: isSelected ? tag.color + "22" : "transparent",
                                    color: isSelected ? tag.color : "var(--text-muted)",
                                }}
                            >
                                {isSelected ? "✓ " : ""}{tag.name}
                            </button>
                        );
                    })}
                </div>
            )}
            {error && <div className="alert" style={{ marginBottom: 8 }}>{error}</div>}
            <div className="comment-form" style={{ marginBottom: 12 }}>
                <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving}>
                    <Icon d={ICONS.save} /> {saving ? "Сохранение…" : "Сохранить теги"}
                </button>
            </div>
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
                <div className="comment-form">
                    <input
                        value={newTagName}
                        onChange={e => setNewTagName(e.target.value)}
                        placeholder="Новый тег (например, клиент-X)…"
                        onKeyDown={e => { if (e.key === "Enter") handleCreateTag(); }}
                    />
                    <button className="btn btn-ghost btn-sm" onClick={handleCreateTag} disabled={creating || !newTagName.trim()}>
                        <Icon d={ICONS.plus} /> {creating ? "…" : "Создать тег"}
                    </button>
                </div>
            </div>
        </div>
    );
}


// ─── Priority config ──────────────────────────────────────
