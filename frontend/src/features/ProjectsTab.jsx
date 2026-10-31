import { useState, useEffect } from "react";
import { apiRequest } from "../api";
import { ClientPicker } from "../components/ClientPicker";
import { Icon } from "../components/Icon";
import { TaskCard } from "../components/TaskCard";
import { TaskRow } from "../components/TaskRow";
import { UserProfileAvatar } from "../components/UserProfileAvatar";
import { ICONS } from "../constants/icons";
import { extractItems } from "../utils/extractItems";

export function ProjectsTab({ token, canManage, currentUserId, currentRole, onOpenClient }) {
    const [projects, setProjects] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [selectedProject, setSelectedProject] = useState(null);
    const [projectTasks, setProjectTasks] = useState([]);
    const [tasksLoading, setTasksLoading] = useState(false);
    const [showCreate, setShowCreate] = useState(false);
    const [createForm, setCreateForm] = useState({ name: "", description: "", group_id: "", client_id: null, client_name: "" });
    const [clientFilter, setClientFilter] = useState(""); // "" — все, "none" — без клиента, иначе id клиента
    const [creating, setCreating] = useState(false);
    const [groups, setGroups] = useState([]);
    // const [showGroupPicker, setShowGroupPicker] = useState(false);
    const [groupPickerProjectId, setGroupPickerProjectId] = useState(null);
    const [settingGroup, setSettingGroup] = useState(false);

    // Редактирование проекта в списке
    const [editingProjectId, setEditingProjectId] = useState(null);
    const [editForm, setEditForm] = useState({ name: "", description: "", client_id: null, client_name: "" });
    const [saving, setSaving] = useState(false);

    // Управление участниками в списке
    const [membersProjectId, setMembersProjectId] = useState(null);
    const [membersData, setMembersData] = useState({}); // { [projectId]: [{id, username}] }
    const [addMemberUserId, setAddMemberUserId] = useState("");
    const [memberLoading, setMemberLoading] = useState(false);

    // Форма создания задачи внутри проекта
    const [showTaskForm, setShowTaskForm] = useState(false);
    const [taskForm, setTaskForm] = useState({ title: "", description: "", deadline: "", priority: "medium" });
    const [users, setUsers] = useState([]);
    const [assignUserId, setAssignUserId] = useState("");
    const [creatingTask, setCreatingTask] = useState(false);
    const [taskError, setTaskError] = useState(null);
    const [expandedTaskId, setExpandedTaskId] = useState(null);

    async function loadProjects() {
        setLoading(true);
        try {
            const data = await apiRequest({ path: "/projects?page=1&size=50", token });
            setProjects(extractItems(data));
            setTotal(data?.total ?? 0);
        } catch { setProjects([]); }
        finally { setLoading(false); }
    }

    async function loadUsers() {
        try {
            const data = await apiRequest({ path: "/users?page=1&size=100", token });
            setUsers(extractItems(data));
        } catch { setUsers([]); }
    }

    async function loadGroups() {
        try {
            const data = await apiRequest({ path: "/groups?page=1&size=100", token });
            setGroups(extractItems(data));
        } catch { setGroups([]); }
    }

    useEffect(() => { loadProjects(); loadUsers(); loadGroups(); }, []); // eslint-disable-line

    async function handleCreate(e) {
        e.preventDefault();
        if (!createForm.name.trim()) return;
        setCreating(true);
        setError(null);
        try {
            await apiRequest({
                path: "/projects", method: "POST", token, body: {
                    name: createForm.name.trim(),
                    description: createForm.description.trim() || null,
                    group_id: createForm.group_id ? Number(createForm.group_id) : null,
                    client_id: createForm.client_id || null,
                }
            });
            setCreateForm({ name: "", description: "", group_id: "", client_id: null, client_name: "" });
            setShowCreate(false);
            await loadProjects();
        } catch (err) { setError(err.message); }
        finally { setCreating(false); }
    }

    async function handleDelete(projectId) {
        if (!window.confirm("Удалить проект и все его задачи? Это действие необратимо.")) return;
        try {
            await apiRequest({ path: `/projects/${projectId}`, method: "DELETE", token });
            if (selectedProject?.id === projectId) {
                setSelectedProject(null);
                setProjectTasks([]);
            }
            await loadProjects();
        } catch (err) { setError(err.message); }
    }

    async function loadProjectTasks(projectId) {
        setTasksLoading(true);
        try {
            const data = await apiRequest({
                path: `/tasks/filter?project_id=${projectId}&page=1&size=100`, token
            });
            setProjectTasks(extractItems(data));
        } catch { setProjectTasks([]); }
        finally { setTasksLoading(false); }
    }

    async function openProject(projectId) {
        try {
            const data = await apiRequest({ path: `/projects/${projectId}`, token });
            setSelectedProject(data);
            setProjectTasks([]);
            setShowTaskForm(false);
            await loadProjectTasks(projectId);
        } catch (err) { setError(err.message); }
    }

    async function handleCreateTask(e) {
        e.preventDefault();
        if (!taskForm.title.trim() || !selectedProject) return;
        setCreatingTask(true);
        setTaskError(null);
        try {
            await apiRequest({
                path: "/tasks", method: "POST", token, body: {
                    title: taskForm.title.trim(),
                    description: taskForm.description.trim() || null,
                    deadline: taskForm.deadline ? `${taskForm.deadline}:00` : null,
                    priority: taskForm.priority || "medium",
                    project_id: selectedProject.id,
                    user_id: assignUserId ? Number(assignUserId) : null,
                }
            });
            setTaskForm({ title: "", description: "", deadline: "", priority: "medium" });
            setAssignUserId("");
            setShowTaskForm(false);
            await loadProjectTasks(selectedProject.id);
        } catch (err) { setTaskError(err.message); }
        finally { setCreatingTask(false); }
    }

    // async function handleSetGroup(groupId) {
    //     if (!selectedProject) return;
    //     setSettingGroup(true);
    //     try {
    //         await apiRequest({
    //             path: `/projects/${selectedProject.id}/group`,
    //             method: "PATCH",
    //             token,
    //             body: { group_id: groupId || null },
    //         });
    //         const data = await apiRequest({ path: `/projects/${selectedProject.id}`, token });
    //         setSelectedProject(data);
    //         setShowGroupPicker(false);
    //     } catch (err) { setError(err.message); }
    //     finally { setSettingGroup(false); }
    // }
    async function handleSetGroup(projectId, groupId) {
        setSettingGroup(true);

        try {
            await apiRequest({
                path: `/projects/${projectId}/group`,
                method: "PATCH",
                token,
                body: { group_id: groupId || null },
            });

            // обновляем список проектов
            await loadProjects();

            setGroupPickerProjectId(null);
        } catch (err) {
            setError(err.message);
        } finally {
            setSettingGroup(false);
        }
    }

    async function handleEditProject(e, projectId) {
        e.preventDefault();
        if (!editForm.name.trim()) return;
        setSaving(true);
        try {
            await apiRequest({
                path: `/projects/${projectId}`, method: "PATCH", token,
                body: { name: editForm.name.trim(), description: editForm.description.trim() || null },
            });
            // клиент меняется отдельным запросом — только если его действительно сменили
            const current = projects.find(x => x.id === projectId);
            if ((editForm.client_id ?? null) !== (current?.client_id ?? null)) {
                await apiRequest({
                    path: `/projects/${projectId}/client`, method: "PATCH", token,
                    body: { client_id: editForm.client_id ?? null },
                });
            }
            setEditingProjectId(null);
            await loadProjects();
        } catch (err) { setError(err.message); }
        finally { setSaving(false); }
    }

    async function loadProjectMembers(projectId) {
        try {
            const data = await apiRequest({ path: `/projects/${projectId}`, token });
            setMembersData(prev => ({ ...prev, [projectId]: data.members || [] }));
        } catch { /* ignore */ }
    }

    async function toggleMembersPanel(projectId, currentMembers) {
        if (membersProjectId === projectId) {
            setMembersProjectId(null);
            setAddMemberUserId("");
        } else {
            setMembersProjectId(projectId);
            setAddMemberUserId("");
            setMembersData(prev => ({ ...prev, [projectId]: currentMembers || [] }));
            await loadProjectMembers(projectId);
        }
    }

    async function handleAddMember(projectId) {
        if (!addMemberUserId) return;
        setMemberLoading(true);
        try {
            await apiRequest({ path: `/projects/${projectId}/members/${addMemberUserId}`, method: "POST", token });
            setAddMemberUserId("");
            await loadProjectMembers(projectId);
            await loadProjects();
        } catch (err) { setError(err.message); }
        finally { setMemberLoading(false); }
    }

    async function handleRemoveMember(projectId, userId) {
        setMemberLoading(true);
        try {
            await apiRequest({ path: `/projects/${projectId}/members/${userId}`, method: "DELETE", token });
            await loadProjectMembers(projectId);
            await loadProjects();
        } catch (err) { setError(err.message); }
        finally { setMemberLoading(false); }
    }

    async function toggleProjectTaskStatus(task, newStatus) {
        const nextIsDone = newStatus === "done";
        setProjectTasks(prev => prev.map(x => x.id === task.id ? { ...x, status: newStatus, is_done: nextIsDone } : x));
        try {
            await apiRequest({ path: `/tasks/${task.id}/status`, method: "PATCH", token, body: { status: newStatus } });
        } catch {
            setProjectTasks(prev => prev.map(x => x.id === task.id ? { ...x, status: task.status, is_done: task.is_done } : x));
        }
    }

    const pct = (p) => p.task_count > 0 ? Math.round((p.done_count / p.task_count) * 100) : 0;

    // ── Детальный вид проекта ──────────────────────────────
    if (selectedProject) {
        const progress = selectedProject.task_count > 0
            ? Math.round((selectedProject.done_count / selectedProject.task_count) * 100) : 0;
        return (
            <div className="cl-page">
                <nav className="cl-crumbs" aria-label="Путь">
                    <button type="button" className="cl-crumb-link" onClick={() => { setSelectedProject(null); setProjectTasks([]); setExpandedTaskId(null); }}>Проекты</button>
                    <span aria-hidden="true">/</span>
                    <span aria-current="page">{selectedProject.name}</span>
                </nav>
                <div className="card">
                    <div className="cl-head">
                        <div>
                            <h1 className="cl-title">{selectedProject.name}</h1>
                            {selectedProject.description && (
                                <div className="cl-sub">{selectedProject.description}</div>
                            )}
                            {selectedProject.client_name && (
                                <div style={{ marginTop: 8 }}>
                                    <button type="button" className="meta-chip pj-client" title="Открыть клиента"
                                        onClick={() => onOpenClient?.(selectedProject.client_id)}>
                                        <Icon d={ICONS.user} size={12} /> {selectedProject.client_name}
                                    </button>
                                </div>
                            )}
                            {selectedProject.group?.name && (
                                <div style={{ marginTop: 4 }}>
                                    <span className="meta-chip" style={{ fontSize: 12 }}>
                                        🏷 {selectedProject.group.name}
                                    </span>
                                </div>
                            )}
                        </div>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                            <button className="btn btn-primary btn-sm"
                                onClick={() => { setShowTaskForm(v => !v); setTaskError(null); }}>
                                <Icon d={ICONS.plus} /> Создать задачу
                            </button>
                            {canManage && (
                                <button className="btn btn-ghost btn-sm" style={{ color: "var(--red)" }}
                                    onClick={() => handleDelete(selectedProject.id)}>
                                    🗑 Удалить
                                </button>
                            )}
                        </div>
                    </div>

                    {/* Форма создания задачи */}
                    {showTaskForm && (
                        <form onSubmit={handleCreateTask} style={{
                            display: "flex", flexDirection: "column", gap: 10,
                            marginBottom: 16, padding: 14,
                            background: "var(--surface2)", borderRadius: 10,
                            border: "1px solid var(--border)"
                        }}>
                            {taskError && <div className="alert">{taskError}</div>}
                            <div className="form-group">
                                <label className="form-label">Заголовок *</label>
                                <input placeholder="Что нужно сделать?"
                                    value={taskForm.title}
                                    onChange={e => setTaskForm(f => ({ ...f, title: e.target.value }))} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Описание</label>
                                <textarea placeholder="Необязательно" rows={2}
                                    value={taskForm.description}
                                    onChange={e => setTaskForm(f => ({ ...f, description: e.target.value }))} />
                            </div>
                            <div className="form-two-col">
                                <div className="form-group">
                                    <label className="form-label">Дедлайн</label>
                                    <input type="datetime-local" value={taskForm.deadline}
                                        onChange={e => setTaskForm(f => ({ ...f, deadline: e.target.value }))} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">Приоритет</label>
                                    <select value={taskForm.priority}
                                        onChange={e => setTaskForm(f => ({ ...f, priority: e.target.value }))}>
                                        <option value="low">⚪ Низкий</option>
                                        <option value="medium">🔵 Средний</option>
                                        <option value="high">🟠 Высокий</option>
                                        <option value="critical">🔴 Критический</option>
                                    </select>
                                </div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">Назначить</label>
                                <select value={assignUserId}
                                    onChange={e => setAssignUserId(e.target.value)}>
                                    <option value="">— Никому —</option>
                                    {users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                                </select>
                            </div>
                            <div style={{ display: "flex", gap: 8 }}>
                                <button type="submit" className="btn btn-primary btn-sm"
                                    disabled={creatingTask || !taskForm.title.trim()}>
                                    <Icon d={ICONS.plus} /> {creatingTask ? "Создание…" : "Создать"}
                                </button>
                                <button type="button" className="btn btn-ghost btn-sm"
                                    onClick={() => { setShowTaskForm(false); setTaskError(null); }}>
                                    Отмена
                                </button>
                            </div>
                        </form>
                    )}

                    <div className="home-kpis pj-kpis">
                        <div className="card home-kpi"><span className="home-kpi-label">Задач</span><span className="home-kpi-value">{selectedProject.task_count}</span></div>
                        <div className="card home-kpi"><span className="home-kpi-label">Готово</span><span className="home-kpi-value" style={{ color: "var(--green)" }}>{selectedProject.done_count}</span></div>
                        <div className="card home-kpi"><span className="home-kpi-label">В работе</span><span className="home-kpi-value">{selectedProject.task_count - selectedProject.done_count}</span></div>
                    </div>
                    <div className="pj-prog">
                        <div className="pj-prog-row"><span>Прогресс проекта</span><span>{progress}%</span></div>
                        <div className="pj-track"><div className="pj-fill" style={{ width: `${progress}%` }} /></div>
                    </div>

                    {selectedProject.members && selectedProject.members.length > 0 && (
                        <div style={{ marginBottom: 16 }}>
                            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6 }}>
                                👥 Участники
                            </div>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                                {selectedProject.members.map(m => (
                                    <span key={m.id} className="meta-chip" style={{ cursor: "pointer" }}
                                        onClick={() => window.openUserProfile?.(m.id)}>
                                        <UserProfileAvatar userId={m.id} username={m.username} size={14} />
                                        {m.username}{m.position ? ` · ${m.position}` : ""}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}

                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-muted)" }}>
                            📋 Задачи проекта
                        </div>
                        <button className="btn btn-ghost btn-sm" onClick={() => loadProjectTasks(selectedProject.id)} disabled={tasksLoading}>
                            <Icon d={ICONS.refresh} /> {tasksLoading ? "…" : "Обновить"}
                        </button>
                    </div>

                    {tasksLoading ? (
                        <div className="empty-state" style={{ padding: "16px 0" }}>
                            <div className="empty-icon">⏳</div>Загрузка задач…
                        </div>
                    ) : projectTasks.length === 0 ? (
                        <div className="empty-state" style={{ padding: "16px 0" }}>
                            <div className="empty-icon">📋</div>Нет задач в проекте
                        </div>
                    ) : (
                        <div className="tr-table" role="table" aria-label="Задачи проекта">
                            {projectTasks.map(t => (
                                <TaskRow
                                    key={t.id} task={t} hideSelect
                                    expanded={expandedTaskId === t.id}
                                    onToggleExpand={() => setExpandedTaskId(id => id === t.id ? null : t.id)}
                                    onToggleStatus={toggleProjectTaskStatus}
                                >
                                <TaskCard
                                    key={t.id}
                                    task={t}
                                    groups={[]}
                                    users={users}
                                    token={token}
                                    onToggle={toggleProjectTaskStatus}
                                    onDelete={async (task) => {
                                        if (!window.confirm("Удалить задачу?")) return;
                                        setProjectTasks(prev => prev.filter(t => t.id !== task.id));
                                        try {
                                            await apiRequest({ path: `/tasks/${task.id}`, method: "DELETE", token });
                                        } catch {
                                            await loadProjectTasks(selectedProject.id);
                                        }
                                    }}
                                    onUpdate={async (task, updates) => {
                                        setProjectTasks(prev => prev.map(t =>
                                            t.id === task.id ? { ...t, ...updates } : t
                                        ));
                                        try {
                                            await apiRequest({
                                                path: `/tasks/${task.id}`,
                                                method: "PATCH",
                                                token,
                                                body: updates,
                                            });
                                        } catch {
                                            await loadProjectTasks(selectedProject.id);
                                        }
                                    }}
                                    onReassign={async (taskId, userId, groupId) => {
                                        await apiRequest({
                                            path: `/tasks/${taskId}`,
                                            method: "PATCH",
                                            token,
                                            body: { user_id: userId, group_id: groupId },
                                        });
                                        await loadProjectTasks(selectedProject.id);
                                    }}
                                    hideReassign
                                    currentUserId={currentUserId}
                                    currentRole={currentRole}
                                />
                                </TaskRow>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        );
    }

    // ── Список проектов ────────────────────────────────────
    // Клиенты, у которых есть проекты (для фильтра), и список с учётом выбранного клиента
    const clientOptions = [...new Map(projects.filter(p => p.client_id && p.client_name).map(p => [p.client_id, { id: p.client_id, name: p.client_name }])).values()]
        .sort((a, b) => a.name.localeCompare(b.name, "ru"));
    const shownProjects = projects.filter(p => (
        !clientFilter || (clientFilter === "none" ? !p.client_id : String(p.client_id) === clientFilter)
    ));
    return (
        <div className="cl-page">
            <div className="cl-head">
                <div>
                    <h1 className="cl-title">Проекты</h1>
                    <div className="cl-sub">{total > 0 ? `${total} проектов · ` : "Нет проектов. "}Проекты, их прогресс и участники.</div>
                </div>
                <div className="cl-actions">
                    <button className="btn btn-ghost" onClick={loadProjects} disabled={loading}>
                        <Icon d={ICONS.refresh} /> Обновить
                    </button>
                    {canManage && (
                        <button className="btn btn-primary" onClick={() => setShowCreate(v => !v)} aria-expanded={showCreate}>
                            <Icon d={ICONS.plus} /> Новый проект
                        </button>
                    )}
                </div>
            </div>

            {showCreate && (
                <div className="card">
                    <form onSubmit={handleCreate} style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12, padding: 12, background: "var(--surface)", borderRadius: 8 }}>
                        {error && <div className="alert">{error}</div>}
                        <div className="form-group">
                            <label className="form-label">Название *</label>
                            <input className="form-input" placeholder="Например, Редизайн сайта"
                                value={createForm.name}
                                onChange={e => setCreateForm(f => ({ ...f, name: e.target.value }))} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">Описание</label>
                            <textarea className="form-input" placeholder="Необязательно" rows={2}
                                value={createForm.description}
                                onChange={e => setCreateForm(f => ({ ...f, description: e.target.value }))} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">Группа</label>
                            <select value={createForm.group_id}
                                onChange={e => setCreateForm(f => ({ ...f, group_id: e.target.value }))}>
                                <option value="">— Без группы —</option>
                                {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                            </select>
                        </div>
                        <div className="form-group">
                            <label className="form-label">Клиент</label>
                            <ClientPicker token={token} value={createForm.client_id} name={createForm.client_name}
                                onChange={(id, name) => setCreateForm(f => ({ ...f, client_id: id, client_name: name }))} />
                        </div>
                        <div style={{ display: "flex", gap: 8 }}>
                            <button type="submit" className="btn btn-primary btn-sm"
                                disabled={creating || !createForm.name.trim()}>
                                {creating ? "Создание…" : "Создать"}
                            </button>
                            <button type="button" className="btn btn-ghost btn-sm"
                                onClick={() => { setShowCreate(false); setError(null); }}>
                                Отмена
                            </button>
                        </div>
                    </form>
                </div>
            )}

            {clientOptions.length > 0 && (
                <div className="cl-filters">
                    <select className="form-input dl-select" aria-label="Клиент" value={clientFilter} onChange={e => setClientFilter(e.target.value)}>
                        <option value="">Клиент: все</option>
                        <option value="none">Без клиента</option>
                        {clientOptions.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                    {clientFilter && <button type="button" className="btn btn-ghost" onClick={() => setClientFilter("")}>Сбросить</button>}
                </div>
            )}

            {loading ? (
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
            ) : shownProjects.length === 0 && projects.length > 0 ? (
                <div className="empty-state"><div className="empty-icon">🔍</div>Нет проектов по выбранному клиенту</div>
            ) : projects.length === 0 ? (
                <div className="empty-state"><div className="empty-icon">📁</div>Нет доступных проектов</div>
            ) : (
                <div className="pj-grid">
                    {shownProjects.map(p => {
                        const isEditing = editingProjectId === p.id;
                        const isShowingMembers = membersProjectId === p.id;
                        const currentMembers = membersData[p.id] || p.members || [];
                        const notMember = users.filter(u => !currentMembers.some(m => m.id === u.id));
                        return (
                            <div key={p.id} className="card pj-card">
                                <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        {isEditing ? (
                                            <form onSubmit={e => handleEditProject(e, p.id)}
                                                style={{ display: "flex", flexDirection: "column", gap: 8 }}
                                                onClick={e => e.stopPropagation()}>
                                                <input value={editForm.name}
                                                    onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))}
                                                    placeholder="Название проекта"
                                                    style={{ fontWeight: 600, fontSize: 14 }}
                                                    autoFocus />
                                                <textarea value={editForm.description}
                                                    onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))}
                                                    placeholder="Описание (необязательно)" rows={2} />
                                                <ClientPicker token={token} value={editForm.client_id} name={editForm.client_name}
                                                    onChange={(id, name) => setEditForm(f => ({ ...f, client_id: id, client_name: name }))} />
                                                <div style={{ display: "flex", gap: 6 }}>
                                                    <button type="submit" className="btn btn-primary btn-sm"
                                                        disabled={saving || !editForm.name.trim()}>
                                                        <Icon d={ICONS.save} /> {saving ? "…" : "Сохранить"}
                                                    </button>
                                                    <button type="button" className="btn btn-ghost btn-sm"
                                                        onClick={() => setEditingProjectId(null)}>
                                                        <Icon d={ICONS.x} /> Отмена
                                                    </button>
                                                </div>
                                            </form>
                                        ) : (
                                            <>
                                                <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4, cursor: "pointer" }}
                                                    onClick={() => openProject(p.id)}>
                                                    {p.name}
                                                </div>
                                                {p.description && (
                                                    <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 6, cursor: "pointer" }}
                                                        onClick={() => openProject(p.id)}>
                                                        {p.description}
                                                    </div>
                                                )}
                                                <div style={{ cursor: "pointer" }} onClick={() => openProject(p.id)}>
                                                    <div className="pj-prog-row"><span>{p.done_count} из {p.task_count} задач</span><span>{pct(p)}%</span></div>
                                                    <div className="pj-track"><div className="pj-fill" style={{ width: `${pct(p)}%` }} /></div>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                </div>

                                {!isEditing && (
                                    <div className="pj-foot">
                                        <span className="pj-chips">
                                            {p.client_name && (
                                                <button type="button" className="meta-chip pj-client" title="Открыть клиента"
                                                    onClick={e => { e.stopPropagation(); onOpenClient?.(p.client_id); }}>
                                                    <Icon d={ICONS.user} size={12} /> {p.client_name}
                                                </button>
                                            )}
                                            {p.group?.name && <span className="meta-chip">🏷 {p.group.name}</span>}
                                            {p.members?.length > 0 && <span className="meta-chip">👥 {p.members.length}</span>}
                                        </span>
                                    {canManage && !isEditing && (
                                            <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                                                <button className="btn btn-ghost btn-sm"
                                                    title="Редактировать проект"
                                                    onClick={e => {
                                                        e.stopPropagation();
                                                        setEditForm({ name: p.name, description: p.description || "", client_id: p.client_id ?? null, client_name: p.client_name || "" });
                                                        setEditingProjectId(p.id);
                                                        setMembersProjectId(null);
                                                    }}>
                                                    <Icon d={ICONS.edit} />
                                                </button>
                                                <button className="btn btn-ghost btn-sm"
                                                    title="Участники"
                                                    style={{ color: isShowingMembers ? "var(--accent-light)" : undefined }}
                                                    onClick={e => { e.stopPropagation(); toggleMembersPanel(p.id, p.members); }}>
                                                    <Icon d={ICONS.userPlus} />
                                                </button>
                                                {/* сюда кнопку  */}
                                                <button
                                                    className="btn btn-ghost btn-sm"
                                                    title={p.group ? "Сменить группу" : "Привязать группу"}
                                                    onClick={e => {
                                                        e.stopPropagation();
                                                        setGroupPickerProjectId(
                                                            groupPickerProjectId === p.id ? null : p.id
                                                        );
                                                    }}
                                                >
                                                    🏷
                                                </button>
                                                <button className="btn btn-ghost btn-sm"
                                                    title="Удалить проект"
                                                    style={{ color: "var(--red)" }}
                                                    onClick={e => { e.stopPropagation(); handleDelete(p.id); }}>
                                                    <Icon d={ICONS.trash} />
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {/* Панель выбора группы */}
                                {groupPickerProjectId === p.id && canManage && (
                                    <div
                                        style={{
                                            marginTop: 12,
                                            padding: 12,
                                            background: "var(--surface2)",
                                            borderRadius: 8,
                                            border: "1px solid var(--border)"
                                        }}
                                    >
                                        <select
                                            defaultValue={p.group_id || ""}
                                            onChange={e =>
                                                handleSetGroup(
                                                    p.id,
                                                    e.target.value ? Number(e.target.value) : null
                                                )
                                            }
                                            disabled={settingGroup}
                                            style={{ width: "100%" }}
                                        >
                                            <option value="">— Без группы —</option>
                                            {groups.map(g => (
                                                <option key={g.id} value={g.id}>
                                                    {g.name}
                                                </option>
                                            ))}
                                        </select>

                                        <button
                                            className="btn btn-ghost btn-sm"
                                            style={{ marginTop: 8 }}
                                            onClick={() => setGroupPickerProjectId(null)}
                                        >
                                            Отмена
                                        </button>
                                    </div>
                                )}

                                {/* Панель управления участниками */}
                                {isShowingMembers && canManage && (
                                    <div style={{
                                        marginTop: 12, padding: 12,
                                        background: "var(--surface2)", borderRadius: 8,
                                        border: "1px solid var(--border)"
                                    }}>
                                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 8 }}>
                                            👥 Участники проекта
                                        </div>
                                        {currentMembers.length === 0 ? (
                                            <div style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 8 }}>
                                                Нет участников
                                            </div>
                                        ) : (
                                            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
                                                {currentMembers.map(m => (
                                                    <span key={m.id} style={{
                                                        display: "inline-flex", alignItems: "center", gap: 4,
                                                        padding: "2px 8px", borderRadius: 12,
                                                        background: "var(--surface)", border: "1px solid var(--border)",
                                                        fontSize: 12,
                                                    }}>
                                                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer" }}
                                                            onClick={() => window.openUserProfile?.(m.id)}>
                                                            <UserProfileAvatar userId={m.id} username={m.username} size={14} />
                                                            {m.username}{m.position ? ` · ${m.position}` : ""}
                                                        </span>
                                                        <button
                                                            onClick={() => handleRemoveMember(p.id, m.id)}
                                                            disabled={memberLoading}
                                                            style={{
                                                                background: "none", border: "none", cursor: "pointer",
                                                                color: "var(--red)", padding: 0, lineHeight: 1,
                                                                display: "flex", alignItems: "center",
                                                            }}
                                                            title="Удалить участника">
                                                            <Icon d={ICONS.x} size={12} />
                                                        </button>
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                        <div style={{ display: "flex", gap: 6 }}>
                                            <select value={addMemberUserId}
                                                onChange={e => setAddMemberUserId(e.target.value)}
                                                style={{ flex: 1 }}
                                                disabled={memberLoading}>
                                                <option value="">Добавить участника…</option>
                                                {notMember.map(u => (
                                                    <option key={u.id} value={u.id}>{u.username}</option>
                                                ))}
                                            </select>
                                            <button className="btn btn-primary btn-sm"
                                                onClick={() => handleAddMember(p.id)}
                                                disabled={memberLoading || !addMemberUserId}>
                                                <Icon d={ICONS.userPlus} /> {memberLoading ? "…" : "Добавить"}
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

// ─── Groups Tab ───────────────────────────────────────────
// ─── TeamTab — справочник всей команды (плоский список, в отличие от
// "Группы", где пользователи сгруппированы и есть управление составом) ────
