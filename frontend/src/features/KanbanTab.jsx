import { useState, useEffect, useCallback } from "react";
import { apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { KanbanCard } from "../components/KanbanCard";
import { ICONS } from "../constants/icons";
import { KANBAN_COLUMNS } from "../constants/kanban";

export function KanbanTab({ token }) {
    const [board, setBoard] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [projectId, setProjectId] = useState("");
    const [onlyMine, setOnlyMine] = useState(false);
    const [onlyAuthor, setOnlyAuthor] = useState(false);
    const [projects, setProjects] = useState([]);
    const [dragging, setDragging] = useState(null); // { taskId, fromCol }
    const [dragOver, setDragOver] = useState(null);
    const [movingId, setMovingId] = useState(null);
    const [moveError, setMoveError] = useState(null);

    // const API = (path) => `/api${path}`;
    // const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

    const loadBoard = useCallback(async (pid, mine, author) => {
        setLoading(true);
        setError(null);
        try {
            const params = new URLSearchParams();
            if (pid) params.set("project_id", pid);
            if (mine) params.set("only_mine", "true");
            if (author) params.set("only_author", "true");
            const data = await apiRequest({ path: `/tasks/kanban?${params}`, token });
            setBoard(data);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => {
        if (!token) return;
        apiRequest({ path: "/projects?page=1&size=50", token })
            .then(data => setProjects(Array.isArray(data) ? data : (data.items ?? [])))
            .catch(() => { });
    }, [token]);

    useEffect(() => {
        if (!token) return;
        loadBoard(projectId, onlyMine, onlyAuthor);
    }, [projectId, onlyMine, onlyAuthor, loadBoard]);

    useEffect(() => {
        if (!moveError) return;
        const timer = setTimeout(() => setMoveError(null), 6000);
        return () => clearTimeout(timer);
    }, [moveError]);

    // ── Drag & Drop ──────────────────────────────────────────
    const onDragStart = (e, taskId, fromCol) => {
        setDragging({ taskId, fromCol });
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("taskId", taskId);
    };

    const onDragOver = (e, col) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        setDragOver(col);
    };

    // Перемещение задачи в другую колонку (используется и при drag&drop, и при выборе из списка статусов)
    const moveTask = async (taskId, fromCol, toCol) => {
        if (!fromCol || fromCol === toCol) return;

        // Оптимистичное обновление
        setBoard(prev => {
            const task = prev[fromCol]?.find(t => t.id === taskId);
            if (!task) return prev;
            return {
                ...prev,
                [fromCol]: prev[fromCol].filter(t => t.id !== taskId),
                [toCol]: [{ ...task, status: toCol }, ...prev[toCol]],
            };
        });

        setMovingId(taskId);
        setMoveError(null);
        try {
            await apiRequest({
                path: `/tasks/${taskId}/status`,
                method: "PATCH",
                token,
                body: { status: toCol },
            });
        } catch (err) {
            // Откат при ошибке — и обязательно показываем причину: без этого
            // карточка молча дёргается назад, и непонятно, почему (например,
            // задачу нельзя закрыть, пока не закрыты её блокеры — см. фичу
            // зависимостей между задачами).
            setMoveError(err.message);
            loadBoard(projectId, onlyMine, onlyAuthor);
        } finally {
            setMovingId(null);
        }
    };

    const onDrop = (e, toCol) => {
        e.preventDefault();
        setDragOver(null);
        if (!dragging) return;
        const { taskId, fromCol } = dragging;
        setDragging(null);
        moveTask(taskId, fromCol, toCol);
    };

    const onDragEnd = () => { setDragging(null); setDragOver(null); };

    // ── Render ───────────────────────────────────────────────
    if (loading) return (
        <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
            Загрузка канбан-доски…
        </div>
    );
    if (error) return (
        <div style={{ padding: 40, textAlign: "center", color: "var(--red)" }}>
            Ошибка: {error}
        </div>
    );

    const totalTasks = board ? Object.values(board).reduce((s, arr) => s + arr.length, 0) : 0;

    return (
        <div style={{ padding: "16px 16px 32px" }}>
            {moveError && (
                <div className="alert" style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <span>{moveError}</span>
                    <button className="btn btn-ghost btn-sm" onClick={() => setMoveError(null)}>✕</button>
                </div>
            )}
            {/* Фильтры */}
            <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
                <select
                    className="form-control"
                    style={{ minWidth: 180, maxWidth: 260 }}
                    value={projectId}
                    onChange={e => setProjectId(e.target.value)}
                >
                    <option value="">Все задачи</option>
                    {projects.map(p => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                </select>
                <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", color: "var(--text-dim)", fontSize: 13 }}>
                    <input
                        type="checkbox"
                        checked={onlyMine}
                        onChange={e => { setOnlyMine(e.target.checked); if (e.target.checked) setOnlyAuthor(false); }}
                        style={{ accentColor: "var(--accent)" }}
                    />
                    Только мои
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", color: "var(--text-dim)", fontSize: 13 }}>
                    <input
                        type="checkbox"
                        checked={onlyAuthor}
                        onChange={e => { setOnlyAuthor(e.target.checked); if (e.target.checked) setOnlyMine(false); }}
                        style={{ accentColor: "var(--accent)" }}
                    />
                    Я автор
                </label>
                <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => loadBoard(projectId, onlyMine)}
                    style={{ marginLeft: "auto" }}
                >
                    <Icon d={ICONS.refresh} /> Обновить
                </button>
                <span style={{ color: "var(--text-muted)", fontSize: 13 }}>
                    {totalTasks} задач
                </span>
            </div>

            {/* Доска */}
            <div style={{
                display: "flex",
                gap: 12,
                overflowX: "auto",
                overflowY: "hidden",
                height: "calc(100vh - 220px)",
                paddingBottom: 8,
                paddingRight: 16,
                alignItems: "flex-start",
            }}>
                {KANBAN_COLUMNS.map(col => {
                    const tasks = board?.[col.key] ?? [];
                    const isOver = dragOver === col.key;
                    return (
                        <div
                            key={col.key}
                            onDragOver={e => onDragOver(e, col.key)}
                            onDrop={e => onDrop(e, col.key)}
                            onDragLeave={() => setDragOver(null)}
                            style={{
                                minWidth: 260,
                                maxWidth: 300,
                                flexShrink: 0,
                                background: isOver
                                    ? "rgba(124,106,240,0.08)"
                                    : "var(--surface)",
                                border: `1.5px solid ${isOver ? "var(--accent)" : "var(--border)"}`,
                                borderRadius: "var(--radius)",
                                transition: "border-color 0.15s, background 0.15s",
                                // overflow: "hidden",
                                overflowY: "auto",
                                maxHeight: "100%",
                            }}
                        >
                            {/* Шапка колонки */}
                            <div style={{
                                padding: "12px 14px 10px",
                                borderBottom: "1px solid var(--border)",
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                            }}>
                                <span style={{
                                    display: "inline-block",
                                    width: 10, height: 10,
                                    borderRadius: "50%",
                                    background: col.color,
                                    flexShrink: 0,
                                }} />
                                <span style={{ fontFamily: "Syne, sans-serif", fontWeight: 700, fontSize: 13 }}>
                                    {col.label}
                                </span>
                                <span style={{
                                    marginLeft: "auto",
                                    background: "var(--surface2)",
                                    color: "var(--text-muted)",
                                    fontSize: 11,
                                    fontWeight: 600,
                                    borderRadius: 20,
                                    padding: "1px 8px",
                                }}>
                                    {tasks.length}
                                </span>
                            </div>

                            {/* Карточки */}
                            <div style={{ padding: "8px 8px", display: "flex", flexDirection: "column", gap: 7, minHeight: 60 }}>
                                {tasks.length === 0 ? (
                                    <div style={{
                                        textAlign: "center",
                                        color: "var(--text-muted)",
                                        fontSize: 12,
                                        padding: "24px 0",
                                        opacity: isOver ? 0.3 : 0.6,
                                    }}>
                                        {isOver ? "Отпустите сюда" : "Пусто"}
                                    </div>
                                ) : tasks.map(task => (
                                    <KanbanCard
                                        key={task.id}
                                        task={task}
                                        col={col.key}
                                        onDragStart={onDragStart}
                                        onDragEnd={onDragEnd}
                                        onChangeStatus={(newStatus) => moveTask(task.id, col.key, newStatus)}
                                        isMoving={movingId === task.id}
                                        isDragging={dragging?.taskId === task.id}
                                    />
                                ))}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
