const API_BASE = "http://localhost:8000";
const main = document.getElementById("main");
const logoutBtn = document.getElementById("logoutBtn");

const state = {
    token: localStorage.getItem("spisoc_token"),
    filterType: "",
    isDone: "",
};

logoutBtn.addEventListener("click", () => {
    localStorage.removeItem("spisoc_token");
    state.token = null;
    render();
});

function authHeader() {
    return state.token ? { Authorization: `Bearer ${state.token}` } : {};
}

function jwtPayload(token) {
    try {
        const payload = token.split(".")[1];
        const decoded = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
        return JSON.parse(decodeURIComponent(
            Array.from(decoded).map(c => `%${(`00${c.charCodeAt(0).toString(16)}`).slice(-2)}`).join("")
        ));
    } catch {
        return null;
    }
}

function getCurrentUserId() {
    const payload = jwtPayload(state.token);
    return payload?.sub ? Number(payload.sub) : null;
}

function showToast(message, isError = true) {
    const alert = document.createElement("div");
    alert.className = "alert";
    alert.textContent = message;
    main.prepend(alert);
    setTimeout(() => alert.remove(), 4500);
}

async function request(path, options = {}) {
    const headers = options.headers ? { ...options.headers } : {};
    if (state.token) {
        headers.Authorization = `Bearer ${state.token}`;
    }
    const response = await fetch(`${API_BASE}${path}`, {
        credentials: "omit",
        headers: {
            "Content-Type": "application/json",
            ...headers,
        },
        ...options,
    });
    if (!response.ok) {
        const data = await response.json().catch(() => null);
        const message = data?.detail || data?.message || `Ошибка ${response.status}`;
        throw new Error(message);
    }
    return response.status === 204 ? null : response.json();
}

function renderLogin() {
    logoutBtn.hidden = true;
    main.innerHTML = `
    <div class="container">
      <div class="card">
        <h2>Вход в Spisoc</h2>
        <form id="loginForm">
          <label>Имя пользователя</label>
          <input name="username" required minlength="3" />
          <label>Пароль</label>
          <input name="password" type="password" required minlength="3" />
          <button type="submit" class="primary">Войти</button>
        </form>
      </div>
    </div>
  `;

    const loginForm = document.getElementById("loginForm");
    loginForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const formData = new FormData(loginForm);
        const data = {
            username: formData.get("username"),
            password: formData.get("password"),
        };

        try {
            const result = await request("/auth/login", {
                method: "POST",
                body: JSON.stringify(data),
            });
            state.token = result.access_token;
            localStorage.setItem("spisoc_token", state.token);
            render();
        } catch (error) {
            showToast(error.message);
        }
    });
}

function renderTasks(tasks = []) {
    const content = document.createElement("div");
    content.className = "container";

    const filterSection = document.createElement("div");
    filterSection.className = "card";
    filterSection.innerHTML = `
    <h2>Фильтры задач</h2>
    <form id="filterForm">
      <div style="display:grid;gap:12px;">
        <label>Показывать задачи</label>
        <select name="filterType">
          <option value="">Все</option>
          <option value="today">На сегодня</option>
          <option value="overdue">Просроченные</option>
          <option value="planned">Запланированные</option>
          <option value="deadline_null">Без дедлайна</option>
        </select>
        <select name="isDone">
          <option value="">Все статусы</option>
          <option value="false">Не выполненные</option>
          <option value="true">Выполненные</option>
        </select>
        <button type="submit" class="primary">Применить</button>
      </div>
    </form>
  `;
    content.appendChild(filterSection);

    const formCard = document.createElement("div");
    formCard.className = "card";
    formCard.innerHTML = `
    <h2>Создать задачу</h2>
    <form id="createTaskForm">
      <input name="title" placeholder="Заголовок" required />
      <textarea name="description" placeholder="Описание"></textarea>
      <label>Дедлайн</label>
      <input type="datetime-local" name="deadline" />
      <button type="submit" class="primary">Создать задачу</button>
    </form>
  `;
    content.appendChild(formCard);

    const listCard = document.createElement("div");
    listCard.className = "card";
    listCard.innerHTML = `<h2>Список задач</h2>`;
    const list = document.createElement("div");

    if (tasks.length === 0) {
        list.innerHTML = `<p>Задач пока нет.</p>`;
    } else {
        tasks.forEach((task) => {
            const row = document.createElement("div");
            row.className = "task-row";
            row.innerHTML = `
        <div>
          <p class="task-title">${task.title}</p>
          <div class="task-meta">
            ${task.description ? `<div>${task.description}</div>` : ""}
            <div>Дедлайн: ${task.deadline || "—"}</div>
            <div>Автор: ${task.author?.username || "—"}</div>
            <div>Статус: <span class="badge">${task.is_done ? "Выполнено" : "В работе"}</span></div>
          </div>
        </div>
        <div class="task-actions">
          <button class="secondary" data-action="toggle" data-id="${task.id}">${task.is_done ? "Отметить как не выполнено" : "Выполнено"}</button>
          <button class="secondary" data-action="delete" data-id="${task.id}">Удалить</button>
        </div>
      `;
            list.appendChild(row);
        });
    }

    listCard.appendChild(list);
    content.appendChild(listCard);
    main.innerHTML = "";
    main.appendChild(content);

    document.getElementById("filterForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        const formData = new FormData(event.target);
        state.filterType = formData.get("filterType");
        state.isDone = formData.get("isDone");
        await loadTasks();
    });

    document.getElementById("createTaskForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        const formData = new FormData(event.target);
        const deadlineValue = formData.get("deadline");
        const payload = {
            title: formData.get("title"),
            description: formData.get("description") || null,
            is_done: false,
            user_id: getCurrentUserId(),
            group_id: null,
            deadline: deadlineValue ? `${deadlineValue}:00` : null,
        };

        try {
            await request("/tasks/", {
                method: "POST",
                body: JSON.stringify(payload),
            });
            event.target.reset();
            await loadTasks();
            showToast("Задача создана", false);
        } catch (error) {
            showToast(error.message);
        }
    });

    listCard.addEventListener("click", async (event) => {
        const button = event.target.closest("button[data-action]");
        if (!button) return;
        const taskId = button.dataset.id;
        const action = button.dataset.action;

        try {
            if (action === "toggle") {
                const task = tasks.find((item) => item.id === Number(taskId));
                if (!task) return;
                await request(`/tasks/${taskId}`, {
                    method: "PATCH",
                    body: JSON.stringify({ is_done: !task.is_done }),
                });
            }
            if (action === "delete") {
                await request(`/tasks/${taskId}`, { method: "DELETE" });
            }
            await loadTasks();
        } catch (error) {
            showToast(error.message);
        }
    });
}

async function loadTasks() {
    const params = new URLSearchParams();
    params.set("filter_user_group", "user");
    if (state.filterType) params.set("filter_type", state.filterType);
    if (state.isDone) params.set("is_done", state.isDone);

    try {
        const tasks = await request(`/tasks/filter?${params.toString()}`);
        renderTasks(tasks);
        logoutBtn.hidden = false;
    } catch (error) {
        if (error.message.includes("401") || error.message.includes("403")) {
            localStorage.removeItem("spisoc_token");
            state.token = null;
            render();
        } else {
            showToast(error.message);
        }
    }
}

function render() {
    if (!state.token) {
        renderLogin();
        return;
    }
    loadTasks();
}

render();
