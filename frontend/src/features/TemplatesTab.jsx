import { useState, useEffect, useRef } from "react";
import { apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { ICONS } from "../constants/icons";
import { PRIORITY_COLORS, PRIORITY_LABELS, PRIORITY_ICONS } from "../constants/priority";
import { extractItems } from "../utils/extractItems";

export function TemplatesTab({ token }) {
    const [view, setView] = useState("list");
    const [templates, setTemplates] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [saving, setSaving] = useState(false);
    const [editingTemplate, setEditingTemplate] = useState(null);
    const [form, setForm] = useState({ title: "", description: "" });
    const [items, setItems] = useState([]);
    const [applyTemplate, setApplyTemplate] = useState(null);
    const [projects, setProjects] = useState([]);
    const [applyProjectId, setApplyProjectId] = useState("");
    const [applying, setApplying] = useState(false);
    const [applySuccess, setApplySuccess] = useState(null);
    const [expandedItems, setExpandedItems] = useState(new Set());
    const dragIdx = useRef(null);

    function toggleExpanded(idx) {
        setExpandedItems(prev => {
            const next = new Set(prev);
            if (next.has(idx)) next.delete(idx); else next.add(idx);
            return next;
        });
    }

    async function loadTemplates() {
        setLoading(true); setError(null);
        try {
            const data = await apiRequest({ path: "/templates", token });
            setTemplates(Array.isArray(data) ? data : []);
        } catch (e) { setError(e.message); }
        finally { setLoading(false); }
    }

    async function loadProjects() {
        try {
            const data = await apiRequest({ path: "/projects?page=1&size=100", token });
            setProjects(extractItems(data));
        } catch { setProjects([]); }
    }

    useEffect(() => { loadTemplates(); loadProjects(); }, []); // eslint-disable-line

    function openCreate() {
        setEditingTemplate(null);
        setForm({ title: "", description: "" });
        setItems([]);
        setView("create");
    }

    function openEdit(tpl) {
        setEditingTemplate(tpl);
        setForm({ title: tpl.title, description: tpl.description || "" });
        setItems([...tpl.items].sort((a, b) => a.order_index - b.order_index)
            .map(it => ({
                title: it.title,
                description: it.description || "",
                priority: it.priority,
                deadline_offset_days: it.deadline_offset_days ?? "",
                tagsText: (it.tags || []).join(", "),
                checklistText: (it.checklist || []).join("\n"),
                order_index: it.order_index,
            })));
        setView("edit");
    }

    function addItem() {
        setItems(prev => [...prev, {
            title: "", description: "", priority: "medium",
            deadline_offset_days: "", tagsText: "", checklistText: "",
            order_index: prev.length,
        }]);
    }

    function removeItem(idx) {
        setItems(prev => prev.filter((_, i) => i !== idx).map((it, i) => ({ ...it, order_index: i })));
    }

    function updateItem(idx, field, value) {
        setItems(prev => prev.map((it, i) => i === idx ? { ...it, [field]: value } : it));
    }

    function onDragStart(idx) { dragIdx.current = idx; }
    function onDragOver(e, idx) {
        e.preventDefault();
        if (dragIdx.current === null || dragIdx.current === idx) return;
        const next = [...items];
        const [moved] = next.splice(dragIdx.current, 1);
        next.splice(idx, 0, moved);
        dragIdx.current = idx;
        setItems(next.map((it, i) => ({ ...it, order_index: i })));
    }
    function onDragEnd() { dragIdx.current = null; }

    async function handleSave() {
        if (!form.title.trim()) return;
        setSaving(true); setError(null);
        const body = {
            title: form.title.trim(),
            description: form.description.trim() || null,
            items: items.filter(it => it.title.trim())
                .map((it, i) => ({
                    title: it.title.trim(),
                    description: it.description?.trim() || null,
                    priority: it.priority,
                    deadline_offset_days: it.deadline_offset_days === "" || it.deadline_offset_days == null
                        ? null : Number(it.deadline_offset_days),
                    tags: (it.tagsText || "").split(",").map(t => t.trim()).filter(Boolean),
                    checklist: (it.checklistText || "").split("\n").map(t => t.trim()).filter(Boolean),
                    order_index: i,
                })),
        };
        try {
            if (view === "edit" && editingTemplate) {
                await apiRequest({ path: `/templates/${editingTemplate.id}`, method: "PUT", token, body });
            } else {
                await apiRequest({ path: "/templates", method: "POST", token, body });
            }
            await loadTemplates();
            setView("list");
        } catch (e) { setError(e.message); }
        finally { setSaving(false); }
    }

    async function handleDelete(id) {
        if (!window.confirm("Удалить шаблон?")) return;
        try {
            await apiRequest({ path: `/templates/${id}`, method: "DELETE", token });
            await loadTemplates();
        } catch (e) { setError(e.message); }
    }

    function openApply(tpl) {
        setApplyTemplate(tpl);
        setApplyProjectId(projects.length > 0 ? String(projects[0].id) : "");
        setApplySuccess(null);
    }

    async function handleApply() {
        if (!applyProjectId || !applyTemplate) return;
        setApplying(true);
        try {
            const created = await apiRequest({
                path: `/templates/${applyTemplate.id}/apply`,
                method: "POST", token,
                body: { project_id: Number(applyProjectId) },
            });
            setApplySuccess(Array.isArray(created) ? created.length : "?");
        } catch (e) { setError(e.message); setApplyTemplate(null); }
        finally { setApplying(false); }
    }

    const TEMPLATE_ICON = "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zm-1 1.5L18.5 9H13V3.5zM6 20V4h5v7h7v9H6z";

    if (view === "create" || view === "edit") {
        return (
            <div className="card" style={{ marginTop: 0 }}>
                <div className="section-header">
                    <div>
                        <div className="section-title">{view === "edit" ? "Редактировать шаблон" : "Новый шаблон"}</div>
                        <div className="section-sub">Добавьте задачи, которые будут созданы при применении</div>
                    </div>
                    <button className="btn btn-ghost btn-sm" onClick={() => setView("list")}>
                        <Icon d={ICONS.x} /> Отмена
                    </button>
                </div>
                {error && <div style={{ color: "var(--red)", marginBottom: 12, fontSize: 13 }}>{error}</div>}
                <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 20 }}>
                    <div>
                        <label className="field-label">НАЗВАНИЕ ШАБЛОНА</label>
                        <input className="input" placeholder="Например: Спринт разработки"
                            value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} />
                    </div>
                    <div>
                        <label className="field-label">ОПИСАНИЕ (необязательно)</label>
                        <textarea className="input" rows={2} placeholder="Для чего этот шаблон…"
                            value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                            style={{ resize: "vertical" }} />
                    </div>
                </div>
                <div style={{ marginBottom: 12 }}>
                    <label className="field-label">ЗАДАЧИ В ШАБЛОНЕ</label>
                    {items.length === 0 && (
                        <div style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 8 }}>
                            Нет задач. Добавьте хотя бы одну.
                        </div>
                    )}
                    {items.map((item, idx) => (
                        <div key={idx}
                            style={{
                                marginBottom: 8, padding: "8px 10px", background: "var(--bg-card2)",
                                borderRadius: 8, border: "1px solid var(--border)",
                            }}>
                            <div draggable
                                onDragStart={() => onDragStart(idx)}
                                onDragOver={e => onDragOver(e, idx)}
                                onDragEnd={onDragEnd}
                                style={{ display: "flex", alignItems: "center", gap: 8, cursor: "grab" }}>
                                <span style={{ color: "var(--text-muted)", fontSize: 16, cursor: "grab", flexShrink: 0 }}>⠿</span>
                                <input className="input" placeholder="Название задачи" value={item.title}
                                    onChange={e => updateItem(idx, "title", e.target.value)}
                                    style={{ flex: 1, marginBottom: 0 }} />
                                <select className="input" value={item.priority}
                                    onChange={e => updateItem(idx, "priority", e.target.value)}
                                    style={{ width: 130, flexShrink: 0, color: PRIORITY_COLORS[item.priority], marginBottom: 0 }}>
                                    {Object.entries(PRIORITY_LABELS).map(([val, label]) => (
                                        <option key={val} value={val}>{PRIORITY_ICONS[val]} {label}</option>
                                    ))}
                                </select>
                                <button type="button" className="btn btn-ghost btn-sm" onClick={() => toggleExpanded(idx)}
                                    title="Описание, дедлайн, теги, чек-лист" style={{ flexShrink: 0 }}>
                                    {expandedItems.has(idx) ? "▲" : "⚙"}
                                </button>
                                <button className="btn btn-ghost btn-sm" onClick={() => removeItem(idx)}
                                    style={{ flexShrink: 0, color: "var(--red)" }}>
                                    <Icon d={ICONS.x} />
                                </button>
                            </div>
                            {expandedItems.has(idx) && (
                                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8, paddingLeft: 24 }}>
                                    <textarea className="input" rows={2} placeholder="Описание задачи (необязательно)"
                                        value={item.description || ""} onChange={e => updateItem(idx, "description", e.target.value)}
                                        style={{ marginBottom: 0, resize: "vertical" }} />
                                    <div style={{ display: "flex", gap: 8 }}>
                                        <div style={{ flex: 1 }}>
                                            <label className="field-label">ДЕДЛАЙН, ДНЕЙ ОТ ПРИМЕНЕНИЯ</label>
                                            <input className="input" type="number" min={0} max={3650}
                                                placeholder="Например: 3"
                                                value={item.deadline_offset_days}
                                                onChange={e => updateItem(idx, "deadline_offset_days", e.target.value)}
                                                style={{ marginBottom: 0 }} />
                                        </div>
                                        <div style={{ flex: 1 }}>
                                            <label className="field-label">ТЕГИ ЧЕРЕЗ ЗАПЯТУЮ</label>
                                            <input className="input" placeholder="срочно, клиент"
                                                value={item.tagsText || ""}
                                                onChange={e => updateItem(idx, "tagsText", e.target.value)}
                                                style={{ marginBottom: 0 }} />
                                        </div>
                                    </div>
                                    <div>
                                        <label className="field-label">ЧЕК-ЛИСТ — ПО ПУНКТУ НА СТРОКУ</label>
                                        <textarea className="input" rows={3} placeholder={"Подготовить материалы\nСогласовать с руководителем"}
                                            value={item.checklistText || ""} onChange={e => updateItem(idx, "checklistText", e.target.value)}
                                            style={{ marginBottom: 0, resize: "vertical" }} />
                                    </div>
                                </div>
                            )}
                        </div>
                    ))}
                    <button className="btn btn-ghost btn-sm" onClick={addItem} style={{ marginTop: 4 }}>
                        <Icon d={ICONS.plus} /> Добавить задачу
                    </button>
                </div>
                <button className="btn btn-primary" onClick={handleSave}
                    disabled={saving || !form.title.trim()} style={{ width: "100%", marginTop: 8 }}>
                    <Icon d={ICONS.save} /> {saving ? "Сохранение…" : view === "edit" ? "Сохранить изменения" : "Создать шаблон"}
                </button>
            </div>
        );
    }

    return (
        <>
            <div className="card" style={{ marginTop: 0 }}>
                <div className="section-header">
                    <div>
                        <div className="section-title">Шаблоны задач</div>
                        <div className="section-sub">
                            {templates.length > 0
                                ? `${templates.length} шаблон${templates.length === 1 ? "" : templates.length < 5 ? "а" : "ов"}`
                                : "Создайте шаблон и применяйте его к проектам"}
                        </div>
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                        <button className="btn btn-ghost btn-sm" onClick={loadTemplates} disabled={loading}>
                            <Icon d={ICONS.refresh} /> Обновить
                        </button>
                        <button className="btn btn-primary btn-sm" onClick={openCreate}>
                            <Icon d={ICONS.plus} /> Новый шаблон
                        </button>
                    </div>
                </div>
                {error && <div style={{ color: "var(--red)", marginBottom: 12, fontSize: 13 }}>{error}</div>}
                {loading ? (
                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                ) : templates.length === 0 ? (
                    <div className="empty-state" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
                        <div className="empty-icon">📋</div>
                        <span>Нет шаблонов</span>
                        <button className="btn btn-primary btn-sm" onClick={openCreate}>
                            <Icon d={ICONS.plus} /> Создать первый шаблон
                        </button>
                    </div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 12 }}>
                        {templates.map(tpl => (
                            <div key={tpl.id} style={{
                                background: "var(--bg-card2)", border: "1px solid var(--border)",
                                borderRadius: 12, padding: "14px 16px",
                            }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                                            <Icon d={TEMPLATE_ICON} size={16} />
                                            <span style={{ fontWeight: 600, fontSize: 15 }}>{tpl.title}</span>
                                        </div>
                                        {tpl.description && (
                                            <div style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 8 }}>
                                                {tpl.description}
                                            </div>
                                        )}
                                        {tpl.items && tpl.items.length > 0 ? (
                                            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                                                {[...tpl.items].sort((a, b) => a.order_index - b.order_index).map(item => (
                                                    <span key={item.id} className="meta-chip" style={{
                                                        background: PRIORITY_COLORS[item.priority] + "18",
                                                        color: PRIORITY_COLORS[item.priority],
                                                        border: `1px solid ${PRIORITY_COLORS[item.priority]}33`,
                                                    }}>
                                                        {PRIORITY_ICONS[item.priority]} {item.title}
                                                        {item.deadline_offset_days != null && ` · ⏰${item.deadline_offset_days}д`}
                                                        {item.tags && item.tags.length > 0 && ` · 🏷${item.tags.length}`}
                                                        {item.checklist && item.checklist.length > 0 && ` · ☑${item.checklist.length}`}
                                                    </span>
                                                ))}
                                            </div>
                                        ) : (
                                            <span style={{ color: "var(--text-muted)", fontSize: 12 }}>Нет задач</span>
                                        )}
                                    </div>
                                    <div style={{ display: "flex", flexDirection: "column", gap: 6, flexShrink: 0 }}>
                                        <button className="btn btn-primary btn-sm" onClick={() => openApply(tpl)}
                                            disabled={!tpl.items || tpl.items.length === 0}>
                                            ▶ Использовать
                                        </button>
                                        <button className="btn btn-ghost btn-sm" onClick={() => openEdit(tpl)}>
                                            <Icon d={ICONS.edit} /> Изменить
                                        </button>
                                        <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(tpl.id)}
                                            style={{ color: "var(--red)" }}>
                                            <Icon d={ICONS.trash} /> Удалить
                                        </button>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {applyTemplate && (
                <div style={{
                    position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    zIndex: 1000, padding: 16,
                }} onClick={e => { if (e.target === e.currentTarget) { setApplyTemplate(null); setApplySuccess(null); } }}>
                    <div style={{
                        background: "var(--bg-card)", border: "1px solid var(--border)",
                        borderRadius: 16, padding: 24, width: "100%", maxWidth: 420,
                    }}>
                        {applySuccess !== null ? (
                            <div style={{ textAlign: "center" }}>
                                <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
                                <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 8 }}>Создано {applySuccess} задач</div>
                                <div style={{ color: "var(--text-muted)", fontSize: 14, marginBottom: 20 }}>
                                    Задачи из шаблона «{applyTemplate.title}» добавлены в проект.
                                </div>
                                <button className="btn btn-primary" style={{ width: "100%" }}
                                    onClick={() => { setApplyTemplate(null); setApplySuccess(null); }}>
                                    Закрыть
                                </button>
                            </div>
                        ) : (
                            <>
                                <div style={{ fontWeight: 700, fontSize: 17, marginBottom: 4 }}>Применить шаблон</div>
                                <div style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 20 }}>
                                    «{applyTemplate.title}» — {applyTemplate.items?.length ?? 0} задач
                                </div>
                                <label className="field-label">ВЫБЕРИТЕ ПРОЕКТ</label>
                                {projects.length === 0 ? (
                                    <div style={{ color: "var(--red)", fontSize: 13, marginBottom: 16 }}>
                                        Нет доступных проектов. Сначала создайте проект.
                                    </div>
                                ) : (
                                    <select className="input" value={applyProjectId}
                                        onChange={e => setApplyProjectId(e.target.value)}
                                        style={{ marginBottom: 20 }}>
                                        {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                                    </select>
                                )}
                                <div style={{ display: "flex", gap: 8 }}>
                                    <button className="btn btn-ghost" style={{ flex: 1 }}
                                        onClick={() => { setApplyTemplate(null); setApplySuccess(null); }}>
                                        Отмена
                                    </button>
                                    <button className="btn btn-primary" style={{ flex: 1 }}
                                        onClick={handleApply}
                                        disabled={applying || !applyProjectId || projects.length === 0}>
                                        {applying ? "Создание…" : "Создать задачи"}
                                    </button>
                                </div>
                            </>
                        )}
                    </div>
                </div>
            )}
        </>
    );
}

// ─── ProjectsTab ──────────────────────────────────────────
