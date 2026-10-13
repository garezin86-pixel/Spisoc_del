import { useEffect, useRef, useState } from "react";
import { apiRequest } from "../api";
import { Icon } from "./Icon";
import { ICONS } from "../constants/icons";
import { STAGE_COLOR_PRESETS, STAGE_KIND_COLORS, plural, stageColor } from "../constants/crm";

const KIND_LABELS = { open: "Обычная", won: "Успех (выигрыш)", lost: "Отказ (проигрыш)" };

/**
 * Выбор цвета стадии: палитра (применяется через полсекунды после последнего изменения, чтобы не слать запрос
 * на каждое движение ползунка), готовые цвета (применяются сразу) и сброс на цвет по виду стадии.
 */
function ColorField({ value, fallback, disabled, onCommit }) {
    const [draft, setDraft] = useState(value ?? fallback);
    const timer = useRef(null);

    useEffect(() => { setDraft(value ?? fallback); }, [value, fallback]);
    useEffect(() => () => clearTimeout(timer.current), []);

    const pick = (color) => {
        clearTimeout(timer.current);
        setDraft(color);
        timer.current = setTimeout(() => onCommit(color), 500);
    };
    const commitNow = (color) => {
        clearTimeout(timer.current);
        setDraft(color);
        onCommit(color);
    };

    return (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
            <input
                type="color" value={draft} disabled={disabled} onChange={e => pick(e.target.value)} title="Свой цвет"
                style={{ width: 34, height: 30, padding: 2, flex: "none", cursor: "pointer" }}
            />
            {STAGE_COLOR_PRESETS.map(color => (
                <button
                    key={color} type="button" disabled={disabled} onClick={() => commitNow(color)} title={color}
                    style={{
                        width: 16, height: 16, borderRadius: "50%", background: color, padding: 0, cursor: "pointer", flex: "none",
                        border: draft.toLowerCase() === color ? "2px solid var(--text)" : "1px solid var(--border)",
                    }}
                />
            ))}
            <button
                type="button" className="btn btn-ghost btn-sm" disabled={disabled || !value} onClick={() => commitNow(null)}
                title="Сбросить на цвет по умолчанию" style={{ padding: "2px 6px" }}
            >↺</button>
        </span>
    );
}

/**
 * Настройка воронок (только admin; сервер всё равно перепроверяет).
 * Воронки: создать (минимальную или копию стадий другой), переименовать, удалить (нельзя единственную и со сделками).
 * Стадии выбранной воронки: переименовать, цвет, порядок стрелками, удалить, добавить.
 * Вид стадии (обычная / успех / отказ) после создания не меняется.
 */
