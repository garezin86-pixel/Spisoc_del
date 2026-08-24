import { useState, useEffect, useMemo, useRef } from "react";
import { apiRequest } from "../api";
import { COMMAND_LIST, CMDK_TASK_STATUS_LABELS } from "../constants/commandPalette";

export function CommandPalette({ open, onClose, token, setTab, setSearchQuery, setTheme, onLogout }) {
    const [query, setQuery] = useState("");
    const [taskResults, setTaskResults] = useState([]);
    const [taskLoading, setTaskLoading] = useState(false);
    const [activeIndex, setActiveIndex] = useState(0);
    const inputRef = useRef(null);

    useEffect(() => {
        if (open) {
            setQuery("");
            setTaskResults([]);
            setActiveIndex(0);
            setTimeout(() => inputRef.current?.focus(), 0);
        }
    }, [open]);

    const filteredCommands = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return COMMAND_LIST;
        return COMMAND_LIST.filter(c => c.label.toLowerCase().includes(q));
    }, [query]);

    useEffect(() => {
        if (!open) return undefined;
        const q = query.trim();
        if (q.length < 2) {
            setTaskResults([]);
            return undefined;
        }
        let cancelled = false;
        setTaskLoading(true);
        const timer = setTimeout(async () => {
            try {
                const params = new URLSearchParams({ search: q, page: "1", size: "5" });
                const data = await apiRequest({ path: `/tasks/filter?${params.toString()}`, token });
                if (!cancelled) setTaskResults(Array.isArray(data?.items) ? data.items : []);
            } catch {
                if (!cancelled) setTaskResults([]);
            } finally {
                if (!cancelled) setTaskLoading(false);
            }
        }, 300);
        return () => { cancelled = true; clearTimeout(timer); };
    }, [query, open, token]);

    const combined = useMemo(
        () => [
            ...filteredCommands.map(c => ({ type: "command", ...c })),
            ...taskResults.map(t => ({ type: "task", ...t })),
        ],
        [filteredCommands, taskResults],
    );

    useEffect(() => { setActiveIndex(0); }, [combined.length]);

    function runCommand(cmd) {
        if (cmd.id === "toggle-theme") setTheme(t => (t === "dark" ? "light" : "dark"));
        else if (cmd.id === "logout") onLogout();
        else setTab(cmd.tab);
        onClose();
    }

    function runTask(t) {
        setTab("tasks");
        setSearchQuery(t.title);
        onClose();
    }

    function runItem(item) {
        if (item.type === "command") runCommand(item);
        else runTask(item);
    }

    function onKeyDown(e) {
        if (e.key === "ArrowDown") {
            e.preventDefault();
            setActiveIndex(i => Math.min(i + 1, combined.length - 1));
        } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActiveIndex(i => Math.max(i - 1, 0));
        } else if (e.key === "Enter") {
            e.preventDefault();
            if (combined[activeIndex]) runItem(combined[activeIndex]);
        } else if (e.key === "Escape") {
            onClose();
        }
    }

    if (!open) return null;

    return (
        <div className="cmdk-overlay" onMouseDown={onClose}>
            <div className="cmdk-panel" onMouseDown={e => e.stopPropagation()}>
                <input
                    ref={inputRef}
                    className="cmdk-input"
                    value={query}
                    onChange={e => setQuery(e.target.value)}
                    onKeyDown={onKeyDown}
                    placeholder="Команда или название задачи…"
                />
                <div className="cmdk-list">
                    {combined.length === 0 && <div className="cmdk-empty">Ничего не найдено</div>}
                    {filteredCommands.length > 0 && <div className="cmdk-group-label">Команды</div>}
                    {filteredCommands.map((c, i) => (
                        <div
                            key={c.id}
                            className={`cmdk-item${activeIndex === i ? " active" : ""}`}
                            onMouseEnter={() => setActiveIndex(i)}
                            onClick={() => runItem({ type: "command", ...c })}
                        >
                            <span className="cmdk-icon">{c.icon}</span> {c.label}
                        </div>
                    ))}
                    {taskLoading && <div className="cmdk-group-label">Задачи · загрузка…</div>}
                    {!taskLoading && taskResults.length > 0 && <div className="cmdk-group-label">Задачи</div>}
                    {taskResults.map((t, i) => {
                        const idx = filteredCommands.length + i;
                        return (
                            <div
                                key={`task-${t.id}`}
                                className={`cmdk-item${activeIndex === idx ? " active" : ""}`}
                                onMouseEnter={() => setActiveIndex(idx)}
                                onClick={() => runItem({ type: "task", ...t })}
                            >
                                <span className="cmdk-icon">📋</span> {t.title}
                                {t.status && <span className="cmdk-hint">{CMDK_TASK_STATUS_LABELS[t.status] ?? t.status}</span>}
                            </div>
                        );
                    })}
                </div>
                <div className="cmdk-footer">
                    <span>↑↓ навигация</span><span>Enter выбрать</span><span>Esc закрыть</span>
                </div>
            </div>
        </div>
    );
}
