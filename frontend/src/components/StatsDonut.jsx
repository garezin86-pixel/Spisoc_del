import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

export function StatsDonut({ total, done, pending, doneLabel = "Готово", pendingLabel = "В работе" }) {
    const rest = Math.max(0, (total ?? 0) - (done ?? 0) - (pending ?? 0));
    const data = [
        { name: doneLabel, value: done ?? 0, color: "var(--green)" },
        { name: pendingLabel, value: pending ?? 0, color: "var(--accent-light)" },
        { name: "Остальное", value: rest, color: "var(--border-hover)" },
    ].filter(d => d.value > 0);

    if (!total) {
        return (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 170, color: "var(--text-muted)", fontSize: 13 }}>
                Нет задач
            </div>
        );
    }

    return (
        <ResponsiveContainer width="100%" height={170}>
            <PieChart>
                <Pie data={data} dataKey="value" nameKey="name" innerRadius={38} outerRadius={58} paddingAngle={2} stroke="none">
                    {data.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Pie>
                <Tooltip contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
            </PieChart>
        </ResponsiveContainer>
    );
}
