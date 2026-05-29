import { useEffect, useMemo, useState } from "react";
import { apiRequest } from "./api";

const initialForm = {
    title: "",
    description: "",
    deadline: "",
};

function decodeToken(token) {
    try {
        const payload = token.split(".")[1];
        const base64 = payload.replace(/-/g, "+").replace(/_/g, "/").padEnd(payload.length + (4 - (payload.length % 4)) % 4, "=");
        const decoded = atob(base64);
        const json = decodeURIComponent(
            Array.from(decoded)
                .map((char) => `%${(`00${char.charCodeAt(0).toString(16)}`).slice(-2)}`)
                .join("")
        );
        return JSON.parse(json);
    } catch {
        return null;
    }
}

function App() {
    const [token, setToken] = useState(localStorage.getItem("spisoc_token"));
    const [tasks, setTasks] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [filterType, setFilterType] = useState("");
    const [isDone, setIsDone] = useState("");
    const [groups, setGroups] = useState([]);
    const [assignType, setAssignType] = useState("self");
    const [selectedGroupId, setSelectedGroupId] = useState("");
    const [selectedUserId, setSelectedUserId] = useState("");
    const [users, setUsers] = useState([]);
    const [taskDone, setTaskDone] = useState(false);
    const [form, setForm] = useState(initialForm);

    const currentUserId = useMemo(() => {
        if (!token) return null;
        const payload = decodeToken(token);
        return payload?.sub ? Number(payload.sub) : null;
    }, [token]);

    useEffect(() => {
        if (token) {
            loadTasks();
            loadGroups();
            loadUsers();
        }
    }, [token, filterType, isDone]);

    async function loadGroups() {
        try {
            const data = await apiRequest({ path: "/groups", token });
            setGroups(Array.isArray(data) ? data : []);
        } catch (err) {
            // ignore group load errors for non-admin users
            setGroups([]);
        }
    }

    async function loadUsers() {
        try {
            const data = await apiRequest({ path: "/users", token });
            setUsers(Array.isArray(data) ? data : []);
        } catch (err) {
            // ignore user load errors for non-admin users
            setUsers([]);
        }
    }

    async function handleLogin(event) {
        event.preventDefault();
        const formData = new FormData(event.target);
        const username = formData.get("username");
        const password = formData.get("password");

        try {
            setError(null);
            const response = await apiRequest({
                path: "/auth/login",
                method: "POST",
                body: { username, password },
            });
            localStorage.setItem("spisoc_token", response.access_token);
            setToken(response.access_token);
        } catch (err) {
            setError(err.message);
        }
    }

    async function loadTasks() {
        setLoading(true);
        try {
            const query = new URLSearchParams();
            query.set("filter_user_group", "user");
            if (filterType) query.set("filter_type", filterType);
            if (isDone) query.set("is_done", isDone);

            const data = await apiRequest({
                path: `/tasks/filter?${query.toString()}`,
                token,
            });
            setTasks(data);
        } catch (err) {
            handleAuthError(err);
        } finally {
            setLoading(false);
        }
    }

    function handleAuthError(err) {
        if (err.message.includes("401") || err.message.includes("403") || err.message.includes("invalid")) {
            logout();
        } else {
            setError(err.message);
        }
    }

    function logout() {
        localStorage.removeItem("spisoc_token");
        setToken(null);
        setTasks([]);
    }

    async function handleCreateTask(event) {
        event.preventDefault();
        if (!form.title.trim()) {
            setError("Введите заголовок задачи");
            return;
        }

        try {
            setError(null);
            const payload = {
                title: form.title.trim(),
                description: form.description.trim() || null,
                is_done: taskDone,
                deadline: form.deadline ? `${form.deadline}:00` : null,
            };

            if (assignType === "self") {
                payload.user_id = currentUserId;
                payload.group_id = null;
            } else if (assignType === "user") {
                payload.user_id = selectedUserId ? Number(selectedUserId) : null;
                payload.group_id = null;
            } else if (assignType === "group") {
                payload.group_id = selectedGroupId ? Number(selectedGroupId) : null;
                payload.user_id = null;
            } else {
                payload.user_id = null;
                payload.group_id = null;
            }

            await apiRequest({ path: "/tasks/", method: "POST", token, body: payload });
            setForm(initialForm);
            setAssignType("self");
            setSelectedGroupId("");
            setSelectedUserId("");
            setTaskDone(false);
            await loadTasks();
        } catch (err) {
            handleAuthError(err);
        }
    }

    async function handleToggleTask(task) {
        try {
            setError(null);
            await apiRequest({
                path: `/tasks/${task.id}`,
                method: "PATCH",
                token,
                body: { is_done: !task.is_done },
            });
            await loadTasks();
        } catch (err) {
            handleAuthError(err);
        }
    }

    async function handleDeleteTask(task) {
        try {
            setError(null);
            await apiRequest({ path: `/tasks/${task.id}`, method: "DELETE", token });
            await loadTasks();
        } catch (err) {
            handleAuthError(err);
        }
    }

    const stats = useMemo(() => {
        const total = tasks.length;
        const done = tasks.filter((task) => task.is_done).length;
        return {
            total,
            done,
            pending: total - done,
            percent: total > 0 ? Math.round((done / total) * 100) : 0,
        };
    }, [tasks]);

    if (!token) {
        return (
            <div className="page-shell">
                <div className="card auth-card">
                    <h1>Войти в Spisoc</h1>
                    <p className="subtitle">Используйте данные из backend-системы.</p>
                    <form className="form" onSubmit={handleLogin}>
                        <label>
                            Имя пользователя
                            <input name="username" placeholder="admin" required minLength={3} />
                        </label>
                        <label>
                            Пароль
                            <input name="password" type="password" placeholder="••••••••" required minLength={3} />
                        </label>
                        <button type="submit" className="button primary">Войти</button>
                        {error && <div className="alert">{error}</div>}
                    </form>
                </div>
            </div>
        );
    }

    return (
        <div className="page-shell">
            <header className="app-header">
                <div>
                    <p className="eyebrow">Spisoc</p>
                    <h1>Управление задачами</h1>
                    <p className="lead">Просматривайте, создавайте и отмечайте задачи в реальном времени.</p>
                </div>
                <button className="button secondary" onClick={logout}>
                    Выйти
                </button>
            </header>

            <div className="content-grid">
                <section className="card sidebar-card">
                    <div className="panel">
                        <h2>Статистика</h2>
                        <div className="stats-row">
                            <div>
                                <span>{stats.total}</span>
                                <p>Всего задач</p>
                            </div>
                            <div>
                                <span>{stats.done}</span>
                                <p>Выполнено</p>
                            </div>
                            <div>
                                <span>{stats.pending}</span>
                                <p>В работе</p>
                            </div>
                        </div>
                        <div className="progress">
                            <div className="progress-bar" style={{ width: `${stats.percent}%` }} />
                        </div>
                        <p className="progress-text">Завершено {stats.percent}% задач</p>
                    </div>

                    <div className="panel">
                        <h2>Фильтры</h2>
                        <form className="form" onSubmit={(event) => {
                            event.preventDefault();
                            loadTasks();
                        }}>
                            <label>
                                Тип задачи
                                <select value={filterType} onChange={(event) => setFilterType(event.target.value)}>
                                    <option value="">Все</option>
                                    <option value="today">На сегодня</option>
                                    <option value="overdue">Просроченные</option>
                                    <option value="planned">Запланированные</option>
                                    <option value="deadline_null">Без дедлайна</option>
                                </select>
                            </label>
                            <label>
                                Статус
                                <select value={isDone} onChange={(event) => setIsDone(event.target.value)}>
                                    <option value="">Все</option>
                                    <option value="false">Не выполненные</option>
                                    <option value="true">Выполненные</option>
                                </select>
                            </label>
                            <button type="submit" className="button primary">Применить</button>
                        </form>
                    </div>
                </section>

                <section className="main-column">
                    <div className="card">
                        <div className="panel-header">
                            <div>
                                <h2>Новая задача</h2>
                                <p>Сохраните задачу себе. Она появится в вашем списке.</p>
                            </div>
                        </div>
                        <form className="form" onSubmit={handleCreateTask}>
                            <label>
                                Заголовок
                                <input
                                    value={form.title}
                                    onChange={(event) => setForm({ ...form, title: event.target.value })}
                                    placeholder="Например, Проверить почту"
                                    required
                                />
                            </label>
                            <label>
                                Описание
                                <textarea
                                    value={form.description}
                                    onChange={(event) => setForm({ ...form, description: event.target.value })}
                                    placeholder="Дополнительные детали"
                                />
                            </label>
                            <label>
                                Дедлайн
                                <input
                                    type="datetime-local"
                                    value={form.deadline}
                                    onChange={(event) => setForm({ ...form, deadline: event.target.value })}
                                />
                            </label>
                            <label>
                                Статус задачи
                                <select value={taskDone ? "done" : "new"} onChange={(event) => setTaskDone(event.target.value === "done")}>
                                    <option value="new">В работе</option>
                                    <option value="done">Выполнено</option>
                                </select>
                            </label>
                            <label>
                                К кому назначить
                                <select value={assignType} onChange={(event) => setAssignType(event.target.value)}>
                                    <option value="self">Себе</option>
                                    <option value="user">Пользователю</option>
                                    <option value="group">Группе</option>
                                    <option value="none">Никому</option>
                                </select>
                            </label>
                            {assignType === "group" && (
                                <label>
                                    Выберите группу
                                    <select value={selectedGroupId} onChange={(event) => setSelectedGroupId(event.target.value)}>
                                        <option value="">Выберите группу</option>
                                        {groups.map((group) => (
                                            <option key={group.id} value={group.id}>
                                                {group.name}
                                            </option>
                                        ))}
                                    </select>
                                </label>
                            )}
                            {assignType === "user" && (
                                <label>
                                    Выберите пользователя
                                    <select value={selectedUserId} onChange={(event) => setSelectedUserId(event.target.value)}>
                                        <option value="">Выберите пользователя</option>
                                        {users.map((user) => (
                                            <option key={user.id} value={user.id}>
                                                {user.username}
                                            </option>
                                        ))}
                                    </select>
                                </label>
                            )}
                            <button type="submit" className="button primary">Создать задачу</button>
                            {error && <div className="alert">{error}</div>}
                        </form>
                    </div>

                    <div className="card">
                        <div className="panel-header">
                            <div>
                                <h2>Задачи</h2>
                                <p>Список задач, назначенных вам.</p>
                            </div>
                            <button className="button secondary" onClick={loadTasks} disabled={loading}>
                                Обновить
                            </button>
                        </div>

                        {loading ? (
                            <div className="empty-state">Загрузка...</div>
                        ) : tasks.length === 0 ? (
                            <div className="empty-state">Нет задач для отображения.</div>
                        ) : (
                            <div className="task-list">
                                {tasks.map((task) => (
                                    <article key={task.id} className={`task-card ${task.is_done ? "done" : "pending"}`}>
                                        <div className="task-card-main">
                                            <div>
                                                <h3>{task.title}</h3>
                                                <p className="task-meta">{task.description || "Без описания"}</p>
                                                <p className="task-meta">
                                                    Дедлайн: <strong>{task.deadline || "—"}</strong>
                                                </p>
                                                <p className="task-meta">Автор: {task.author?.username || "—"}</p>
                                                {task.user?.username && (
                                                    <p className="task-meta">
                                                        Исполнитель: <strong>{task.user.username}</strong>
                                                    </p>
                                                )}
                                                {task.group?.name && (
                                                    <p className="task-meta">
                                                        Группа: <strong>{task.group.name}</strong>
                                                    </p>
                                                )}
                                            </div>
                                            <span className={`badge ${task.is_done ? "badge-done" : "badge-active"}`}>
                                                {task.is_done ? "Выполнено" : "В работе"}
                                            </span>
                                        </div>
                                        <div className="task-actions">
                                            <button className="button secondary" onClick={() => handleToggleTask(task)}>
                                                {task.is_done ? "Отметить невыполненным" : "Отметить выполненным"}
                                            </button>
                                            <button className="button danger" onClick={() => handleDeleteTask(task)}>
                                                Удалить
                                            </button>
                                        </div>
                                    </article>
                                ))}
                            </div>
                        )}
                    </div>
                </section>
            </div>
        </div>
    );
}

export default App;
