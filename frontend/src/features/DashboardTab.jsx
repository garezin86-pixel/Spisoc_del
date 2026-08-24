import { StatsDonut } from "../components/StatsDonut";
import { PRIORITY_COLORS, PRIORITY_LABELS } from "../constants/priority";
import { ManagerAnalyticsSection } from "./ManagerAnalyticsSection";
import { PushNotificationsCard } from "./PushNotificationsCard";

export function DashboardTab({ stats, loading, username, role, token }) {
    const isManagerOrAdmin = role === "admin" || role === "manager";

    if (loading) {
        return (
            <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "0 0 32px" }}>
                <PushNotificationsCard token={token} />
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка дашборда…</div>
                {isManagerOrAdmin && <ManagerAnalyticsSection token={token} />}
            </div>
        );
    }
    if (!stats) {
        return (
            <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "0 0 32px" }}>
                <PushNotificationsCard token={token} />
                <div className="empty-state"><div className="empty-icon">📊</div>Нет данных</div>
                {isManagerOrAdmin && <ManagerAnalyticsSection token={token} />}
            </div>
        );
    }

    const completionPercent = stats.total > 0 ? Math.round((stats.done / stats.total) * 100) : 0;
    const authorPercent = stats.a_total > 0 ? Math.round((stats.a_done / stats.a_total) * 100) : 0;

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "0 0 32px" }}>
            {/* Приветствие */}
            <div className="card" style={{ background: "linear-gradient(135deg, var(--accent) 0%, var(--accent-light) 100%)", border: "none" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div style={{ width: 48, height: 48, borderRadius: "50%", background: "rgba(255,255,255,0.2)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, fontWeight: 700, color: "#fff" }}>
                        {(username || "U")[0].toUpperCase()}
                    </div>
                    <div>
                        <div style={{ fontSize: 18, fontWeight: 700, color: "#fff" }}>Привет, {username}!</div>
                        <div style={{ fontSize: 13, color: "rgba(255,255,255,0.8)" }}>Роль: {role}</div>
                    </div>
                </div>
            </div>

            <PushNotificationsCard token={token} />

            {/* Мои задачи (исполнитель) */}
            <div className="card">
                <div className="section-header">
                    <div className="section-title">Назначено мне</div>
                    <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{completionPercent}% выполнено</div>
                </div>
                <div className="stats-grid" style={{ marginBottom: 12 }}>
                    <div className="stat-box">
                        <div className="stat-value">{stats.total ?? 0}</div>
                        <div className="stat-label">Всего</div>
                    </div>
                    <div className="stat-box">
                        <div className="stat-value" style={{ color: "var(--green)" }}>{stats.done ?? 0}</div>
                        <div className="stat-label">Готово</div>
                    </div>
                    <div className="stat-box">
                        <div className="stat-value" style={{ color: "var(--accent-light)" }}>{stats.pending ?? 0}</div>
                        <div className="stat-label">В работе</div>
                    </div>
                </div>
                <div className="progress-wrap">
                    <div className="progress-track">
                        <div className="progress-fill" style={{ width: `${completionPercent}%` }} />
                    </div>
                    <div className="progress-caption">{completionPercent}%</div>
                </div>
                <StatsDonut total={stats.total} done={stats.done} pending={stats.pending} />
            </div>

            {/* Созданные мной */}
            <div className="card">
                <div className="section-header">
                    <div className="section-title">Создано мной</div>
                    <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{authorPercent}% выполнено</div>
                </div>
                <div className="stats-grid" style={{ marginBottom: 12 }}>
                    <div className="stat-box">
                        <div className="stat-value">{stats.a_total ?? 0}</div>
                        <div className="stat-label">Всего</div>
                    </div>
                    <div className="stat-box">
                        <div className="stat-value" style={{ color: "var(--green)" }}>{stats.a_done ?? 0}</div>
                        <div className="stat-label">Закрыто</div>
                    </div>
                    <div className="stat-box">
                        <div className="stat-value" style={{ color: "var(--accent-light)" }}>{(stats.a_total ?? 0) - (stats.a_done ?? 0)}</div>
                        <div className="stat-label">Открыто</div>
                    </div>
                </div>
                <div className="progress-wrap">
                    <div className="progress-track">
                        <div className="progress-fill" style={{ width: `${authorPercent}%` }} />
                    </div>
                    <div className="progress-caption">{authorPercent}%</div>
                </div>
                <StatsDonut total={stats.a_total} done={stats.a_done} pending={(stats.a_total ?? 0) - (stats.a_done ?? 0)} doneLabel="Закрыто" pendingLabel="Открыто" />
            </div>

            {/* Последние задачи */}
            {stats.tasks && stats.tasks.length > 0 && (
                <div className="card">
                    <div className="section-header">
                        <div className="section-title">Последние задачи</div>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        {stats.tasks.map(t => (
                            <div key={t.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
                                <span style={{ fontSize: 16 }}>{t.is_done ? "✅" : "⏳"}</span>
                                <span style={{ flex: 1, fontSize: 14, color: t.is_done ? "var(--text-muted)" : "var(--text)", textDecoration: t.is_done ? "line-through" : "none" }}>
                                    {t.title}
                                </span>
                                {t.priority && (
                                    <span style={{ fontSize: 11, padding: "2px 6px", borderRadius: 4, background: PRIORITY_COLORS[t.priority] + "22", color: PRIORITY_COLORS[t.priority], fontWeight: 600 }}>
                                        {PRIORITY_LABELS[t.priority] ?? t.priority}
                                    </span>
                                )}
                                {t.deadline && (
                                    <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{t.deadline}</span>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Аналитика для менеджера/админа — отдельная секция, подгружает свои данные сама */}
            {isManagerOrAdmin && <ManagerAnalyticsSection token={token} />}
        </div>
    );
}

// ─── Manager Analytics Section ─────────────────────────────