export function PipelineSettings({ token, pipelines, selectedId, onSelect, dealsCountOf, onChanged, onClose }) {
    const pipeline = pipelines.find(p => p.id === selectedId) ?? pipelines[0];
    const stages = pipeline?.stages ?? [];

    const [stageNames, setStageNames] = useState({});
    const [pipelineNames, setPipelineNames] = useState({});
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [newPipeline, setNewPipeline] = useState({ name: "", copy_from_id: "" });
    const [newStage, setNewStage] = useState({ name: "", kind: "open" });

    useEffect(() => { setStageNames(Object.fromEntries(stages.map(s => [s.id, s.name]))); }, [stages]);
    useEffect(() => { setPipelineNames(Object.fromEntries(pipelines.map(p => [p.id, p.name]))); }, [pipelines]);

    const run = async (request) => {
        setBusy(true);
        setError(null);
        try {
            return await request();
        } catch (err) {
            setError(err.message);
            return undefined;
        } finally {
            await onChanged(); // что бы ни случилось — на экране то, что реально на сервере
            setBusy(false);
        }
    };

    // ── воронки ──
    const renamePipeline = (p) => {
        const name = (pipelineNames[p.id] ?? "").trim();
        if (name === p.name) return;
        if (!name) { setPipelineNames(n => ({ ...n, [p.id]: p.name })); return; }
        run(() => apiRequest({ path: `/pipelines/${p.id}`, method: "PATCH", token, body: { name } }));
    };
    const removePipeline = (p) => {
        if (!window.confirm(`Удалить воронку «${p.name}» вместе со стадиями?`)) return;
        run(() => apiRequest({ path: `/pipelines/${p.id}`, method: "DELETE", token }));
    };
    const addPipeline = async (e) => {
        e.preventDefault();
        const name = newPipeline.name.trim();
        if (!name) return;
        const body = { name };
        if (newPipeline.copy_from_id) body.copy_from_id = Number(newPipeline.copy_from_id);
        const created = await run(() => apiRequest({ path: "/pipelines", method: "POST", token, body }));
        if (created) {
            setNewPipeline({ name: "", copy_from_id: "" });
            onSelect(created.id); // сразу открываем новую воронку, чтобы настроить её стадии
        }
    };

    // ── стадии ──
    const patchStage = (stage, body) =>
        run(() => apiRequest({ path: `/pipeline/stages/${stage.id}`, method: "PATCH", token, body }));
    const renameStage = (stage) => {
        const name = (stageNames[stage.id] ?? "").trim();
        if (name === stage.name) return;
        if (!name) { setStageNames(n => ({ ...n, [stage.id]: stage.name })); return; }
        patchStage(stage, { name });
    };
    const moveStage = (stage, index, delta) => patchStage(stage, { position: index + delta });
    const removeStage = (stage) => {
        if (!window.confirm(`Удалить стадию «${stage.name}»?`)) return;
        run(() => apiRequest({ path: `/pipeline/stages/${stage.id}`, method: "DELETE", token }));
    };
    const addStage = async (e) => {
        e.preventDefault();
        const name = newStage.name.trim();
        if (!name || !pipeline) return;
        const created = await run(() => apiRequest({
            path: "/pipeline/stages", method: "POST", token, body: { name, kind: newStage.kind, pipeline_id: pipeline.id },
        }));
        if (created) setNewStage(s => ({ ...s, name: "" }));
    };

    return (
        <div className="card" style={{ marginBottom: 14 }}>
            <div className="section-header" style={{ marginBottom: 10 }}>
                <div>
                    <div className="section-title">Воронки</div>
                    <div className="section-sub">У каждой воронки свои стадии; сделка живёт в одной воронке</div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={onClose}>Готово</button>
            </div>
            {error && <div className="alert" style={{ marginBottom: 10 }}>{error}</div>}

            {pipelines.map(p => {
                const count = dealsCountOf(p);
                const active = p.id === pipeline?.id;
                return (
                    <div key={p.id} style={{
                        display: "flex", alignItems: "center", gap: 8, padding: "6px 8px", marginBottom: 4, borderRadius: "var(--radius-sm)",
                        border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`, background: active ? "rgba(124,106,240,0.08)" : "transparent",
                    }}>
                        <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => onSelect(p.id)} title="Настроить стадии этой воронки" style={{ flex: "none" }}>
                            {active ? "●" : "○"}
                        </button>
                        <input
                            value={pipelineNames[p.id] ?? ""} maxLength={100} disabled={busy}
                            onChange={e => setPipelineNames(n => ({ ...n, [p.id]: e.target.value }))}
                            onBlur={() => renamePipeline(p)}
                            onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }}
                            style={{ flex: 1, padding: "6px 10px" }}
                        />
                        <span style={{ fontSize: 11, color: "var(--text-muted)", width: 110, flexShrink: 0, textAlign: "right" }}>
                            {p.stages.length} {plural(p.stages.length, "стадия", "стадии", "стадий")} · {count} {plural(count, "сделка", "сделки", "сделок")}
                        </span>
                        <button className="btn btn-ghost btn-sm" disabled={busy || pipelines.length < 2} onClick={() => removePipeline(p)}
                            title={pipelines.length < 2 ? "Единственную воронку удалить нельзя" : count ? "В воронке есть сделки" : "Удалить воронку"}>
                            <Icon d={ICONS.trash} />
                        </button>
                    </div>
                );
            })}

            <form className="form" onSubmit={addPipeline} style={{ marginTop: 10 }}>
                <div className="form-two-col">
                    <div className="form-group">
                        <label className="form-label">Новая воронка</label>
                        <input value={newPipeline.name} maxLength={100} placeholder="Например, Партнёры"
                            onChange={e => setNewPipeline(f => ({ ...f, name: e.target.value }))} />
                    </div>
                    <div className="form-group">
                        <label className="form-label">Стадии</label>
                        <select value={newPipeline.copy_from_id} onChange={e => setNewPipeline(f => ({ ...f, copy_from_id: e.target.value }))}>
                            <option value="">Минимальные (Новая → Успех / Отказ)</option>
                            {pipelines.map(p => <option key={p.id} value={p.id}>Скопировать из «{p.name}»</option>)}
                        </select>
                    </div>
                </div>
                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                    <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !newPipeline.name.trim()}>
                        <Icon d={ICONS.plus} /> Добавить воронку
                    </button>
                </div>
            </form>

            {pipeline && (
                <div style={{ marginTop: 16, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
                    <div className="section-title" style={{ fontSize: 14, marginBottom: 2 }}>Стадии воронки «{pipeline.name}»</div>
                    <div className="section-sub" style={{ marginBottom: 8 }}>Порядок меняется стрелками; новая стадия добавляется в конец</div>

                    {stages.map((stage, i) => (
                        <div key={stage.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", borderBottom: "1px solid var(--border)", flexWrap: "wrap" }}>
                            <span title={KIND_LABELS[stage.kind]} style={{ width: 10, height: 10, borderRadius: "50%", background: stageColor(stage), flexShrink: 0 }} />
                            <input
                                value={stageNames[stage.id] ?? ""} maxLength={100} disabled={busy}
                                onChange={e => setStageNames(n => ({ ...n, [stage.id]: e.target.value }))}
                                onBlur={() => renameStage(stage)}
                                onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }}
                                style={{ flex: "1 1 180px", padding: "6px 10px", minWidth: 140 }}
                            />
                            <ColorField
                                value={stage.color} fallback={STAGE_KIND_COLORS[stage.kind]} disabled={busy}
                                onCommit={color => patchStage(stage, { color })}
                            />
                            <span style={{ fontSize: 11, color: "var(--text-muted)", width: 110, flexShrink: 0 }}>{KIND_LABELS[stage.kind]}</span>
                            <button className="btn btn-ghost btn-sm" disabled={busy || i === 0} onClick={() => moveStage(stage, i, -1)} title="Выше">↑</button>
                            <button className="btn btn-ghost btn-sm" disabled={busy || i === stages.length - 1} onClick={() => moveStage(stage, i, 1)} title="Ниже">↓</button>
                            <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => removeStage(stage)} title="Удалить"><Icon d={ICONS.trash} /></button>
                        </div>
                    ))}

                    <form className="form" onSubmit={addStage} style={{ marginTop: 12 }}>
                        <div className="form-two-col">
                            <div className="form-group">
                                <label className="form-label">Новая стадия</label>
                                <input value={newStage.name} onChange={e => setNewStage(f => ({ ...f, name: e.target.value }))} maxLength={100} placeholder="Например, Договор" />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Вид</label>
                                <select value={newStage.kind} onChange={e => setNewStage(f => ({ ...f, kind: e.target.value }))}>
                                    {Object.entries(KIND_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                                </select>
                            </div>
                        </div>
                        <div style={{ display: "flex", justifyContent: "flex-end" }}>
                            <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !newStage.name.trim()}>
                                <Icon d={ICONS.plus} /> Добавить стадию
                            </button>
                        </div>
                    </form>
                </div>
            )}
        </div>
    );
}
