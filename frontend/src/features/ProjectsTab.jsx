import { useState, useEffect } from "react";
import { apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { TaskCard } from "../components/TaskCard";
import { UserProfileAvatar } from "../components/UserProfileAvatar";
import { ICONS } from "../constants/icons";
import { extractItems } from "../utils/extractItems";

export function ProjectsTab({ token, canManage, currentUserId, currentRole }) {
    const [projects, setProjects] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [selectedProject, setSelectedProject] = useState(null);
    const [projectTasks, setProjectTasks] = useState([]);
    const [tasksLoading, setTasksLoading] = useState(false);
    const [showCreate, setShowCreate] = useState(false);
    const [createForm, setCreateForm] = useState({ name: "", description: "", group_id: "" });
    const [creating, setCreating] = useState(false);
    const [groups, setGroups] = useState([]);
    // const [showGroupPicker, setShowGroupPicker] = useState(false);
    const [groupPickerProjectId, setGroupPickerProjectId] = useState(null);
    const [settingGroup, setSettingGroup] = useState(false);

    // Редактирование проекта в списке
    const [editingProjectId, setEditingProjectId] = useState(null);
    const [editForm, setEditForm] = useState({ name: "", description: "" });
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
                }
            });
            setCreateForm({ name: "", description: "", group_id: "" });
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

    const pct = (p) => p.task_count > 0 ? Math.round((p.done_count / p.task_count) * 100) : 0;

    // ── Детальный вид проекта ──────────────────────────────
    if (selectedProject) {
        const progress = selectedProject.task_count > 0
            ? Math.round((selectedProject.done_count / selectedProject.task_count) * 100) : 0;
        return (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div className="card">
                    <button className="btn btn-ghost btn-sm" onClick={() => { setSelectedProject(null); setProjectTasks([]); }} style={{ marginBottom: 12 }}>
                        ← Назад к проектам
                    </button>
                    <div className="section-header">
                        <div>
                            <div className="section-title">{selectedProject.name}</div>
                            {selectedProject.description && (
                                <div className="section-sub">{selectedProject.description}</div>
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

                    <div className="stats-grid" style={{ marginBottom: 12 }}>
                        <div className="stat-box">
                            <div className="stat-value">{selectedProject.task_count}</div>
                            <div className="stat-label">Задач</div>
                        </div>
                        <div className="stat-box">
                            <div className="stat-value" style={{ color: "var(--green)" }}>{selectedProject.done_count}</div>
                            <div className="stat-label">Готово</div>
                        </div>
                        <div className="stat-box">
                            <div className="stat-value" style={{ color: "var(--accent-light)" }}>
                                {selectedProject.task_count - selectedProject.done_count}
                            </div>
                            <div className="stat-label">В работе</div>
                        </div>
                    </div>
                    <div className="progress-wrap" style={{ marginBottom: 16 }}>
                        <div className="progress-track">
                            <div className="progress-fill" style={{ width: `${progress}%` }} />
                        </div>
                        <div className="progress-caption">{progress}% выполнено</div>
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
                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                            {projectTasks.map(t => (
                                <TaskCard
                                    key={t.id}
                                    task={t}
                                    groups={[]}
                                    users={users}
                                    token={token}
                                    onToggle={async (task, newStatus) => {
                                        const nextIsDone = newStatus === "done";

                                        setProjectTasks(prev => prev.map(t =>
                                            t.id === task.id
                                                ? { ...t, status: newStatus, is_done: nextIsDone }
                                                : t
                                        ));

                                        try {
                                            await apiRequest({
                                                path: `/tasks/${task.id}/status`,
                                                method: "PATCH",
                                                token,
                                                body: { status: newStatus },
                                            });
                                        } catch {
                                            setProjectTasks(prev => prev.map(t =>
                                                t.id === task.id
                                                    ? { ...t, status: task.status, is_done: task.is_done }
                                                    : t
                                            ));
                                        }
                                    }}
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
                                    collapsible
                                    currentUserId={currentUserId}
                                    currentRole={currentRole}
                                />
                            ))}
                        </div>
                    )}
                </div>
            </div>
        );
    }

    // ── Список проектов ────────────────────────────────────
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div className="card">
                <div className="section-header">
                    <div>
                        <div className="section-title">Проекты</div>
                        <div className="section-sub">{total > 0 ? `${total} проектов` : "Нет проектов"}</div>
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                        <button className="btn btn-ghost btn-sm" onClick={loadProjects} disabled={loading}>
                            <Icon d={ICONS.refresh} /> Обновить
                        </button>
                        {canManage && (
                            <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(v => !v)}>
                                + Создать
                            </button>
                        )}
                    </div>
                </div>

                {showCreate && (
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
                )}
            </div>

            {loading ? (
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
            ) : projects.length === 0 ? (
                <div className="empty-state"><div className="empty-icon">📁</div>Нет доступных проектов</div>
            ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {projects.map(p => {
                        const isEditing = editingProjectId === p.id;
                        const isShowingMembers = membersProjectId === p.id;
                        const currentMembers = membersData[p.id] || p.members || [];
                        const notMember = users.filter(u => !currentMembers.some(m => m.id === u.id));
                        return (
                            <div key={p.id} className="card">
                                <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                                    <div style={{ fontSize: 28, lineHeight: 1, cursor: "pointer" }}
                                        onClick={() => openProject(p.id)}>📁</div>
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
                                                <div style={{ display: "flex", gap: 12, fontSize: 12, color: "var(--text-muted)", marginBottom: 8, cursor: "pointer" }}
                                                    onClick={() => openProject(p.id)}>
                                                    <span>📋 {p.task_count}</span>
                                                    <span style={{ color: "var(--green)" }}>✅ {p.done_count}</span>
                                                    {p.members?.length > 0 && <span>👥 {p.members.length}</span>}
                                                    {p.group?.name && <span>🏷 {p.group.name}</span>}
                                                </div>
                                                <div className="progress-wrap" style={{ cursor: "pointer" }}
                                                    onClick={() => openProject(p.id)}>
                                                    <div className="progress-track">
                                                        <div className="progress-fill" style={{ width: `${pct(p)}%` }} />
                                                    </div>
                                                    <div className="progress-caption">{pct(p)}%</div>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                    {canManage && !isEditing && (
                                        <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                                            <button className="btn btn-ghost btn-sm"
                                                title="Редактировать проект"
                                                onClick={e => {
                                                    e.stopPropagation();
                                                    setEditForm({ name: p.name, description: p.description || "" });
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
