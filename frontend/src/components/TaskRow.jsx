import { PRIORITY_COLORS, PRIORITY_ICONS, PRIORITY_LABELS } from "../constants/priority";
import { formatDeadline } from "../utils/date";
import { Icon } from "./Icon";
import { ICONS } from "../constants/icons";
import { StatusMenu } from "./StatusMenu";
import { UserProfileAvatar } from "./UserProfileAvatar";

// Компактная строка списка задач. Клик по названию раскрывает полную карточку (children).
export function TaskRow({ task, projectName, selected, onToggleSelect, hideSelect, expanded, onToggleExpand, onToggleStatus, children }) {
    const dl = formatDeadline(task.deadline);
    const open = !task.is_done;
    const dlClass = dl && open ? (dl.isOverdue ? " overdue" : dl.isToday ? " today" : "") : "";
    const checklist = task.checklist_items || [];
    return (
        <div className={`tr-item${expanded ? " open" : ""}${task.is_done ? " done" : ""}`}>
            <div className="tr-row">
                {hideSelect ? <span aria-hidden="true" /> : (
                    <input
                        type="checkbox" className="tr-check" checked={!!selected}
                        onChange={() => onToggleSelect(task.id)} aria-label={`Выбрать задачу «${task.title}»`}
                    />
                )}
                <button type="button" className="tr-main" aria-expanded={expanded} onClick={onToggleExpand}>
                    <span className="tr-title"><span className="task-id">#{task.id}</span> {task.title}</span>
                    <span className="tr-meta">
                        {task.priority && task.priority !== "medium" && (
                            <span className="meta-chip" style={{ color: PRIORITY_COLORS[task.priority], borderColor: PRIORITY_COLORS[task.priority] + "55" }}>
                                {PRIORITY_ICONS[task.priority]} {PRIORITY_LABELS[task.priority]}
                            </span>
                        )}
                        {projectName && <span className="meta-chip" title="Проект"><Icon d={ICONS.folder} size={12} /> {projectName}</span>}
                        {task.client_name && <span className="meta-chip" title="Клиент">👤 {task.client_name}</span>}
                        {task.group?.name && <span className="meta-chip"><Icon d={ICONS.group} size={12} /> {task.group.name}</span>}
                        {checklist.length > 0 && <span className="meta-chip">☑️ {checklist.filter(i => i.is_done).length}/{checklist.length}</span>}
                        {task.comments_count > 0 && <span className="meta-chip"><Icon d={ICONS.comment} size={12} /> {task.comments_count}</span>}
                        {(task.tags || []).map(tag => (
                            <span key={tag.id} className="meta-chip" style={{ background: tag.color + "22", color: tag.color, borderColor: tag.color + "55" }}>{tag.name}</span>
                        ))}
                    </span>
                </button>
                <span className={`tr-deadline${dlClass}`}>
                    {dl ? <>{dlClass === " overdue" ? "Просрочено · " : dlClass === " today" ? "Сегодня · " : ""}{dl.fmt}</> : <span className="tr-none">Без срока</span>}
                </span>
                <div className="tr-status">
                    <StatusMenu status={task.status || (task.is_done ? "done" : "todo")} onChange={(s) => onToggleStatus(task, s)} />
                </div>
                <span className="tr-assignee" title={task.user?.username || "Без исполнителя"}>
                    {task.user?.username
                        ? <UserProfileAvatar userId={task.user.id} username={task.user.username} size={28} />
                        : <span className="tr-none">—</span>}
                </span>
            </div>
            {expanded && <div className="tr-expanded">{children}</div>}
        </div>
    );
}
