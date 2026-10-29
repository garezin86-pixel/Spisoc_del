import { Icon } from "./Icon";
import { UserProfileAvatar } from "./UserProfileAvatar";
import { ICONS } from "../constants/icons";
import { formatDeadline } from "../utils/date";

export function TrashCard({ task, onRestore, onHardDelete }) {
    const dl = formatDeadline(task.deadline);

    return (
        <div className="tr-item trash-row">
            <div className="trash-main">
                <div className="tr-title"><span className="task-id">#{task.id}</span> <span className="trash-title">{task.title}</span></div>
                {task.description && <div className="cl-muted trash-desc">{task.description}</div>}
                <div className="tr-meta">
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
            <div className="trash-actions">
                <button className="btn btn-success btn-sm" onClick={() => onRestore(task)}>
                    <Icon d={ICONS.check} /> Восстановить
                </button>
                <button className="btn btn-danger btn-sm" onClick={() => onHardDelete(task)}>
                    <Icon d={ICONS.trash} /> Удалить навсегда
                </button>
            </div>
        </div>
    );
}

// ─── GroupPanel ───────────────────────────────────────────
