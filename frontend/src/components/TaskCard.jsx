import { useState } from "react";
import AttachmentsPanel from "../AttachmentsPanel";
import { AuditPanel } from "./AuditPanel";
import { ChecklistPanel } from "./ChecklistPanel";
import { CommentsPanel } from "./CommentsPanel";
import { DependenciesPanel } from "./DependenciesPanel";
import { ClientPicker } from "./ClientPicker";
import { Icon } from "./Icon";
import { StatusMenu } from "./StatusMenu";
import { TagsPanel } from "./TagsPanel";
import { UserProfileAvatar } from "./UserProfileAvatar";
import { ICONS } from "../constants/icons";
import { PRIORITY_COLORS, PRIORITY_LABELS, PRIORITY_ICONS } from "../constants/priority";
import { formatDeadline } from "../utils/date";

export function TaskCard({ task, groups, users, token, allTags, onTagsCreated, onTagsUpdated, onToggle, onDelete, onUpdate, onReassign, hideReassign, collapsible, currentUserId, currentRole, selected, onToggleSelect, onOpenClient, embedded = false }) {
    const [expanded, setExpanded] = useState(!collapsible);
    const [editing, setEditing] = useState(false);
    const [showComments, setShowComments] = useState(false);
    const [showAudit, setShowAudit] = useState(false);
    const [showAttachments, setShowAttachments] = useState(false);
    const [showReassign, setShowReassign] = useState(false);
    const [showChecklist, setShowChecklist] = useState(false);
    const [showDependencies, setShowDependencies] = useState(false);
    const [showTags, setShowTags] = useState(false);
    const [saving, setSaving] = useState(false);
    const formatForInput = (value) => {
        if (!value) return "";

        // если уже ISO
        if (value.includes("T")) {
            return value.slice(0, 16);
        }

        // если формат "14.06.2026 22:15"
        const [date, time] = value.split(" ");
        if (!date || !time) return "";

        const [day, month, year] = date.split(".");
        return `${year}-${month}-${day}T${time.slice(0, 5)}`;
    };
    const [editForm, setEditForm] = useState({
        title: task.title, description: task.description || "",
        deadline: formatForInput(task.deadline),
        priority: task.priority || "medium",
        recurrence_rule: task.recurrence_rule || "none",
        client_id: task.client_id ?? null,
        client_name: task.client_name ?? "",
    });
    const [reassignUserId, setReassignUserId] = useState("");
    const [reassignGroupId, setReassignGroupId] = useState("");
    const dl = formatDeadline(task.deadline);

    async function handleSave() {
        setSaving(true);
        await onUpdate(task, {
            title: editForm.title.trim(),
            description: editForm.description.trim() || null,
            deadline: editForm.deadline
                ? new Date(editForm.deadline).toISOString()
                : null,
            priority: editForm.priority,
            recurrence_rule: editForm.recurrence_rule,
            client_id: editForm.client_id ?? null,
        });
        setSaving(false); setEditing(false);
    }

    async function handleReassign() {
        await onReassign(task.id, reassignUserId || null, reassignGroupId || null);
        setShowReassign(false); setReassignUserId(""); setReassignGroupId("");
    }

    // Компактная строка для свёрнутого режима
    if (collapsible && !expanded) {
        return (
            <div
                onClick={() => setExpanded(true)}
                style={{
                    display: "flex", alignItems: "center", gap: 10,
                    padding: "10px 14px", borderRadius: 8, cursor: "pointer",
                    background: "var(--surface)", border: "1px solid var(--border)",
                    transition: "border-color 0.15s",
                }}
                onMouseEnter={e => e.currentTarget.style.borderColor = "var(--accent)"}
                onMouseLeave={e => e.currentTarget.style.borderColor = "var(--border)"}
            >
                <span style={{ fontSize: 15 }}>{task.is_done ? "✅" : "⏳"}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                        fontSize: 14, fontWeight: 500,
                        color: task.is_done ? "var(--text-muted)" : "var(--text)",
                        textDecoration: task.is_done ? "line-through" : "none",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                        <span className="task-id">#{task.id}</span> {task.title}
                    </div>
                    {(dl || task.client_name) && (
                        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                            {dl && <>📅 {dl.fmt}</>}
                            {task.client_name && <>{dl ? " · " : ""}👤 {task.client_name}</>}
                        </div>
                    )}
                </div>
                {task.user?.username && (
                    <span className="meta-chip task-row-user"
                        onClick={e => { e.stopPropagation(); window.openUserProfile?.(task.user.id); }}
                        style={{
                            fontSize: 11, cursor: "pointer",
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                            flexShrink: 0, display: "inline-flex", alignItems: "center", gap: 4,
                        }}>
                        <UserProfileAvatar userId={task.user.id} username={task.user.username} size={14} />
                        {task.user.username}
                    </span>
                )}
                {task.priority && (
                    <span style={{
                        fontSize: 11, padding: "2px 7px", borderRadius: 4,
                        background: PRIORITY_COLORS[task.priority] + "22",
                        color: PRIORITY_COLORS[task.priority], fontWeight: 600,
                        whiteSpace: "nowrap", flexShrink: 0,
                    }}>
                        {PRIORITY_ICONS[task.priority]}
                    </span>
                )}
                <span style={{ fontSize: 11, color: "var(--text-muted)", flexShrink: 0 }}>▼</span>
            </div>
        );
    }

    return (
        <article className={`task-card${task.is_done ? " done-card" : ""}`}>
            <div className="task-main-info"> {/* НОВЫЙ ИЗОЛИРУЮЩИЙ КОНТЕЙНЕР ДЛЯ ВЕРХНЕЙ ЧАСТИ */}
                <div className="task-top">
                    <div style={{ flex: 1, minWidth: 0 }}>
                        {!embedded && (
                        <div className="task-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            {onToggleSelect && (
                                <input
                                    type="checkbox"
                                    checked={!!selected}
                                    onChange={() => onToggleSelect(task.id)}
                                    onClick={e => e.stopPropagation()}
                                    style={{
                                        width: 16, height: 16, minWidth: 16, minHeight: 16,
                                        flexShrink: 0, margin: 0, padding: 0,
                                        border: "1px solid var(--border)", borderRadius: 4,
                                        cursor: "pointer", accentColor: "var(--accent)",
                                    }}
                                />
                            )}
                            <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                                <span className="task-id">#{task.id}</span>
                                {task.title}
                            </span>
                        </div>
                        )}
                        {task.description && <div className="task-desc">{task.description}</div>}
                        <div className="task-meta-row">
                            {dl && !embedded && (
                                <span className={`meta-chip${dl.isOverdue && !task.is_done ? " overdue" : dl.isToday && !task.is_done ? " today" : ""}`}>
                                    <Icon d={ICONS.clock} />
                                    {dl.isOverdue && !task.is_done ? "Просрочено: " : dl.isToday && !task.is_done ? "Сегодня: " : ""}
                                    {dl.fmt}
                                </span>
                            )}
                            {task.author?.username && (
                                <span className="meta-chip" style={{ cursor: "pointer" }}
                                    onClick={e => { e.stopPropagation(); window.openUserProfile?.(task.author.id); }}>
                                    <UserProfileAvatar userId={task.author.id} username={task.author.username} size={14} /> {task.author.username}
                                </span>
                            )}
                            {task.user?.username && task.user.username !== task.author?.username && (
                                <span className="meta-chip" style={{ cursor: "pointer" }}
                                    onClick={e => { e.stopPropagation(); window.openUserProfile?.(task.user.id); }}>
                                    → <UserProfileAvatar userId={task.user.id} username={task.user.username} size={14} /> {task.user.username}
                                </span>
                            )}
                            {task.group?.name && (
                                <span className="meta-chip"><Icon d={ICONS.group} /> {task.group.name}</span>
                            )}
                            {task.client_name && (
                                <span
                                    className="meta-chip" title="Клиент"
                                    style={{ cursor: onOpenClient ? "pointer" : "default" }}
                                    onClick={e => { e.stopPropagation(); onOpenClient?.(task.client_id); }}
                                >
                                    👤 {task.client_name}
                                </span>
                            )}
                            {task.comments_count > 0 && (
                                <span className="meta-chip"><Icon d={ICONS.comment} /> {task.comments_count}</span>
                            )}
                            {task.recurrence_rule && task.recurrence_rule !== "none" && (
                                <span className="meta-chip" title="Повторяющаяся задача">
                                    🔁 {{ daily: "Ежедневно", weekly: "Еженедельно", monthly: "Ежемесячно" }[task.recurrence_rule]}
                                </span>
                            )}
                            {task.checklist_items?.length > 0 && (
                                <span className="meta-chip">
                                    ☑️ {task.checklist_items.filter(i => i.is_done).length}/{task.checklist_items.length}
                                </span>
                            )}
                            {(task.tags || []).map(tag => (
                                <span key={tag.id} className="meta-chip" style={{
                                    background: tag.color + "22", color: tag.color, borderColor: tag.color + "55",
                                }}>
                                    {tag.name}
                                </span>
                            ))}
                        </div>
                    </div>
                    <div className="tk-top-right">
                        {!embedded && (
                            <StatusMenu
                                status={task.status || (task.is_done ? "done" : "todo")}
                                onChange={(newStatus) => onToggle(task, newStatus)}
                            />
                        )}
                        {task.priority && (
                            <span style={{
                                fontSize: 11, padding: "3px 8px", borderRadius: 6,
                                background: PRIORITY_COLORS[task.priority] + "22",
                                color: PRIORITY_COLORS[task.priority], fontWeight: 600, whiteSpace: "nowrap"
                            }}>
                                {PRIORITY_ICONS[task.priority]} {PRIORITY_LABELS[task.priority]}
                            </span>
                        )}
                    </div>
                    {collapsible && (
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => { setExpanded(false); setEditing(false); setShowComments(false); setShowReassign(false); }}
                            style={{ fontSize: 11, padding: "2px 8px", left: 5, position: "relative" }}
                        >
                            свернуть ▲
                        </button>
                    )}
                </div>
            </div> {/* КОНЕЦ НОВОГО КОНТЕЙНЕРА */}
            {editing && (
                <div className="edit-form">
                    <div className="form-group">
                        <label className="form-label">Заголовок</label>
                        <input value={editForm.title}
                            onChange={e => setEditForm({ ...editForm, title: e.target.value })} />
                    </div>
                    <div className="form-group">
                        <label className="form-label">Описание</label>
                        <textarea value={editForm.description} style={{ minHeight: 64 }}
                            onChange={e => setEditForm({ ...editForm, description: e.target.value })} />
                    </div>
                    <div className="form-group">
                        <label className="form-label">Дедлайн</label>
                        <input type="datetime-local" value={editForm.deadline}
                            onChange={e => setEditForm({ ...editForm, deadline: e.target.value })} />
                    </div>

                    <div className="form-group">
                        <label className="form-label">Приоритет</label>
                        <select value={editForm.priority}
                            onChange={e => setEditForm(f => ({ ...f, priority: e.target.value }))}>
                            <option value="low">⚪ Низкий</option>
                            <option value="medium">🔵 Средний</option>
                            <option value="high">🟠 Высокий</option>
                            <option value="critical">🔴 Критический</option>
                        </select>
                    </div>

                    <div className="form-group">
                        <label className="form-label">Клиент</label>
                        <ClientPicker
                            token={token} value={editForm.client_id} name={editForm.client_name}
                            onChange={(id, name) => setEditForm(f => ({ ...f, client_id: id, client_name: name }))}
                        />
                    </div>

                    <div className="form-group">
                        <label className="form-label">Повторение</label>
                        <select value={editForm.recurrence_rule}
                            onChange={e => setEditForm(f => ({ ...f, recurrence_rule: e.target.value }))}>
                            <option value="none">Не повторяется</option>
                            <option value="daily">🔁 Каждый день</option>
                            <option value="weekly">🔁 Каждую неделю</option>
                            <option value="monthly">🔁 Каждый месяц</option>
                        </select>
                    </div>

                    <div className="edit-actions">
                        <button className="btn btn-primary btn-sm" onClick={handleSave}
                            disabled={saving || !editForm.title.trim()}>
                            <Icon d={ICONS.save} /> {saving ? "Сохранение…" : "Сохранить"}
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>
                            <Icon d={ICONS.x} /> Отмена
                        </button>
                    </div>
                </div>
            )}

            {showReassign && (
                <div className="edit-form">
                    <div className="edit-form-row">
                        <div className="form-group">
                            <label className="form-label">Пользователь</label>
                            <select value={reassignUserId} onChange={e => setReassignUserId(e.target.value)}>
                                <option value="">— не менять —</option>
                                {users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                            </select>
                        </div>
                        <div className="form-group">
                            <label className="form-label">Группа</label>
                            <select value={reassignGroupId} onChange={e => setReassignGroupId(e.target.value)}>
                                <option value="">— не менять —</option>
                                {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                            </select>
                        </div>
                    </div>
                    <div className="edit-actions">
                        <button className="btn btn-primary btn-sm" onClick={handleReassign}>
                            <Icon d={ICONS.reassign} /> Переназначить
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={() => setShowReassign(false)}>
                            <Icon d={ICONS.x} /> Отмена
                        </button>
                    </div>
                </div>
            )}

            <div className="tk-actions">
                {!editing && (
                    <button type="button" className="tk-chip" onClick={() => { setEditing(true); setShowReassign(false); }}>
                        <Icon d={ICONS.edit} /> Изменить
                    </button>
                )}
                {!hideReassign && (
                    <button type="button" className="tk-chip" onClick={() => { setShowReassign(v => !v); setEditing(false); }}>
                        <Icon d={ICONS.reassign} /> Переназначить
                    </button>
                )}
                {[
                    { label: "Комментарии", icon: <Icon d={ICONS.comment} />, on: showComments, toggle: () => { setShowComments(v => !v); setShowAudit(false); } },
                    { label: "Вложения", icon: "📎", on: showAttachments, toggle: () => setShowAttachments(v => !v) },
                    { label: "Чек-лист", icon: "☑️", on: showChecklist, toggle: () => setShowChecklist(v => !v) },
                    { label: "Зависимости", icon: <Icon d={ICONS.link} />, on: showDependencies, toggle: () => setShowDependencies(v => !v) },
                    { label: "Теги", icon: "🏷️", on: showTags, toggle: () => setShowTags(v => !v) },
                    { label: "История", icon: "📋", on: showAudit, toggle: () => { setShowAudit(v => !v); setShowComments(false); } },
                ].map(b => (
                    <button key={b.label} type="button" className={`tk-chip${b.on ? " on" : ""}`} aria-pressed={b.on} onClick={b.toggle}>
                        {b.icon} {b.label}
                    </button>
                ))}
                <span className="tk-spacer" />
                <button type="button" className="tk-chip tk-chip--danger" onClick={() => onDelete(task)} aria-label={`Удалить задачу «${task.title}»`}>
                    <Icon d={ICONS.trash} /> Удалить
                </button>
            </div>

            {showComments && <CommentsPanel taskId={task.id} token={token} />}
            {showAttachments && (
                <AttachmentsPanel
                    taskId={task.id}
                    token={token}
                    currentUserId={currentUserId}
                    canDelete={currentRole === "admin" || currentRole === "manager"}
                />
            )}
            {showChecklist && <ChecklistPanel taskId={task.id} token={token} />}
            {showDependencies && <DependenciesPanel taskId={task.id} token={token} />}
            {showTags && (
                <TagsPanel
                    task={task}
                    allTags={allTags}
                    token={token}
                    onTagsCreated={onTagsCreated}
                    onSaved={(updatedTags) => onTagsUpdated?.(task.id, updatedTags)}
                />
            )}
            {showAudit && <AuditPanel taskId={task.id} token={token} />}
        </article>
    );
}

// ─── TrashCard ────────────────────────────────────────────
