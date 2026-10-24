import { useState } from "react";
import { apiRequest } from "../api";
import { Modal } from "./Modal";
import { plural } from "../constants/crm";

const EMPTY = "";
const TYPE_TITLES = { company: "Компания", person: "Частное лицо", auto: "Определять по названию" };
const shorten = (text, max = 18) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

// Импорт клиентов из CSV/Excel: файл → сопоставление колонок → предпросмотр → импорт → отчёт.
export function ClientImportModal({ token, onClose, onImported }) {
    const [step, setStep] = useState("file"); // file | map | preview | done
    const [file, setFile] = useState(null);
    const [info, setInfo] = useState(null); // ответ /clients/import/columns
    const [mapping, setMapping] = useState({}); // поле → индекс колонки ("" — не импортировать)
    const [defaultType, setDefaultType] = useState("company");
    const [skipDuplicates, setSkipDuplicates] = useState(true);
    const [report, setReport] = useState(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);

    const run = async fn => {
        setBusy(true);
        setError(null);
        try {
            await fn();
        } catch (e) {
            setError(e.message);
        } finally {
            setBusy(false);
        }
    };

    const chooseFile = e => {
        const picked = e.target.files?.[0];
        e.target.value = "";
        if (!picked) return;
        run(async () => {
            const fd = new FormData();
            fd.append("file", picked);
            const res = await apiRequest({ path: "/clients/import/columns", method: "POST", token, body: fd });
            const suggested = {};
            res.columns.forEach(c => { if (c.suggested) suggested[c.suggested] = String(c.index); });
            setFile(picked);
            setInfo(res);
            setMapping(suggested);
            setStep("map");
        });
    };

    const send = dryRun => run(async () => {
        const fd = new FormData();
        fd.append("file", file);
        const chosen = {};
        Object.entries(mapping).forEach(([key, index]) => { if (index !== EMPTY) chosen[key] = Number(index); });
        fd.append("mapping", JSON.stringify(chosen));
        fd.append("default_type", defaultType);
        fd.append("skip_duplicates", String(skipDuplicates));
        fd.append("dry_run", String(dryRun));
        const res = await apiRequest({ path: "/clients/import", method: "POST", token, body: fd });
        setReport(res);
        setStep(dryRun ? "preview" : "done");
        if (!dryRun) onImported?.();
    });

    const issues = (list, title, color) => list.length > 0 && (
        <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: "pointer", color }}>{title}: {list.length}</summary>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 12, maxHeight: 160, overflowY: "auto" }}>
                {list.map((i, n) => <li key={n}>строка {i.row}: {i.message}</li>)}
            </ul>
        </details>
    );

    const summary = report && (
        <div style={{ fontSize: 13 }}>
            <div>Тип, если не указан: <b>{TYPE_TITLES[report.default_type] ?? report.default_type}</b></div>
            <div>В файле: <b>{report.total_rows}</b> {plural(report.total_rows, "строка", "строки", "строк")}</div>
            <div>{report.dry_run ? "Будет создано" : "Создано"}: <b>{report.dry_run ? report.to_create : report.created}</b></div>
            {report.skipped_duplicates > 0 && <div>Пропущено дубликатов: <b>{report.skipped_duplicates}</b></div>}
            {issues(report.errors, "Пропущено из-за ошибок", "var(--red)")}
            {issues(report.warnings, "Предупреждения", "var(--text-dim)")}
            {issues(report.duplicates, "Дубликаты", "var(--text-dim)")}
            {report.dry_run && report.preview.length > 0 && (
                <table style={{ width: "100%", marginTop: 10, fontSize: 12, borderCollapse: "collapse" }}>
                    <thead><tr style={{ textAlign: "left", color: "var(--text-muted)" }}>
                        <th>Название</th><th>Тип</th><th>Телефон</th><th>Email</th>
                    </tr></thead>
                    <tbody>{report.preview.map(r => (
                        <tr key={r.row} style={{ borderTop: "1px solid var(--border)" }}>
                            <td>{r.name}</td><td>{r.client_type === "person" ? "Частное лицо" : "Компания"}</td>
                            <td>{r.phone || "—"}</td><td>{r.email || "—"}</td>
                        </tr>
                    ))}</tbody>
                </table>
            )}
            {report.dry_run && report.to_create > report.preview.length && (
                <div style={{ marginTop: 6, color: "var(--text-muted)" }}>Показаны первые {report.preview.length}.</div>
            )}
        </div>
    );

    return (
        <Modal title="Импорт клиентов" onClose={onClose} width={680}>
            {error && <div className="alert" style={{ marginBottom: 10 }}>{error}</div>}

            {step === "file" && (
                <div>
                    <p style={{ fontSize: 13, marginTop: 0 }}>
                        Загрузите файл .csv или .xlsx: первая строка — заголовки колонок. На следующем шаге
                        можно сопоставить колонки с полями клиента. Максимум 5000 строк.
                    </p>
                    <input type="file" accept=".csv,.xlsx" onChange={chooseFile} disabled={busy} />
                    {busy && <div style={{ marginTop: 8 }}>⏳ Читаю файл…</div>}
                </div>
            )}

            {step === "map" && info && (
                <div>
                    <div style={{ fontSize: 13, marginBottom: 10 }}>
                        Файл <b>{file?.name}</b>: {info.total_rows} {plural(info.total_rows, "строка", "строки", "строк")}.
                        Выберите, из какой колонки брать каждое поле.
                    </div>
                    {info.fields.map(f => (
                        <div key={f.key} className="form-group" style={{ display: "flex", gap: 10, alignItems: "center" }}>
                            <label className="form-label" style={{ flex: "0 0 240px", margin: 0 }}>
                                {f.label}{f.required ? " *" : ""}
                            </label>
                            <select
                                className="form-input" value={mapping[f.key] ?? EMPTY}
                                onChange={e => setMapping(m => ({ ...m, [f.key]: e.target.value }))}
                            >
                                <option value={EMPTY}>— не импортировать —</option>
                                {info.columns.map(c => {
                                    // колонку, уже выбранную для другого поля, показываем, но помечаем
                                    const usedBy = Object.entries(mapping).find(([k, v]) => k !== f.key && v === String(c.index));
                                    return (
                                        <option key={c.index} value={String(c.index)} disabled={Boolean(usedBy)}>
                                            {shorten(c.header, 28)}{c.samples.length ? ` (${c.samples.slice(0, 2).map(v => shorten(v)).join(", ")})` : ""}
                                        </option>
                                    );
                                })}
                            </select>
                        </div>
                    ))}
                    <div className="form-group" style={{ display: "flex", gap: 10, alignItems: "center" }}>
                        <label className="form-label" style={{ flex: "0 0 240px", margin: 0 }}>Тип, если не указан</label>
                        <select className="form-input" value={defaultType} onChange={e => setDefaultType(e.target.value)}>
                            <option value="company">Компания</option>
                            <option value="person">Частное лицо</option>
                            <option value="auto">Определять по названию</option>
                        </select>
                    </div>
                    {defaultType === "auto" && (
                        <div style={{ fontSize: 12, color: "var(--text-muted)", margin: "-4px 0 8px" }}>
                            «ООО …», кавычки и цифры в названии — компания, «Иванов Иван» — частное лицо. Это догадка:
                            проверьте тип в предпросмотре.
                        </div>
                    )}
                    <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer", width: "auto" }}>
                        <input type="checkbox" style={{ width: "auto" }} checked={skipDuplicates} onChange={e => setSkipDuplicates(e.target.checked)} />
                        Пропускать дубликаты (тот же телефон, email или название)
                    </label>
                    <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 14 }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => setStep("file")} disabled={busy}>Другой файл</button>
                        <button className="btn btn-primary btn-sm" onClick={() => send(true)} disabled={busy || (mapping.name ?? EMPTY) === EMPTY}>
                            {busy ? "Проверяю…" : "Предпросмотр"}
                        </button>
                    </div>
                </div>
            )}

            {step === "preview" && report && (
                <div>
                    {summary}
                    <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 14 }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => setStep("map")} disabled={busy}>Назад</button>
                        <button className="btn btn-primary btn-sm" onClick={() => send(false)} disabled={busy || report.to_create === 0}>
                            {busy ? "Импортирую…" : `Импортировать ${report.to_create}`}
                        </button>
                    </div>
                </div>
            )}

            {step === "done" && report && (
                <div>
                    {summary}
                    <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>
                        <button className="btn btn-primary btn-sm" onClick={onClose}>Готово</button>
                    </div>
                </div>
            )}
        </Modal>
    );
}
