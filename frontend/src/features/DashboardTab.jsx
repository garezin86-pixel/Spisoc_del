import { StatsDonut } from "../components/StatsDonut";
import { PRIORITY_COLORS, PRIORITY_LABELS } from "../constants/priority";
import { ROLE_LABELS } from "../constants/roles";
import { ManagerAnalyticsSection } from "./ManagerAnalyticsSection";

function Kpi({ label, value, sub, color }) {
    return (
        <div className="card home-kpi">
            <span className="home-kpi-label">{label}</span>
            <span className="home-kpi-value" style={color ? { color } : undefined}>{value}</span>
            {sub && <span className="home-kpi-sub">{sub}</span>}
        </div>
    );
}

function Progress({ percent }) {
    return (
        <div className="pj-prog">
            <div className="pj-prog-row"><span>Выполнено</span><span>{percent}%</span></div>
            <div className="pj-track"><div className="pj-fill" style={{ width: `${percent}%` }} /></div>
        </div>
    );
}

export function DashboardTab({ stats, loading, username, role, token }) {
    const isManagerOrAdmin = role === "admin" || role === "manager";
    const head = (
        <div className="cl-head">
            <div>
                <h1 className="cl-title">Статистика</h1>
                <div className="cl-sub">{username} · {ROLE_LABELS[role] ?? role}</div>
            </div>
        </div>
    );

    if (loading || !stats) {
        return (
            <div className="cl-page">
                {head}
                <div className="empty-state">
                    <div className="empty-icon">{loading ? "⏳" : "📊"}</div>
                    {loading ? "Загрузка статистики…" : "Нет данных"}
                </div>
                {isManagerOrAdmin && <ManagerAnalyticsSection token={token} />}
            </div>
        );
    }

    const total = stats.total ?? 0;
    const done = stats.done ?? 0;
    const aTotal = stats.a_total ?? 0;
    const aDone = stats.a_done ?? 0;
    const completionPercent = total > 0 ? Math.round((done / total) * 100) : 0;
    const authorPercent = aTotal > 0 ? Math.round((aDone / aTotal) * 100) : 0;

    return (
        <div className="cl-page">
            {head}

            <div className="home-kpis">
                <Kpi label="Назначено мне" value={total} sub={`в работе: ${stats.pending ?? 0}`} />
                <Kpi label="Выполнено мной" value={done} color="var(--green)" sub={`${completionPercent}% от назначенных`} />
                <Kpi label="Создано мной" value={aTotal} sub={`открыто: ${aTotal - aDone}`} />
                <Kpi label="Закрыто из созданных" value={aDone} color="var(--green)" sub={`${authorPercent}% от созданных`} />
            </div>

            <div className="st-cols">
                <div className="card">
                    <h3 className="cl-panel-title">Назначено мне</h3>
                    <Progress percent={completionPercent} />
                    <StatsDonut total={stats.total} done={stats.done} pending={stats.pending} />
                </div>
                <div className="card">
                    <h3 className="cl-panel-title">Создано мной</h3>
                    <Progress percent={authorPercent} />
                    <StatsDonut total={stats.a_total} done={stats.a_done} pending={aTotal - aDone} doneLabel="Закрыто" pendingLabel="Открыто" />
                </div>
            </div>

            {stats.tasks && stats.tasks.length > 0 && (
                <div className="card">
                    <h3 className="cl-panel-title">Последние задачи</h3>
                    <div className="st-tasks">
                        {stats.tasks.map(t => (
                            <div key={t.id} className="st-task">
                                <span aria-hidden="true">{t.is_done ? "✅" : "⏳"}</span>
                                <span className={`st-task-title${t.is_done ? " done" : ""}`}>{t.title}</span>
                                {t.priority && (
                                    <span className="pl-chip" style={{ background: PRIORITY_COLORS[t.priority] + "22", color: PRIORITY_COLORS[t.priority] }}>
                                        {PRIORITY_LABELS[t.priority] ?? t.priority}
                                    </span>
                                )}
                                {t.deadline && <span className="cl-muted">{t.deadline}</span>}
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
