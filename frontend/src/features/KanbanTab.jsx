import { useState, useEffect, useCallback, useRef } from "react";
import { apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { KanbanBoard } from "../components/KanbanBoard";
import { KanbanCard } from "../components/KanbanCard";
import { ICONS } from "../constants/icons";
import { KANBAN_COLUMNS } from "../constants/kanban";

// embedded — доска показывается внутри вкладки «Задачи» (режим «Канбан»); refreshKey — внешний сигнал
// «обновить» (создание задачи, событие WebSocket): перезагрузка без экрана «Загрузка…».
export function KanbanTab({ token, embedded = false, refreshKey = 0 }) {
    const [board, setBoard] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [projectId, setProjectId] = useState("");
    const [onlyMine, setOnlyMine] = useState(false);
    const [onlyAuthor, setOnlyAuthor] = useState(false);
    const [projects, setProjects] = useState([]);
    const [movingId, setMovingId] = useState(null);
    const [moveError, setMoveError] = useState(null);

    // const API = (path) => `/api${path}`;
    // const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

    const loadBoard = useCallback(async (pid, mine, author, silent = false) => {
        if (!silent) setLoading(true);
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

    const firstRefresh = useRef(true);
    useEffect(() => {
        if (firstRefresh.current) { firstRefresh.current = false; return; }
        if (token) loadBoard(projectId, onlyMine, onlyAuthor, true);
    }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (!moveError) return;
        const timer = setTimeout(() => setMoveError(null), 6000);
        return () => clearTimeout(timer);
    }, [moveError]);

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
        <div style={{ padding: embedded ? 0 : "16px 16px 32px" }}>
            {moveError && (
                <div className="alert" style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <span>{moveError}</span>
                    <button className="btn btn-ghost btn-sm" onClick={() => setMoveError(null)}>✕</button>
                </div>
            )}
            {/* Фильтры */}
            <div className="cl-filters" style={{ marginBottom: 16 }}>
                <select
                    className="form-input dl-select"
                    aria-label="Проект"
                    value={projectId}
                    onChange={e => setProjectId(e.target.value)}
                >
                    <option value="">Все задачи</option>
                    {projects.map(p => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                </select>
                <label className="cl-check">
                    <input
                        type="checkbox"
                        checked={onlyMine}
                        onChange={e => { setOnlyMine(e.target.checked); if (e.target.checked) setOnlyAuthor(false); }}
                    />
                    Только мои
                </label>
                <label className="cl-check">
                    <input
                        type="checkbox"
                        checked={onlyAuthor}
                        onChange={e => { setOnlyAuthor(e.target.checked); if (e.target.checked) setOnlyMine(false); }}
                    />
                    Я автор
                </label>
                <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 12 }}>
                    <span className="cl-muted">{totalTasks} задач</span>
                    <button className="btn btn-ghost" onClick={() => loadBoard(projectId, onlyMine, onlyAuthor)}>
                        <Icon d={ICONS.refresh} /> Обновить
                    </button>
                </span>
            </div>

            {/* Доска */}
            <KanbanBoard
                columns={KANBAN_COLUMNS}
                items={board ?? {}}
                onMove={(taskId, fromCol, toCol) => moveTask(taskId, fromCol, toCol)}
                renderCard={({ item, col, onDragStart, onDragEnd, isDragging }) => (
                    <KanbanCard
                        task={item}
                        col={col}
                        onDragStart={onDragStart}
                        onDragEnd={onDragEnd}
                        onChangeStatus={(newStatus) => moveTask(item.id, col, newStatus)}
                        isMoving={movingId === item.id}
                        isDragging={isDragging}
                    />
                )}
            />
        </div>
    );
}
