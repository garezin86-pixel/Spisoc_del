import { Icon } from "./Icon";
import { StatusMenu } from "./StatusMenu";
import { UserProfileAvatar } from "./UserProfileAvatar";
import { ICONS } from "../constants/icons";
import { PRIORITY_COLORS, PRIORITY_LABELS } from "../constants/priority";

export function KanbanCard({ task, col, onDragStart, onDragEnd, onChangeStatus, isMoving, isDragging }) {
    const priColor = PRIORITY_COLORS[task.priority] ?? "#3b82f6";
    const isOverdue = task.deadline && !task.is_done && new Date(task.deadline) < new Date();

    return (
        <div
            draggable
            onDragStart={e => onDragStart(e, task.id, col)}
            onDragEnd={onDragEnd}
            style={{
                background: "var(--surface2)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                padding: "10px 12px",
                cursor: isDragging ? "grabbing" : "grab",
                opacity: isDragging ? 0.4 : isMoving ? 0.7 : 1,
                transition: "opacity 0.15s, box-shadow 0.15s",
                boxShadow: isDragging ? "none" : "var(--shadow-sm)",
                userSelect: "none",
            }}
        >
            {/* Приоритет */}
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5 }}>
                <span style={{
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: "0.04em",
                    color: priColor,
                    background: priColor + "22",
                    borderRadius: 6,
                    padding: "1px 7px",
                    textTransform: "uppercase",
                }}>
                    {PRIORITY_LABELS[task.priority] ?? task.priority}
                </span>
                <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-muted)" }}>
                    #{task.id}
                </span>
            </div>

            {/* Заголовок */}
            <div style={{
                fontSize: 13,
                fontWeight: 600,
                color: "var(--text)",
                lineHeight: 1.4,
                marginBottom: 6,
                wordBreak: "break-word",
            }}>
                {task.title}
            </div>

            {/* Описание (обрезанное) */}
            {task.description && (
                <div style={{
                    fontSize: 11,
                    color: "var(--text-muted)",
                    lineHeight: 1.4,
                    marginBottom: 6,
                    overflow: "hidden",
                    display: "-webkit-box",
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: "vertical",
                }}>
                    {task.description}
                </div>
            )}

            {/* Дедлайн + исполнитель */}
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
                {task.deadline && (
                    <span style={{
                        fontSize: 11,
                        color: isOverdue ? "var(--red)" : "var(--text-muted)",
                        display: "flex",
                        alignItems: "center",
                        gap: 3,
                    }}>
                        <Icon d={ICONS.clock} size={11} />
                        {new Date(task.deadline).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}
                    </span>
                )}
                {task.user && (
                    <span style={{
                        marginLeft: "auto",
                        fontSize: 11,
                        color: "var(--text-dim)",
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                        cursor: "pointer",
                    }}
                        onClick={e => { e.stopPropagation(); window.openUserProfile?.(task.user.id); }}
                        title={task.user.username}
                    >
                        <UserProfileAvatar userId={task.user.id} username={task.user.username} size={16} />
                        {task.user.username}
                    </span>
                )}
            </div>

            {/* Теги + чек-лист + повторение (компактно) */}
            {((task.tags?.length > 0) || (task.checklist_items?.length > 0) || (task.recurrence_rule && task.recurrence_rule !== "none")) && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                    {task.recurrence_rule && task.recurrence_rule !== "none" && (
                        <span style={{ fontSize: 10, color: "var(--text-muted)" }} title="Повторяющаяся задача">🔁</span>
                    )}
                    {task.checklist_items?.length > 0 && (
                        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
                            ☑️ {task.checklist_items.filter(i => i.is_done).length}/{task.checklist_items.length}
                        </span>
                    )}
                    {(task.tags || []).map(tag => (
                        <span key={tag.id} style={{
                            fontSize: 10, padding: "1px 6px", borderRadius: 8,
                            background: tag.color + "22", color: tag.color, fontWeight: 600,
                        }}>
                            {tag.name}
                        </span>
                    ))}
                </div>
            )}

            {/* Смена статуса без перетаскивания */}
            <div draggable={false} style={{ marginTop: 8 }} onMouseDown={e => e.stopPropagation()}>
                <StatusMenu status={task.status || col} onChange={onChangeStatus} disabled={isMoving} />
            </div>
        </div>
    );
}

// ─── TemplatesTab ──────────────────────────────────────────
