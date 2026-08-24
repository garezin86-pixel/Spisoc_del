import { useState, useEffect } from "react";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { apiRequest } from "../api";

export function ManagerAnalyticsSection({ token }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            setLoading(true);
            try {
                const result = await apiRequest({ path: "/analytics/dashboard", token });
                if (!cancelled) setData(result);
            } catch (err) {
                if (!cancelled) setError(err.message);
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [token]);

    if (loading) {
        return (
            <div className="card">
                <div className="section-title" style={{ marginBottom: 12 }}>📊 Аналитика команды</div>
                <div className="empty-state"><div className="empty-icon">⏳</div>Считаем метрики…</div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="card">
                <div className="section-title" style={{ marginBottom: 12 }}>📊 Аналитика команды</div>
                <div className="alert">{error}</div>
            </div>
        );
    }

    const executors = data?.executor_completion || [];
    const projects = data?.project_overdue || [];

    return (
        <>
            <div className="card">
                <div className="section-header">
                    <div>
                        <div className="section-title">📊 Закрытие задач в срок — по исполнителям</div>
                        <div className="section-sub">Только задачи с дедлайном, которые уже завершены</div>
                    </div>
                </div>
                {executors.length === 0 ? (
                    <div className="empty-state"><div className="empty-icon">📊</div>Пока нет завершённых задач с дедлайном</div>
                ) : (
                    <ResponsiveContainer width="100%" height={Math.max(120, executors.length * 42)}>
                        <BarChart data={executors} layout="vertical" margin={{ left: 8, right: 24 }}>
                            <XAxis type="number" domain={[0, 100]} tick={{ fill: "var(--text-muted)", fontSize: 12 }} unit="%" />
                            <YAxis type="category" dataKey="username" width={110} tick={{ fill: "var(--text)", fontSize: 12 }} />
                            <Tooltip
                                contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                                formatter={(value, _name, item) => [`${item.payload.on_time}/${item.payload.total_completed} в срок (${value}%)`, "Вовремя"]}
                            />
                            <Bar dataKey="on_time_rate" radius={[0, 6, 6, 0]}>
                                {executors.map((e, i) => (
                                    <Cell key={i} fill={e.on_time_rate >= 80 ? "var(--green)" : e.on_time_rate >= 50 ? "var(--amber)" : "var(--red)"} />
                                ))}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>

            <div className="card">
                <div className="section-header">
                    <div>
                        <div className="section-title">📊 Средняя просрочка — по проектам</div>
                        <div className="section-sub">Среди задач, закрытых с опозданием (в днях)</div>
                    </div>
                </div>
                {projects.length === 0 ? (
                    <div className="empty-state"><div className="empty-icon">📊</div>Пока нет данных по проектам</div>
                ) : (
                    <ResponsiveContainer width="100%" height={Math.max(160, projects.length * 50)}>
                        <BarChart data={projects} margin={{ left: -10, right: 12, top: 8 }}>
                            <XAxis dataKey="project_name" tick={{ fill: "var(--text-muted)", fontSize: 11 }} interval={0} angle={-20} textAnchor="end" height={60} />
                            <YAxis tick={{ fill: "var(--text-muted)", fontSize: 12 }} unit=" дн." />
                            <Tooltip
                                contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                                formatter={(value, _name, item) => [`${item.payload.completed_late}/${item.payload.total_completed} с опозданием`, `+${value} дн.`]}
                            />
                            <Bar dataKey="avg_overdue_days" radius={[6, 6, 0, 0]}>
                                {projects.map((p, i) => (
                                    <Cell key={i} fill={p.avg_overdue_days === 0 ? "var(--green)" : p.avg_overdue_days > 3 ? "var(--red)" : "var(--amber)"} />
                                ))}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                )}
            </div>
        </>
    );
}

// ─── Main App ─────────────────────────────────────────────
