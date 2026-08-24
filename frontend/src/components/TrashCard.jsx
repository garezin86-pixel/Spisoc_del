import { Icon } from "./Icon";
import { UserProfileAvatar } from "./UserProfileAvatar";
import { ICONS } from "../constants/icons";
import { formatDeadline } from "../utils/date";

export function TrashCard({ task, onRestore, onHardDelete }) {
    const dl = formatDeadline(task.deadline);

    return (
        <article className="task-card done-card">
            <div className="task-main-info">
                <div className="task-top">
                    {/* Единообразие с TaskCard: внутренний div с flex:1 */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="task-title">
                            <span className="task-id">#{task.id}</span>
                            {task.title}
                        </div>
                        {task.description && <div className="task-desc">{task.description}</div>}
                        <div className="task-meta-row">
                            {dl && (
                                <span className="meta-chip">
                                    <Icon d={ICONS.clock} />
                                    {dl.fmt}
                                </span>
                            )}
                            {task.author?.username && (
                                <span className="meta-chip" style={{ cursor: "pointer" }}
                                    onClick={e => { e.stopPropagation(); window.openUserProfile?.(task.author.id); }}>
                                    <UserProfileAvatar userId={task.author.id} username={task.author.username} size={14} /> {task.author.username}
                                </span>
                            )}
                            {task.group?.name && (
                                <span className="meta-chip">
                                    <Icon d={ICONS.group} /> {task.group.name}
                                </span>
                            )}
                        </div>
                    </div>
                    <span className="badge badge-done">Удалена</span>
                </div>
            </div>
            <div className="task-actions">
                <button className="btn btn-success btn-sm" onClick={() => onRestore(task)}>
                    <Icon d={ICONS.check} /> Восстановить
                </button>
                <button className="btn btn-danger btn-sm" onClick={() => onHardDelete(task)}>
                    <Icon d={ICONS.trash} /> Удалить навсегда
                </button>
            </div>
        </article>
    );
}

// ─── GroupPanel ───────────────────────────────────────────
