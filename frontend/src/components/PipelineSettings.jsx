import { useEffect, useState } from "react";
import { apiRequest } from "../api";
import { Icon } from "./Icon";
import { ICONS } from "../constants/icons";
import { STAGE_KIND_COLORS } from "../constants/crm";

const KIND_LABELS = { open: "Обычная", won: "Успех (выигрыш)", lost: "Отказ (проигрыш)" };

/**
 * Настройка стадий воронки (только admin; сервер всё равно перепроверяет).
 * Переименование — по Enter или уходу из поля; порядок — стрелками (остальные стадии сдвигаются на сервере);
 * удалить нельзя стадию со сделками и последнюю стадию своего вида (сервер ответит 409 — текст покажем).
 * Вид стадии (обычная / успех / отказ) после создания не меняется.
 */
export function PipelineSettings({ token, stages, onChanged, onClose }) {
    const [names, setNames] = useState({});
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [newName, setNewName] = useState("");
    const [newKind, setNewKind] = useState("open");

    // поля имён синхронизируются со списком стадий после каждого обновления
    useEffect(() => { setNames(Object.fromEntries(stages.map(s => [s.id, s.name]))); }, [stages]);

    const run = async (request) => {
        setBusy(true);
        setError(null);
        try {
            await request();
            await onChanged();
        } catch (err) {
            setError(err.message);
            await onChanged(); // вернуть на экран то, что реально на сервере
        } finally {
            setBusy(false);
        }
    };

    const rename = (stage) => {
        const name = (names[stage.id] ?? "").trim();
        if (name === stage.name) return;
        if (!name) { setNames(n => ({ ...n, [stage.id]: stage.name })); return; }
        run(() => apiRequest({ path: `/pipeline/stages/${stage.id}`, method: "PATCH", token, body: { name } }));
    };

    const move = (stage, index, delta) =>
        run(() => apiRequest({ path: `/pipeline/stages/${stage.id}`, method: "PATCH", token, body: { position: index + delta } }));

    const remove = (stage) => {
        if (!window.confirm(`Удалить стадию «${stage.name}»?`)) return;
        run(() => apiRequest({ path: `/pipeline/stages/${stage.id}`, method: "DELETE", token }));
    };

    const add = (e) => {
        e.preventDefault();
        const name = newName.trim();
        if (!name) return;
        run(async () => {
            await apiRequest({ path: "/pipeline/stages", method: "POST", token, body: { name, kind: newKind } });
            setNewName("");
        });
    };

    return (
        <div className="card" style={{ marginBottom: 14 }}>
            <div className="section-header" style={{ marginBottom: 10 }}>
                <div>
                    <div className="section-title">Стадии воронки</div>
                    <div className="section-sub">Новая стадия добавляется в конец; порядок меняется стрелками</div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={onClose}>Готово</button>
            </div>
            {error && <div className="alert" style={{ marginBottom: 10 }}>{error}</div>}

            {stages.map((stage, i) => (
                <div key={stage.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
                    <span title={KIND_LABELS[stage.kind]} style={{ width: 10, height: 10, borderRadius: "50%", background: STAGE_KIND_COLORS[stage.kind], flexShrink: 0 }} />
                    <input
                        value={names[stage.id] ?? ""} maxLength={100} disabled={busy}
                        onChange={e => setNames(n => ({ ...n, [stage.id]: e.target.value }))}
                        onBlur={() => rename(stage)}
                        onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }}
                        style={{ flex: 1, padding: "6px 10px" }}
                    />
                    <span style={{ fontSize: 11, color: "var(--text-muted)", width: 120, flexShrink: 0 }}>{KIND_LABELS[stage.kind]}</span>
                    <button className="btn btn-ghost btn-sm" disabled={busy || i === 0} onClick={() => move(stage, i, -1)} title="Выше">↑</button>
                    <button className="btn btn-ghost btn-sm" disabled={busy || i === stages.length - 1} onClick={() => move(stage, i, 1)} title="Ниже">↓</button>
                    <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => remove(stage)} title="Удалить"><Icon d={ICONS.trash} /></button>
                </div>
            ))}

            <form className="form" onSubmit={add} style={{ marginTop: 12 }}>
                <div className="form-two-col">
                    <div className="form-group">
                        <label className="form-label">Новая стадия</label>
                        <input value={newName} onChange={e => setNewName(e.target.value)} maxLength={100} placeholder="Например, Договор" />
                    </div>
                    <div className="form-group">
                        <label className="form-label">Вид</label>
                        <select value={newKind} onChange={e => setNewKind(e.target.value)}>
                            {Object.entries(KIND_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                        </select>
                    </div>
                </div>
                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                    <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !newName.trim()}>
                        <Icon d={ICONS.plus} /> Добавить стадию
                    </button>
                </div>
            </form>
        </div>
    );
}
