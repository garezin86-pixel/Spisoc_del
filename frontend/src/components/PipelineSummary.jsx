import { useEffect, useState } from "react";
import { apiRequest } from "../api";
import { CLIENT_TYPES, STAGE_KIND_COLORS, formatTotals, plural, stageColor } from "../constants/crm";

// [{currency, count, amount}] → «16 000 ₴ · 2 500 $»; пусто → «—». Суммы разных валют не складываются.
function totalsText(totals) {
    const text = formatTotals(Object.fromEntries(totals.map(t => [t.currency, t.amount])));
    return text || "—";
}

function Card({ title, color, count, totals, hint }) {
    return (
        <div style={{ flex: "1 1 200px", background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "12px 14px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: color }} />{title}
            </div>
            <div style={{ fontSize: 22, fontWeight: 700 }}>{count}</div>
            <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 2 }}>{hint ?? totalsText(totals)}</div>
        </div>
    );
}

/**
 * Сводка по воронке: сколько сделок и на какие суммы (по валютам) в каждой стадии, итоги «в работе / выиграно /
 * проиграно» и конверсия won / (won + lost) среди закрытых сделок. owner — фильтр по ответственному.
 * refreshKey меняется, когда доска перечитала сделки: сводка обновляется следом.
 */
export function PipelineSummary({ token, users, pipelineId, refreshKey, onClose }) {
    const [ownerId, setOwnerId] = useState("");
    const [clientType, setClientType] = useState(""); // "" — все клиенты, "company" — B2B, "person" — B2C
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);

    useEffect(() => {
        let cancelled = false;
        const params = new URLSearchParams();
        if (ownerId) params.set("owner_id", ownerId);
        if (pipelineId) params.set("pipeline_id", pipelineId);
        if (clientType) params.set("client_type", clientType);
        const qs = params.toString() ? `?${params}` : "";
        apiRequest({ path: `/pipeline/summary${qs}`, token })
            .then(res => { if (!cancelled) { setData(res); setError(null); } })
            .catch(err => { if (!cancelled) setError(err.message); });
        return () => { cancelled = true; };
    }, [token, ownerId, pipelineId, clientType, refreshKey]);

    const maxCount = Math.max(1, ...(data?.stages ?? []).map(s => s.count));
    const conv = data?.conversion;

    return (
        <div className="card" style={{ marginBottom: 14 }}>
            <div className="section-header" style={{ marginBottom: 10 }}>
                <div>
                    <div className="section-title">Сводка по воронке{data ? ` «${data.pipeline_name}»` : ""}</div>
                    <div className="section-sub">Суммы разных валют показываются отдельно, по курсу не пересчитываются</div>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <select value={clientType} onChange={e => setClientType(e.target.value)} style={{ padding: "6px 10px", minWidth: 170 }}>
                        <option value="">Все клиенты</option>
                        {CLIENT_TYPES.map(t => <option key={t.key} value={t.key}>{t.icon} {t.label}</option>)}
                    </select>
                    {users.length > 0 && (
                        <select value={ownerId} onChange={e => setOwnerId(e.target.value)} style={{ padding: "6px 10px", minWidth: 180 }}>
                            <option value="">Все ответственные</option>
                            {users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                        </select>
                    )}
                    <button className="btn btn-ghost btn-sm" onClick={onClose}>Скрыть</button>
                </div>
            </div>

            {error && <div className="alert">{error}</div>}
            {!data && !error && <div style={{ color: "var(--text-muted)" }}>Загрузка…</div>}

            {data && (
                <>
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
                        <Card title="В работе" color={STAGE_KIND_COLORS.open} count={data.by_kind.open.count} totals={data.by_kind.open.totals} />
                        <Card title="Выиграно" color={STAGE_KIND_COLORS.won} count={data.by_kind.won.count} totals={data.by_kind.won.totals} />
                        <Card title="Проиграно" color={STAGE_KIND_COLORS.lost} count={data.by_kind.lost.count} totals={data.by_kind.lost.totals} />
                        <Card
                            title="Конверсия" color="var(--accent)"
                            count={conv.win_rate === null ? "—" : `${Math.round(conv.win_rate * 100)}%`}
                            hint={conv.closed === 0
                                ? "Пока нет закрытых сделок"
                                : `${conv.won} из ${conv.closed} закрытых ${plural(conv.closed, "сделки", "сделок", "сделок")} выиграно`}
                        />
                    </div>

                    {data.stages.map(stage => (
                        <div key={stage.stage_id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0", borderBottom: "1px solid var(--border)", fontSize: 13 }}>
                            <span style={{ width: 8, height: 8, borderRadius: "50%", background: stageColor(stage), flexShrink: 0 }} />
                            <span style={{ width: 150, flexShrink: 0, fontWeight: 600 }}>{stage.name}</span>
                            <div style={{ flex: 1, height: 6, background: "var(--surface2)", borderRadius: 3, overflow: "hidden" }}>
                                <div style={{ width: `${(stage.count / maxCount) * 100}%`, height: "100%", background: stageColor(stage) }} />
                            </div>
                            <span style={{ width: 30, textAlign: "right", color: "var(--text-dim)" }}>{stage.count}</span>
                            <span style={{ width: 230, textAlign: "right", color: "var(--text-dim)", flexShrink: 0 }}>{totalsText(stage.totals)}</span>
                        </div>
                    ))}
                </>
            )}
        </div>
    );
}
