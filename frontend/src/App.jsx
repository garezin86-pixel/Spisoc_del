import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, apiRequest, clearTokens, getRefreshToken, saveTokens, setTokenRefreshHandler } from "./api";
import { ChatBubble } from "./components/ChatBubble";
import { CommandPalette } from "./components/CommandPalette";
import { Icon } from "./components/Icon";
import { NotificationBell } from "./components/NotificationBell";
import { Pagination } from "./components/Pagination";
import { SidebarDeadlineWidget } from "./components/SidebarDeadlineWidget";
import { TaskCard } from "./components/TaskCard";
import { TrashCard } from "./components/TrashCard";
import { UserProfileAvatar } from "./components/UserProfileAvatar";
import { initialForm } from "./constants/forms";
import { ICONS } from "./constants/icons";
import { ROLE_COLORS, ROLE_LABELS } from "./constants/roles";
import { STATUS_LIST } from "./constants/status";
import { CalendarTab } from "./features/CalendarTab";
import { ChangePasswordCard } from "./features/ChangePasswordCard";
import { DashboardTab } from "./features/DashboardTab";
import { DeadlineCalendarTab } from "./features/DeadlineCalendarTab";
import { ForceChangePasswordScreen } from "./features/ForceChangePasswordScreen";
import { GroupsTab } from "./features/GroupsTab";
import { KanbanTab } from "./features/KanbanTab";
import { ProjectsTab } from "./features/ProjectsTab";
import { TeamTab } from "./features/TeamTab";
import { TemplatesTab } from "./features/TemplatesTab";
import { TimelineTab } from "./features/TimelineTab";
import { TokensTab } from "./features/TokensTab";
import { TwoFactorTab } from "./features/TwoFactorTab";
import { UserProfilePage } from "./features/UserProfilePage";
import { WebhooksTab } from "./features/WebhooksTab";
import { useWebSocket } from "./hooks/useWebSocket";
import { extractItems } from "./utils/extractItems";
import { decodeToken } from "./utils/token";

function App() {
    const [token, setToken] = useState(localStorage.getItem("spisoc_token"));
    const [tab, setTab] = useState("tasks"); // "tasks" | "projects" | "groups" | "trash" | "dashboard" | "templates"
    const [mfaPending, setMfaPending] = useState(null); // { mfaToken } — ждём код 2FA перед выдачей токенов
    const [show2faNudge, setShow2faNudge] = useState(false);
    const [mustChangePassword, setMustChangePassword] = useState(false);

    // api.js рефрешит access-токен "тихо" внутри apiRequest при 401 и кладёт
    // его в localStorage, но состояние React об этом не знает само по себе —
    // подписываемся, чтобы все компоненты/эффекты сразу получали новый токен
    // и не продолжали слать запросы со старым (что приводило к повторным 401
    // и refresh_token_reuse на бэкенде).
    useEffect(() => {
        setTokenRefreshHandler((newToken) => setToken(newToken));
        return () => setTokenRefreshHandler(null);
    }, []);

    // ── WebSocket realtime ────────────────────────────────────────────────────
    const [chatWsEvent, setChatWsEvent] = useState(null);

    // handleWsEvent должен иметь СТАБИЛЬНУЮ ссылку (useCallback с пустыми deps) —
    // иначе useWebSocket(token, handleWsEvent) пересоздаёт соединение на каждое
    // изменение `tab`/`tasksPage`/`viewMode` (они были в deps раньше), а это
    // рвёт WS ровно в момент переключения вкладок и роняет "живые" события —
    // отсюда и жалоба "сообщения приходят с опозданием, иногда нужно
    // перезагружать страницу". Вместо deps читаем актуальные значения из рефов.
    const tabRef = useRef(tab);
    tabRef.current = tab;
    // Синхронизируются чуть ниже, сразу после объявления соответствующих
    // useState (tasksPage/viewMode объявлены позже в этом компоненте) —
    // до тех пор просто держат дефолт, handleWsEvent их читает лениво,
    // только когда реально прилетает WS-событие.
    const tasksPageRef = useRef(1);

    const handleWsEvent = useCallback((event, data) => {
        const currentTab = tabRef.current;
        if (event === "task_created" || event === "task_updated" || event === "kanban_moved" || event === "task_deleted") {
            if (currentTab === "tasks") loadTasks(tasksPageRef.current, viewModeRef.current);
            // Канбан обновляет список сам при монтировании/действиях пользователя —
            // отдельного live-refresh для него пока нет (не относится к этой правке).
        } else if (event === "task_restored") {
            if (currentTab === "trash") loadTrash();
        } else if (event === "comment_added") {
            // Комментарии обновятся при следующем открытии задачи
        } else if (event === "chat_message" || event === "chat_message_deleted") {
            setChatWsEvent({ event, data, ts: Date.now() });
        }
    }, []);  // eslint-disable-line

    useWebSocket(token, handleWsEvent);
    const [theme, setTheme] = useState(() => localStorage.getItem("spisoc_theme") || "dark");

    const [paletteOpen, setPaletteOpen] = useState(false);
    const [profileUserId, setProfileUserId] = useState(null);
    // window.openUserProfile — чтобы открывать профиль клика по имени из глубоко
    // вложенных компонентов (TaskCard, комментарии, участники проекта) без
    // протаскивания callback через десяток слоёв пропсов.
    useEffect(() => {
        window.openUserProfile = (id) => setProfileUserId(id);
        return () => { delete window.openUserProfile; };
    }, []);
    useEffect(() => {
        function onKeyDown(e) {
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
                e.preventDefault();
                setPaletteOpen(open => !open);
            }
        }
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, []);
    const [tasks, setTasks] = useState([]);
    const [trashTasks, setTrash] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [filterPriority, setFilterPriority] = useState(null);
    const [appProjects, setAppProjects] = useState([]);
    const [dashStats, setDashStats] = useState(null);
    const [dashLoading, setDashLoading] = useState(false);

    const [filterType, setFilterType] = useState("");
    const [statusFilter, setStatusFilter] = useState("");
    const [searchQuery, setSearchQuery] = useState("");
    const [viewMode, setViewMode] = useState("user"); // "user" | "author"

    const [tasksPage, setTasksPage] = useState(1);
    tasksPageRef.current = tasksPage;
    const [tasksTotal, setTasksTotal] = useState(null); // null = ещё не загружено (см. count-badge ниже — резервируем место, чтобы бейдж не "впрыгивал" и не сдвигал вкладки)
    const PAGE_SIZE = 50;

    const [trashPage, setTrashPage] = useState(1);
    const [trashTotal, setTrashTotal] = useState(null); // null = ещё не загружено

    const [groups, setGroups] = useState([]);
    const [users, setUsers] = useState([]);
    const [allTags, setAllTags] = useState([]);
    const [tagFilter, setTagFilter] = useState("");

    const [filterPresets, setFilterPresets] = useState([]);
    const [presetNameInput, setPresetNameInput] = useState("");
    const [savingPreset, setSavingPreset] = useState(false);

    const [form, setForm] = useState(initialForm);
    const [assignType, setAssignType] = useState("self");
    const [selectedGroupId, setSelectedGroupId] = useState("");
    const [selectedUserId, setSelectedUserId] = useState("");

    const tokenPayload = useMemo(() => decodeToken(token), [token]);
    const currentUserId = useMemo(() => tokenPayload?.sub ? Number(tokenPayload.sub) : null, [tokenPayload]);
    const currentUsername = useMemo(() => tokenPayload?.username || tokenPayload?.sub || "Пользователь", [tokenPayload]);
    const currentRole = useMemo(() => tokenPayload?.role ?? "user", [tokenPayload]);
    const canManage = currentRole === "admin" || currentRole === "manager";

    // Поиск теперь серверный (см. searchDebounceRef useEffect выше) — полнотекстовый
    // по title+description на всех страницах, а не только по уже загруженной.
    // Раньше здесь была клиентская фильтрация по подстроке в title/id —
    // это скрывало бы результаты, найденные сервером по description.
    const visibleTasks = tasks;

    const [selectedTaskIds, setSelectedTaskIds] = useState(new Set());
    const [bulkStatus, setBulkStatus] = useState("");
    const [bulkPriority, setBulkPriority] = useState("");
    const [bulkTagId, setBulkTagId] = useState("");
    const [bulkUserId, setBulkUserId] = useState("");
    const [bulkApplying, setBulkApplying] = useState(false);

    function toggleTaskSelection(taskId) {
        setSelectedTaskIds(prev => {
            const next = new Set(prev);
            if (next.has(taskId)) next.delete(taskId); else next.add(taskId);
            return next;
        });
    }

    function toggleSelectAllVisible() {
        setSelectedTaskIds(prev => {
            const allSelected = visibleTasks.every(t => prev.has(t.id));
            if (allSelected) return new Set(); // все выбраны — снимаем всё
            return new Set(visibleTasks.map(t => t.id)); // иначе выбираем все видимые
        });
    }

    async function handleBulkApply() {
        if (!bulkStatus && !bulkPriority && !bulkTagId && !bulkUserId) {
            setError("Выберите хотя бы одно поле для изменения");
            return;
        }

        const body = { task_ids: Array.from(selectedTaskIds) };
        if (bulkStatus) body.status = bulkStatus;
        if (bulkPriority) body.priority = bulkPriority;
        if (bulkTagId) body.tag_id = Number(bulkTagId);
        if (bulkUserId) body.user_id = Number(bulkUserId);

        setBulkApplying(true);
        try {
            const response = await fetch(`${API_BASE}/tasks/bulk`, {
                method: "PATCH",
                headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            if (!response.ok) {
                const text = await response.text();
                throw new Error(text || `Ошибка ${response.status}`);
            }
            const result = await response.json();
            if (result.skipped.length > 0) {
                setError(`Обновлено: ${result.updated}. Пропущено (нет доступа или удалены): ${result.skipped.join(", ")}`);
            }
            setSelectedTaskIds(new Set());
            setBulkStatus(""); setBulkPriority(""); setBulkTagId(""); setBulkUserId("");
            await loadTasks(tasksPage, viewMode);
        } catch (err) {
            setError(err.message);
        } finally {
            setBulkApplying(false);
        }
    }

    const [showTooltip, setShowTooltip] = useState(false);
    const chipRef = React.useRef(null);
    const [tooltipPos, setTooltipPos] = useState({ top: 0, right: 0 });
    const loadAppProjects = React.useCallback(async () => {
        if (!token) return;
        try {
            const data = await apiRequest({ path: "/projects?page=1&size=100", token });
            setAppProjects(extractItems(data));
        } catch { setAppProjects([]); }
    }, [token]);

    // Загружаем проекты при входе
    useEffect(() => { if (token) loadAppProjects(); }, [token, loadAppProjects]);

    // Применяем тему к документу
    useEffect(() => {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("spisoc_theme", theme);
    }, [theme]);

    // ── loaders ──────────────────────────────────────────
    // Refs позволяют функциям читать актуальные значения без пересоздания,
    // что исключает цепочку useCallback→useEffect→двойной setState
    const tokenRef = React.useRef(token);
    const filterTypeRef = React.useRef(filterType);
    const statusFilterRef = React.useRef(statusFilter);
    const viewModeRef = React.useRef(viewMode);
    tokenRef.current = token;
    filterTypeRef.current = filterType;
    statusFilterRef.current = statusFilter;
    viewModeRef.current = viewMode;

    const filterPriorityRef = React.useRef(filterPriority);
    filterPriorityRef.current = filterPriority;
    const searchQueryRef = React.useRef(searchQuery);
    searchQueryRef.current = searchQuery;
    const tagFilterRef = React.useRef(tagFilter);
    tagFilterRef.current = tagFilter;
    // AbortController отменяет предыдущий запрос при новом вызове
    const tasksAbortRef = React.useRef(null);
    const trashAbortRef = React.useRef(null);

    const loadTasks = useCallback(async (page = 1, filterUserGroup) => {
        // Отменяем предыдущий запрос если он ещё выполняется
        if (tasksAbortRef.current) tasksAbortRef.current.abort();
        const controller = new AbortController();
        tasksAbortRef.current = controller;

        const mode = filterUserGroup ?? viewModeRef.current;
        setLoading(true);
        try {
            const q = new URLSearchParams();
            q.set("filter_user_group", mode);
            q.set("page", page);
            q.set("size", PAGE_SIZE);
            if (filterTypeRef.current) q.set("filter_type", filterTypeRef.current);
            if (filterPriorityRef.current) q.set("priority", filterPriorityRef.current);
            if (statusFilterRef.current) q.set("status", statusFilterRef.current);
            if (searchQueryRef.current.trim()) q.set("search", searchQueryRef.current.trim());
            if (tagFilterRef.current) q.set("tag_id", tagFilterRef.current);
            const data = await apiRequest({ path: `/tasks/filter?${q}`, token: tokenRef.current });
            // Если запрос был отменён — игнорируем результат
            if (controller.signal.aborted) return;
            setTasks(extractItems(data));
            setTasksTotal(data?.total ?? 0);
            setTasksPage(page);
        } catch (err) {
            if (!controller.signal.aborted) handleAuthError(err);
        }
        finally {
            if (!controller.signal.aborted) setLoading(false);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const loadFilterPresets = useCallback(async () => {
        try {
            const data = await apiRequest({ path: "/tasks/presets", token: tokenRef.current });
            setFilterPresets(Array.isArray(data) ? data : []);
        } catch (err) {
            handleAuthError(err);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    async function handleSavePreset() {
        const name = presetNameInput.trim();
        if (!name) {
            setError("Введите название пресета");
            return;
        }
        setSavingPreset(true);
        try {
            await apiRequest({
                path: "/tasks/presets",
                method: "POST",
                token,
                body: {
                    name,
                    status: statusFilter || null,
                    priority: filterPriority || null,
                    tag_id: tagFilter ? Number(tagFilter) : null,
                    filter_user_group: viewMode || null,
                    filter_type: filterType || null,
                },
            });
            setPresetNameInput("");
            await loadFilterPresets();
        } catch (err) {
            setError(err.message);
        } finally {
            setSavingPreset(false);
        }
    }

    function handleApplyPreset(preset) {
        // Выставляем все стейты фильтров разом и перезагружаем список.
        setStatusFilter(preset.status || "");
        setFilterPriority(preset.priority || null);
        setTagFilter(preset.tag_id ? String(preset.tag_id) : "");
        setFilterType(preset.filter_type || "");
        if (preset.filter_user_group) setViewMode(preset.filter_user_group);
        // Рефы (statusFilterRef и т.д.) обновятся синхронно с ре-рендером на
        // следующий тик, поэтому передаём filter_user_group явным аргументом,
        // а не полагаемся на viewModeRef, который ещё не успеет обновиться.
        loadTasks(1, preset.filter_user_group || undefined);
    }

    async function handleDeletePreset(presetId) {
        try {
            await apiRequest({ path: `/tasks/presets/${presetId}`, method: "DELETE", token });
            setFilterPresets(prev => prev.filter(p => p.id !== presetId));
        } catch (err) {
            setError(err.message);
        }
    }

    const loadTrash = useCallback(async (page = 1) => {
        if (trashAbortRef.current) trashAbortRef.current.abort();
        const controller = new AbortController();
        trashAbortRef.current = controller;

        setLoading(true);
        try {
            const q = new URLSearchParams();
            q.set("page", page); q.set("size", PAGE_SIZE);
            const data = await apiRequest({ path: `/tasks/trash?${q}`, token: tokenRef.current });
            if (controller.signal.aborted) return;
            setTrash(extractItems(data));
            setTrashTotal(data?.total ?? 0);
            setTrashPage(page);
        } catch (err) {
            if (!controller.signal.aborted) handleAuthError(err);
        }
        finally {
            if (!controller.signal.aborted) setLoading(false);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const loadGroups = useCallback(async () => {
        try {
            const data = await apiRequest({ path: "/groups?page=1&size=100", token: tokenRef.current });
            setGroups(extractItems(data));
        } catch { setGroups([]); }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);


    const loadDashboard = useCallback(async () => {
        if (!tokenRef.current) return;
        setDashLoading(true);
        try {
            const [meData, statsData] = await Promise.all([
                apiRequest({ path: "/users/me", token: tokenRef.current }),
                apiRequest({ path: `/users/${currentUserId}/stats`, token: tokenRef.current }),
            ]);
            setDashStats({ ...statsData, username: meData?.username });
        } catch { setDashStats(null); }
        finally { setDashLoading(false); }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [currentUserId]);

    const loadUsers = useCallback(async () => {
        try {
            const data = await apiRequest({ path: "/users?page=1&size=100", token: tokenRef.current });
            setUsers(extractItems(data));
        } catch { setUsers([]); }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const loadTags = useCallback(async () => {
        try {
            const data = await apiRequest({ path: "/tags", token: tokenRef.current });
            // /tags отдаёт плоский массив (не пагинированный список), extractItems тут не нужен
            setAllTags(Array.isArray(data) ? data : []);
        } catch { setAllTags([]); }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Один эффект — все загрузки. Используем ref чтобы отделить
    // первый запуск (логин) от последующих (смена фильтров/вкладки).
    // isFirstRender объявлен ВНЕ useEffect и НЕ пересоздаётся при ре-рендере.
    const didInitRef = React.useRef(false);
    const prevTokenRef = React.useRef(null);

    useEffect(() => {
        if (!token) {
            // Логаут — сбрасываем флаг чтобы при следующем логине загрузить заново
            didInitRef.current = false;
            prevTokenRef.current = null;
            return;
        }

        const isNewLogin = token !== prevTokenRef.current;
        prevTokenRef.current = token;

        if (isNewLogin) {
            // Первый вход или смена токена — грузим всё.
            // loadTrash(1) грузим сразу, а не только при открытии вкладки "Корзина" —
            // иначе счётчик-бейдж появляется с опозданием и весь ряд вкладок
            // сдвигается по ширине (см. баг-репорт про "прыгающие" отступы).
            didInitRef.current = true;
            loadGroups();
            loadUsers();
            loadTags();
            loadFilterPresets();
            if (tab === "tasks") loadTasks(1);
            loadTrash(1);
            if (tab === "dashboard") loadDashboard();
        } else {
            // Смена фильтров/вкладки — только задачи
            if (tab === "tasks") loadTasks(1);
            if (tab === "trash") loadTrash(1);
            if (tab === "dashboard") loadDashboard();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token, tab, filterType, statusFilter, viewMode, filterPriority, tagFilter]);

    // Полнотекстовый поиск — дебаунс 400мс, серверный (title+description),
    // а не клиентская фильтрация по уже загруженной странице (та не видела бы
    // совпадения в description и не искала бы по остальным страницам).
    const searchDebounceRef = React.useRef(null);
    useEffect(() => {
        if (!didInitRef.current) return;
        if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
        searchDebounceRef.current = setTimeout(() => {
            if (tab === "tasks") loadTasks(1);
        }, 400);
        return () => clearTimeout(searchDebounceRef.current);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [searchQuery]);

    // ── auth ─────────────────────────────────────────────
    function handleAuthError(err) {
        if (["401", "403", "invalid"].some(s => err.message?.includes(s))) logout();
        else setError(err.message);
    }

    async function logout() {
        try {
            const refreshToken = getRefreshToken();
            if (refreshToken) {
                await apiRequest({
                    path: "/auth/logout", method: "POST",
                    token, body: { refresh_token: refreshToken },
                });
            }
        } catch { /* игнорируем ошибки при logout */ }
        clearTokens();
        setToken(null); setTasks([]);
    }

    async function handleLogin(e) {
        e.preventDefault();
        const fd = new FormData(e.target);
        try {
            setError(null);
            const resp = await apiRequest({
                path: "/auth/login", method: "POST",
                body: { username: fd.get("username"), password: fd.get("password") },
            });
            if (resp.mfa_required) {
                setMfaPending({ mfaToken: resp.mfa_token });
                return;
            }
            saveTokens(resp.access_token, resp.refresh_token);
            setToken(resp.access_token);
            setShow2faNudge(!!resp.requires_2fa_setup);
            setMustChangePassword(!!resp.must_change_password);
        } catch (err) { setError(err.message); }
    }

    async function handleLogin2fa(e) {
        e.preventDefault();
        const fd = new FormData(e.target);
        try {
            setError(null);
            const resp = await apiRequest({
                path: "/auth/login/2fa", method: "POST",
                body: { mfa_token: mfaPending.mfaToken, code: fd.get("code").trim() },
            });
            saveTokens(resp.access_token, resp.refresh_token);
            setToken(resp.access_token);
            setMfaPending(null);
            setMustChangePassword(!!resp.must_change_password);
        } catch (err) { setError(err.message); }
    }

    // ── task actions ─────────────────────────────────────
    async function handleCreateTask(e) {
        e.preventDefault();
        if (!form.title.trim()) { setError("Введите заголовок задачи"); return; }
        try {
            setError(null);
            const payload = {
                title: form.title.trim(),
                description: form.description.trim() || null,
                status: form.status || "todo",
                priority: form.priority || "medium",
                project_id: form.project_id ? Number(form.project_id) : null,
                deadline: form.deadline ? `${form.deadline}:00` : null,
                recurrence_rule: form.recurrence_rule || "none",
            };
            if (assignType === "self") { payload.user_id = currentUserId; payload.group_id = null; }
            else if (assignType === "user") { payload.user_id = selectedUserId ? Number(selectedUserId) : null; payload.group_id = null; }
            else if (assignType === "group") { payload.group_id = selectedGroupId ? Number(selectedGroupId) : null; payload.user_id = null; }
            else { payload.user_id = null; payload.group_id = null; }

            await apiRequest({ path: "/tasks", method: "POST", token, body: payload });
            setForm(initialForm); setAssignType("self");
            setSelectedGroupId(""); setSelectedUserId("");
            await loadTasks(1);
        } catch (err) { handleAuthError(err); }
    }

    async function handleToggleTask(task, newStatus) {
        if (!newStatus) return;
        const nextIsDone = newStatus === "done";
        setTasks(prev => prev.map(t =>
            t.id === task.id ? { ...t, status: newStatus, is_done: nextIsDone } : t
        ));
        try {
            await apiRequest({
                path: `/tasks/${task.id}/status`,
                method: "PATCH",
                token,
                body: { status: newStatus },
            });
        } catch (err) {
            setTasks(prev => prev.map(t => t.id === task.id ? task : t));
            handleAuthError(err);
        }
    }

    async function handleUpdateTask(task, updates) {
        setTasks(prev => prev.map(t => t.id === task.id ? { ...t, ...updates } : t));
        try {
            await apiRequest({ path: `/tasks/${task.id}`, method: "PATCH", token, body: updates });
        } catch (err) {
            setTasks(prev => prev.map(t => t.id === task.id ? task : t));
            handleAuthError(err);
        }
    }

    async function handleDeleteTask(task) {
        setTasks(prev => prev.filter(t => t.id !== task.id));
        setTasksTotal(prev => (prev ?? 0) - 1);
        try {
            await apiRequest({ path: `/tasks/${task.id}`, method: "DELETE", token });
        } catch (err) {
            setTasks(prev => [...prev, task].sort((a, b) => a.id - b.id));
            setTasksTotal(prev => (prev ?? 0) + 1);
            handleAuthError(err);
        }
    }

    async function handleReassignTask(taskId, userId, groupId) {
        const userObj = userId ? users.find(u => u.id === Number(userId)) : null;
        const groupObj = groupId ? groups.find(g => g.id === Number(groupId)) : null;
        setTasks(prev => prev.map(t => t.id === taskId ? {
            ...t,
            ...(userObj ? { user: { id: userObj.id, username: userObj.username } } : {}),
            ...(groupObj ? { group: { id: groupObj.id, name: groupObj.name } } : {}),
        } : t));
        try {
            const q = new URLSearchParams();
            if (userId) q.set("user_id", userId);
            if (groupId) q.set("group_id", groupId);
            await apiRequest({ path: `/tasks/${taskId}/reassign?${q}`, method: "PATCH", token });
        } catch (err) {
            await loadTasks(tasksPage);
            handleAuthError(err);
        }
    }

    // TagsPanel сам делает PUT /tags/tasks/{id} — этот колбэк только
    // синхронизирует локальный кэш tasks[], чтобы чипы тегов в мета-строке
    // карточки обновились сразу, без повторной загрузки всей страницы.
    function handleTaskTagsUpdated(taskId, updatedTags) {
        setTasks(prev => prev.map(t => t.id === taskId ? { ...t, tags: updatedTags } : t));
    }

    const [exporting, setExporting] = useState(false);
    async function handleExportCsv() {
        // Экспорт отдаёт CSV-файл, а не JSON — apiRequest() из ./api не подходит
        // (он всегда пытается JSON.parse ответ), поэтому здесь прямой fetch с
        // ручной обработкой Blob и скачиванием через временную ссылку <a>.
        setExporting(true);
        try {
            const q = new URLSearchParams();
            if (statusFilter) q.set("status", statusFilter);
            if (filterPriority) q.set("priority", filterPriority);
            if (tagFilter) q.set("tag_id", tagFilter);

            const response = await fetch(`${API_BASE}/tasks/export?${q}`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (!response.ok) {
                const text = await response.text();
                throw new Error(text || `Ошибка ${response.status}`);
            }
            const blob = await response.blob();
            const disposition = response.headers.get("Content-Disposition") || "";
            const match = disposition.match(/filename="?([^"]+)"?/);
            const filename = match ? match[1] : "tasks_export.csv";

            const url = window.URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);
        } catch (err) {
            setError(err.message);
        } finally {
            setExporting(false);
        }
    }

    const [importing, setImporting] = useState(false);
    const [importSummary, setImportSummary] = useState(null); // { created, errors, warnings } | null
    const importInputRef = useRef(null);

    async function handleImportFile(e) {
        const file = e.target.files?.[0];
        e.target.value = ""; // сбрасываем, чтобы можно было выбрать тот же файл повторно
        if (!file) return;

        setImporting(true);
        setImportSummary(null);
        try {
            const formData = new FormData();
            formData.append("file", file);

            const q = new URLSearchParams();
            if (projectId) q.set("project_id", projectId); // если на странице выбран проект — импортируем в него

            const response = await fetch(`${API_BASE}/tasks/import?${q}`, {
                method: "POST",
                headers: { Authorization: `Bearer ${token}` }, // Content-Type НЕ ставим — fetch сам
                body: formData,                                // проставит multipart boundary
            });
            if (!response.ok) {
                const text = await response.text();
                throw new Error(text || `Ошибка ${response.status}`);
            }
            const summary = await response.json();
            setImportSummary(summary);
            await loadTasks(1); // перезагружаем список — импортированные задачи должны появиться
        } catch (err) {
            setError(err.message);
        } finally {
            setImporting(false);
        }
    }

    async function handleRestoreTask(task) {
        setTrash(prev => prev.filter(t => t.id !== task.id));
        setTrashTotal(prev => (prev ?? 0) - 1);
        try {
            await apiRequest({ path: `/tasks/${task.id}/restore`, method: "PATCH", token });
        } catch (err) {
            setTrash(prev => [...prev, task].sort((a, b) => a.id - b.id));
            setTrashTotal(prev => (prev ?? 0) + 1);
            handleAuthError(err);
        }
    }

    async function handleHardDelete(task) {
        if (!window.confirm("Удалить задачу навсегда? Это действие нельзя отменить.")) return;
        setTrash(prev => prev.filter(t => t.id !== task.id));
        setTrashTotal(prev => (prev ?? 0) - 1);
        try {
            await apiRequest({ path: `/tasks/${task.id}/hard`, method: "DELETE", token });
        } catch (err) {
            setTrash(prev => [...prev, task].sort((a, b) => a.id - b.id));
            setTrashTotal(prev => (prev ?? 0) + 1);
            handleAuthError(err);
        }
    }

    const stats = useMemo(() => {
        const total = tasks.length;
        const done = tasks.filter(t => t.is_done).length;
        return { total, done, pending: total - done, percent: total > 0 ? Math.round((done / total) * 100) : 0 };
    }, [tasks]);

    const tasksTotalPages = Math.ceil((tasksTotal ?? 0) / PAGE_SIZE);
    const trashTotalPages = Math.ceil((trashTotal ?? 0) / PAGE_SIZE);

    // ── Role badge in header ──────────────────────────────
    const roleColor = ROLE_COLORS[currentRole] ?? ROLE_COLORS.user;

    // ── Login screen ─────────────────────────────────────
    if (!token) {
        return (
            <div className="login-page">
                <div className="auth-card">
                    <div className="login-logo">
                        <div className="logo-mark">{import.meta.env.VITE_APP_LOGO}</div>
                        <div>
                            <div className="brand-name">{import.meta.env.VITE_APP_NAME}</div>
                            <div className="brand-tagline">{import.meta.env.VITE_APP_DESCRIPTION}</div>
                        </div>
                    </div>
                    <div className="auth-title">Добро пожаловать</div>
                    <div className="auth-sub">Войдите, чтобы управлять задачами</div>
                    {mfaPending ? (
                        <form className="form" onSubmit={handleLogin2fa}>
                            <div className="form-group">
                                <label className="form-label">Код из приложения-аутентификатора</label>
                                <input
                                    name="code" placeholder="123456" required minLength={6} maxLength={11}
                                    inputMode="numeric" autoFocus
                                />
                                <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
                                    Нет доступа к приложению? Введите один из recovery-кодов вместо этого.
                                </div>
                            </div>
                            <button type="submit" className="btn btn-primary" style={{ marginTop: 4 }}>
                                Подтвердить
                            </button>
                            <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setMfaPending(null); setError(null); }}>
                                ← Назад
                            </button>
                            {error && <div className="alert">{error}</div>}
                        </form>
                    ) : (
                        <form className="form" onSubmit={handleLogin}>
                            <div className="form-group">
                                <label className="form-label">Имя пользователя</label>
                                <input name="username" placeholder="admin" required minLength={3} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Пароль</label>
                                <input name="password" type="password" placeholder="••••••••" required minLength={3} />
                            </div>
                            <button type="submit" className="btn btn-primary" style={{ marginTop: 4 }}>
                                Войти
                            </button>
                            {error && <div className="alert">{error}</div>}
                        </form>
                    )}
                </div>
            </div>
        );
    }

    if (mustChangePassword) {
        return <ForceChangePasswordScreen token={token} onDone={() => setMustChangePassword(false)} onLogout={() => { clearTokens(); setToken(null); }} />;
    }

    // ── Main screen ──────────────────────────────────────
    return (
        <div className="page-shell">
            <header className="app-header">
                <div className="app-header-left">
                    <div className="logo-mark">{import.meta.env.VITE_APP_LOGO}</div>
                    <div>
                        <div className="brand-name">{import.meta.env.VITE_APP_NAME}</div>
                        <div className="brand-tagline">{import.meta.env.VITE_APP_DESCRIPTION}</div>
                    </div>
                </div>
                <div className="header-right">
                    {/* Верхний ряд — пользователь и управление */}
                    <div className="header-row header-row-top">
                        <button className="cmdk-trigger" onClick={() => setPaletteOpen(true)} title="Command Palette">
                            🔍 <span>Поиск</span> <kbd>Ctrl K</kbd>
                        </button>
                        <div className="user-chip"
                            ref={chipRef}
                            onClick={() => currentUserId != null && setProfileUserId(currentUserId)}
                            style={{ cursor: currentUserId != null ? "pointer" : "default" }}
                            onMouseEnter={() => {
                                const rect = chipRef.current?.getBoundingClientRect();
                                if (rect) setTooltipPos({
                                    top: rect.bottom + 8,
                                    right: window.innerWidth - rect.right,
                                });
                                setShowTooltip(true);
                            }}
                            onMouseLeave={() => setShowTooltip(false)}>
                            {currentUserId != null && <UserProfileAvatar userId={currentUserId} username={currentUsername} size={22} />}
                            <span className="user-chip-name">{currentUsername}</span>
                            <span className="role-badge" style={{ color: roleColor.color, background: roleColor.bg, marginLeft: 4 }}>
                                {ROLE_LABELS[currentRole] ?? currentRole}
                            </span>
                            {showTooltip && (
                                <span style={{
                                    position: "fixed",
                                    top: tooltipPos.top,
                                    right: tooltipPos.right,
                                    background: "var(--surface2)",
                                    border: "1px solid var(--border)",
                                    color: "var(--text)",
                                    fontSize: 12,
                                    padding: "5px 10px",
                                    borderRadius: 25,
                                    whiteSpace: "nowrap",
                                    zIndex: 1000,
                                }}>
                                    {currentUsername}
                                </span>
                            )}
                        </div>
                        <NotificationBell
                            token={token}
                            onOpenTask={(title) => { setTab("tasks"); setSearchQuery(title); }}
                        />
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => setTheme(t => t === "dark" ? "light" : "dark")}
                            title="Переключить тему"
                            style={{ fontSize: "0.85rem" }}
                        >
                            {theme === "dark" ? "☀️" : "🌙"}
                        </button>
                        {currentRole === "admin" && (
                            <a
                                href={import.meta.env.DEV ? "http://127.0.0.1:8000/admin/" : "https://spisoc-del.onrender.com/admin/"}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="btn btn-ghost btn-sm"
                            >
                                <Icon d={ICONS.shield} /> Админка
                            </a>
                        )}
                        <button className="btn btn-ghost btn-sm" onClick={logout}>
                            <Icon d={ICONS.logout} /> Выйти
                        </button>
                    </div>
                    {/* Нижний ряд — навигация */}
                    <div className="header-row header-row-bottom">
                        <div className="tab-bar">
                            <button className={`tab-btn${tab === "dashboard" ? " active" : ""}`} onClick={() => { setTab("dashboard"); loadDashboard(); }}>
                                <Icon d={ICONS.chart} /> Дашборд
                            </button>
                            <button className={`tab-btn${tab === "timeline" ? " active" : ""}`} onClick={() => setTab("timeline")}>
                                <Icon d={ICONS.clock} /> Лента
                            </button>
                            <button className={`tab-btn${tab === "tasks" ? " active" : ""}`} onClick={() => setTab("tasks")}>
                                Задачи <span className="count-badge" style={{ visibility: tasksTotal ? "visible" : "hidden" }}>{tasksTotal || 0}</span>
                            </button>
                            <button className={`tab-btn${tab === "projects" ? " active" : ""}`} onClick={() => setTab("projects")}>
                                <Icon d={ICONS.folder} /> Проекты
                            </button>
                            <button className={`tab-btn${tab === "templates" ? " active" : ""}`} onClick={() => setTab("templates")}>
                                <Icon d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zm-1 1.5L18.5 9H13V3.5zM6 20V4h5v7h7v9H6z" /> Шаблоны
                            </button>
                            <button className={`tab-btn${tab === "trash" ? " active" : ""}`} onClick={() => setTab("trash")}>
                                <Icon d={ICONS.trash} /> Корзина
                                <span className="count-badge" style={{ visibility: trashTotal ? "visible" : "hidden" }}>{trashTotal || 0}</span>
                            </button>
                            <button className={`tab-btn${tab === "kanban" ? " active" : ""}`} onClick={() => setTab("kanban")}>
                                <Icon d={ICONS.kanban ?? "M3 3h7v7H3zm0 11h7v7H3zm11-11h7v7h-7zm0 11h7v7h-7z"} /> Канбан
                            </button>
                            <button className={`tab-btn${tab === "calendar" ? " active" : ""}`} onClick={() => setTab("calendar")}>
                                <Icon d={ICONS.calendar} /> Календарь
                            </button>
                            <button className={`tab-btn${tab === "groups" ? " active" : ""}`} onClick={() => setTab("groups")}>
                                <Icon d={ICONS.group} /> Группы
                            </button>
                            <button className={`tab-btn${tab === "team" ? " active" : ""}`} onClick={() => setTab("team")}>
                                <Icon d={ICONS.user} /> Команда
                            </button>
                            <button className={`tab-btn${tab === "tokens" || tab === "webhooks" || tab === "ical" || tab === "2fa" ? " active" : ""}`} onClick={() => setTab("2fa")}>
                                <Icon d={ICONS.shield} /> Настройки
                            </button>
                        </div>
                    </div>
                </div>
            </header>

            <CommandPalette
                open={paletteOpen}
                onClose={() => setPaletteOpen(false)}
                token={token}
                setTab={setTab}
                setSearchQuery={setSearchQuery}
                setTheme={setTheme}
                onLogout={logout}
            />

            <ChatBubble token={token} currentUserId={currentUserId} wsEvent={chatWsEvent} />

            {show2faNudge && (
                <div className="alert" style={{
                    margin: "12px 16px 0", display: "flex", justifyContent: "space-between",
                    alignItems: "center", gap: 12, borderColor: "#f59e0b", background: "#f59e0b11",
                }}>
                    <span>
                        🔒 У вашей роли расширенные права — рекомендуем включить двухфакторную аутентификацию.
                    </span>
                    <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                        <button className="btn btn-sm btn-primary" onClick={() => { setTab("2fa"); setShow2faNudge(false); }}>
                            Настроить
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={() => setShow2faNudge(false)}>✕</button>
                    </div>
                </div>
            )}

            {/* ── TASKS TAB ── */}
            {tab === "tasks" && (
                <div>
                    <div className="content-grid">
                        <aside className="sidebar-col">
                            <div className="card">
                                <div className="section-header">
                                    <div>
                                        <div className="section-title">Статистика</div>
                                        <div className="section-sub">Текущая страница</div>
                                    </div>
                                </div>
                                <div className="stats-grid">
                                    <div className="stat-box">
                                        <div className="stat-value">{tasksTotal ?? "–"}</div>
                                        <div className="stat-label">Всего</div>
                                    </div>
                                    <div className="stat-box">
                                        <div className="stat-value" style={{ color: "var(--green)" }}>{stats.done}</div>
                                        <div className="stat-label">Готово</div>
                                    </div>
                                    <div className="stat-box">
                                        <div className="stat-value" style={{ color: "var(--accent-light)" }}>{stats.pending}</div>
                                        <div className="stat-label">В работе</div>
                                    </div>
                                </div>
                                <div className="progress-wrap">
                                    <div className="progress-track">
                                        <div className="progress-fill" style={{ width: `${stats.percent}%` }} />
                                    </div>
                                    <div className="progress-caption">{stats.percent}% выполнено</div>
                                </div>
                            </div>

                            <div className="card">
                                <div className="section-header">
                                    <div className="section-title"><Icon d={ICONS.filter} size={13} /> Фильтры</div>
                                </div>
                                <div className="view-mode-row">
                                    <button
                                        className={`btn btn-sm ${viewMode === "user" ? "btn-primary" : "btn-ghost"}`}
                                        onClick={() => setViewMode("user")}>
                                        Мои задачи
                                    </button>
                                    <button
                                        className={`btn btn-sm ${viewMode === "author" ? "btn-primary" : "btn-ghost"}`}
                                        onClick={() => setViewMode("author")}>
                                        Я автор
                                    </button>
                                </div>
                                <div className="divider" />
                                <div className="filter-row">
                                    <div className="form-group">
                                        <label className="form-label">Приоритет</label>
                                        <select value={filterPriority || ""} onChange={e => setFilterPriority(e.target.value || null)}>
                                            <option value="">Все</option>
                                            <option value="critical">🔴 Критический</option>
                                            <option value="high">🟠 Высокий</option>
                                            <option value="medium">🔵 Средний</option>
                                            <option value="low">⚪ Низкий</option>
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">Тип задачи</label>
                                        <select value={filterType} onChange={e => setFilterType(e.target.value)}>
                                            <option value="">Все</option>
                                            <option value="today">На сегодня</option>
                                            <option value="overdue">Просроченные</option>
                                            <option value="planned">Запланированные</option>
                                            <option value="deadline_null">Без дедлайна</option>
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">Статус</label>
                                        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                                            <option value="">Все</option>
                                            <option value="backlog">Очередь</option>
                                            <option value="todo">Новые</option>
                                            <option value="in_progress">В работе</option>
                                            <option value="review">На проверке</option>
                                            <option value="done">Готово</option>
                                        </select>
                                    </div>
                                </div>
                            </div>

                            <SidebarDeadlineWidget
                                token={token}
                                onOpenTask={(title) => { setSearchQuery(title); }}
                                onOpenFullCalendar={() => setTab("calendar")}
                            />
                        </aside>

                        <main className="main-column">
                            <div className="card">
                                <div className="section-header">
                                    <div>
                                        <div className="section-title">Новая задача</div>
                                        <div className="section-sub">Создайте задачу и назначьте исполнителя</div>
                                    </div>
                                </div>
                                <form className="form" onSubmit={handleCreateTask}>
                                    <div className="form-group">
                                        <label className="form-label">Заголовок *</label>
                                        <input value={form.title}
                                            onChange={e => setForm({ ...form, title: e.target.value })}
                                            placeholder="Например, проверить почту" required />
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">Описание</label>
                                        <textarea value={form.description}
                                            onChange={e => setForm({ ...form, description: e.target.value })}
                                            placeholder="Дополнительные детали (необязательно)" />
                                    </div>
                                    <div className="form-two-col">
                                        <div className="form-group">
                                            <label className="form-label">Дедлайн</label>
                                            <input type="datetime-local" value={form.deadline}
                                                onChange={e => setForm({ ...form, deadline: e.target.value })} />
                                        </div>
                                        <div className="form-group">
                                            <label className="form-label">Статус</label>
                                            <select value={form.status || "todo"}
                                                onChange={e => setForm({ ...form, status: e.target.value })}>
                                                {STATUS_LIST.map(s => (
                                                    <option key={s.key} value={s.key}>{s.icon} {s.label}</option>
                                                ))}
                                            </select>
                                        </div>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">Приоритет</label>
                                        <select value={form.priority || "medium"} onChange={e => setForm({ ...form, priority: e.target.value })}>
                                            <option value="low">⚪ Низкий</option>
                                            <option value="medium">🔵 Средний</option>
                                            <option value="high">🟠 Высокий</option>
                                            <option value="critical">🔴 Критический</option>
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">Повторение</label>
                                        <select value={form.recurrence_rule || "none"} onChange={e => setForm({ ...form, recurrence_rule: e.target.value })}>
                                            <option value="none">Не повторяется</option>
                                            <option value="daily">🔁 Каждый день</option>
                                            <option value="weekly">🔁 Каждую неделю</option>
                                            <option value="monthly">🔁 Каждый месяц</option>
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">Проект</label>
                                        <select value={form.project_id || ""} onChange={e => setForm({ ...form, project_id: e.target.value })}>
                                            <option value="">— Без проекта —</option>
                                            {appProjects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">Назначить</label>
                                        <select value={assignType} onChange={e => setAssignType(e.target.value)}>
                                            <option value="self">Себе</option>
                                            <option value="user">Пользователю</option>
                                            <option value="group">Группе</option>
                                            <option value="none">Никому</option>
                                        </select>
                                    </div>
                                    {assignType === "group" && (
                                        <div className="form-group">
                                            <label className="form-label">Группа</label>
                                            <select value={selectedGroupId} onChange={e => setSelectedGroupId(e.target.value)}>
                                                <option value="">Выберите группу</option>
                                                {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                                            </select>
                                        </div>
                                    )}
                                    {assignType === "user" && (
                                        <div className="form-group">
                                            <label className="form-label">Пользователь</label>
                                            <select value={selectedUserId} onChange={e => setSelectedUserId(e.target.value)}>
                                                <option value="">Выберите пользователя</option>
                                                {users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                                            </select>
                                        </div>
                                    )}
                                    {error && <div className="alert">{error}</div>}
                                    <button type="submit" className="btn btn-primary">
                                        <Icon d={ICONS.plus} /> Создать задачу
                                    </button>
                                </form>
                            </div>

                            <div className="card">
                                <div className="section-header">
                                    <div>
                                        <div className="section-title">Задачи</div>
                                        <div className="section-sub">
                                            {tasksTotal == null
                                                ? "Загрузка…"
                                                : tasksTotal > 0
                                                    ? `${tasksTotal} задач${searchQuery.trim() ? " (по запросу)" : ""} · стр. ${tasksPage}/${tasksTotalPages}`
                                                    : "Нет задач"}
                                        </div>
                                    </div>
                                    <div style={{ display: "flex", gap: 8 }}>
                                        <button className="btn btn-ghost btn-sm" onClick={handleExportCsv} disabled={exporting}>
                                            📄 {exporting ? "Экспорт…" : "Экспорт в CSV"}
                                        </button>
                                        <input
                                            ref={importInputRef}
                                            type="file"
                                            accept=".csv,.xlsx"
                                            style={{ display: "none" }}
                                            onChange={handleImportFile}
                                        />
                                        <button
                                            className="btn btn-ghost btn-sm"
                                            onClick={() => importInputRef.current?.click()}
                                            disabled={importing}
                                        >
                                            📥 {importing ? "Импорт…" : "Импорт из CSV/Excel"}
                                        </button>
                                        <button className="btn btn-ghost btn-sm" onClick={() => loadTasks(tasksPage, viewMode)} disabled={loading}>
                                            <Icon d={ICONS.refresh} /> {loading ? "…" : "Обновить"}
                                        </button>
                                    </div>
                                </div>
                                <div className="form-two-col" style={{ marginBottom: 12 }}>
                                    <div className="form-group" style={{ marginBottom: 0 }}>
                                        <input
                                            type="text"
                                            value={searchQuery}
                                            onChange={e => setSearchQuery(e.target.value)}
                                            placeholder="Поиск по названию и описанию…"
                                        />
                                    </div>
                                    <div className="form-group" style={{ marginBottom: 0 }}>
                                        <select value={tagFilter} onChange={e => setTagFilter(e.target.value)}>
                                            <option value="">Все теги</option>
                                            {allTags.map(t => (
                                                <option key={t.id} value={t.id}>{t.name}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>

                                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginBottom: 12 }}>
                                    {filterPresets.map(preset => (
                                        <span key={preset.id} style={{
                                            display: "inline-flex", alignItems: "center", gap: 4,
                                            background: "var(--surface2)", border: "1px solid var(--border)",
                                            borderRadius: "var(--radius-sm)", overflow: "hidden",
                                        }}>
                                            <button
                                                className="btn btn-ghost btn-sm"
                                                style={{ border: "none" }}
                                                onClick={() => handleApplyPreset(preset)}
                                                title="Применить пресет"
                                            >
                                                {preset.name}
                                            </button>
                                            <button
                                                className="btn btn-ghost btn-sm"
                                                style={{ border: "none", padding: "4px 8px", color: "var(--red)" }}
                                                onClick={() => handleDeletePreset(preset.id)}
                                                title="Удалить пресет"
                                            >
                                                ×
                                            </button>
                                        </span>
                                    ))}

                                    <input
                                        type="text"
                                        value={presetNameInput}
                                        onChange={e => setPresetNameInput(e.target.value)}
                                        placeholder="Название пресета…"
                                        style={{ width: 160, padding: "6px 10px" }}
                                    />
                                    <button className="btn btn-ghost btn-sm" onClick={handleSavePreset} disabled={savingPreset}>
                                        💾 {savingPreset ? "Сохраняю…" : "Сохранить как пресет"}
                                    </button>
                                </div>

                                {loading ? (
                                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка задач…</div>
                                ) : tasks.length === 0 ? (
                                    <div className="empty-state">
                                        <div className="empty-icon">{searchQuery.trim() ? "🔍" : "📋"}</div>
                                        {searchQuery.trim() ? `Ничего не найдено по запросу «${searchQuery}»` : "Задач нет. Создайте первую!"}
                                    </div>
                                ) : (
                                    <>
                                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                                            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
                                                <input
                                                    type="checkbox"
                                                    checked={visibleTasks.length > 0 && visibleTasks.every(t => selectedTaskIds.has(t.id))}
                                                    onChange={toggleSelectAllVisible}
                                                />
                                                Выбрать все на странице
                                            </label>
                                        </div>

                                        {selectedTaskIds.size > 0 && (
                                            <div style={{
                                                display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8,
                                                padding: "10px 12px", marginBottom: 12,
                                                background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)",
                                            }}>
                                                <span style={{ fontWeight: 600, fontSize: 13 }}>Выбрано: {selectedTaskIds.size}</span>

                                                <select value={bulkStatus} onChange={e => setBulkStatus(e.target.value)} style={{ maxWidth: 140 }}>
                                                    <option value="">Статус…</option>
                                                    <option value="backlog">Очередь</option>
                                                    <option value="todo">Новые</option>
                                                    <option value="in_progress">В работе</option>
                                                    <option value="review">На проверке</option>
                                                    <option value="done">Готово</option>
                                                </select>

                                                <select value={bulkPriority} onChange={e => setBulkPriority(e.target.value)} style={{ maxWidth: 140 }}>
                                                    <option value="">Приоритет…</option>
                                                    <option value="low">Низкий</option>
                                                    <option value="medium">Средний</option>
                                                    <option value="high">Высокий</option>
                                                    <option value="critical">Критический</option>
                                                </select>

                                                <select value={bulkTagId} onChange={e => setBulkTagId(e.target.value)} style={{ maxWidth: 140 }}>
                                                    <option value="">Тег…</option>
                                                    {allTags.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                                                </select>

                                                <select value={bulkUserId} onChange={e => setBulkUserId(e.target.value)} style={{ maxWidth: 160 }}>
                                                    <option value="">Исполнитель…</option>
                                                    {users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                                                </select>

                                                <button className="btn btn-primary btn-sm" onClick={handleBulkApply} disabled={bulkApplying}>
                                                    {bulkApplying ? "Применяю…" : "Применить"}
                                                </button>
                                                <button className="btn btn-ghost btn-sm" onClick={() => setSelectedTaskIds(new Set())} disabled={bulkApplying}>
                                                    Отменить выбор
                                                </button>
                                            </div>
                                        )}

                                        <div className="task-list">
                                            {visibleTasks.map(task => (
                                                <TaskCard key={task.id} task={task}
                                                    groups={groups} users={users} token={token}
                                                    allTags={allTags}
                                                    onTagsCreated={loadTags}
                                                    onTagsUpdated={handleTaskTagsUpdated}
                                                    onToggle={handleToggleTask}
                                                    onDelete={handleDeleteTask}
                                                    onUpdate={handleUpdateTask}
                                                    onReassign={handleReassignTask}
                                                    currentUserId={currentUserId}
                                                    currentRole={currentRole}
                                                    selected={selectedTaskIds.has(task.id)}
                                                    onToggleSelect={toggleTaskSelection} />
                                            ))}
                                        </div>
                                        <Pagination page={tasksPage} totalPages={tasksTotalPages}
                                            onPage={p => loadTasks(p, viewMode)} />
                                    </>
                                )}
                            </div>

                            {importSummary && (
                                <div style={{
                                    position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    zIndex: 1000, padding: 16,
                                }} onClick={e => { if (e.target === e.currentTarget) setImportSummary(null); }}>
                                    <div style={{
                                        background: "var(--bg-card)", border: "1px solid var(--border)",
                                        borderRadius: 16, padding: 24, width: "100%", maxWidth: 480,
                                    }}>
                                        <div style={{ fontWeight: 700, fontSize: 17, marginBottom: 12 }}>Импорт завершён</div>
                                        <div style={{ marginBottom: 16 }}>Создано задач: <b>{importSummary.created}</b></div>

                                        {importSummary.errors.length > 0 && (
                                            <div style={{ marginBottom: 16 }}>
                                                <div style={{ color: "var(--red)", fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                                                    Пропущено строк: {importSummary.errors.length}
                                                </div>
                                                <ul style={{ maxHeight: 140, overflowY: "auto", fontSize: 13, margin: 0, paddingLeft: 18 }}>
                                                    {importSummary.errors.map((e, i) => (
                                                        <li key={i}>Строка {e.row}: {e.message}</li>
                                                    ))}
                                                </ul>
                                            </div>
                                        )}

                                        {importSummary.warnings.length > 0 && (
                                            <div style={{ marginBottom: 16 }}>
                                                <div style={{ color: "var(--text-muted)", fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                                                    Предупреждения: {importSummary.warnings.length}
                                                </div>
                                                <ul style={{ maxHeight: 140, overflowY: "auto", fontSize: 13, margin: 0, paddingLeft: 18 }}>
                                                    {importSummary.warnings.map((w, i) => (
                                                        <li key={i}>Строка {w.row}: {w.message}</li>
                                                    ))}
                                                </ul>
                                            </div>
                                        )}

                                        <button className="btn btn-primary" style={{ width: "100%" }} onClick={() => setImportSummary(null)}>
                                            Закрыть
                                        </button>
                                    </div>
                                </div>
                            )}
                        </main>
                    </div>
                </div>
            )}
            {profileUserId != null ? (
                <UserProfilePage
                    userId={profileUserId}
                    token={token}
                    currentUserId={currentUserId}
                    onClose={() => setProfileUserId(null)}
                    onOpenTask={(title) => { setProfileUserId(null); setTab("tasks"); setSearchQuery(title); }}
                />
            ) : (
                <>
                    {/* ── DASHBOARD TAB ── */}
                    {tab === "dashboard" && (
                        <div style={{ maxWidth: 720, margin: "0 auto", padding: "16px 16px 0" }}>
                            <DashboardTab
                                stats={dashStats}
                                loading={dashLoading}
                                username={currentUsername}
                                role={currentRole}
                                token={token}
                            />
                        </div>
                    )}
                    {/* ── TIMELINE TAB ── */}
                    {tab === "timeline" && (
                        <div style={{ maxWidth: 720, margin: "0 auto", padding: "16px 16px 0" }}>
                            <TimelineTab token={token} />
                        </div>
                    )}
                    {/* ── PROJECTS TAB ── */}
                    {tab === "projects" && (
                        <div>
                            <ProjectsTab token={token} canManage={canManage}
                                currentUserId={currentUserId} currentRole={currentRole} />
                        </div>
                    )}
                    {/* ── KANBAN TAB ── */}
                    {tab === "kanban" && (
                        <div>
                            <KanbanTab token={token} />
                        </div>
                    )}
                    {/* ── CALENDAR TAB (визуальный календарь дедлайнов) ── */}
                    {tab === "calendar" && (
                        <div>
                            <DeadlineCalendarTab
                                token={token}
                                onOpenTask={(title) => { setTab("tasks"); setSearchQuery(title); }}
                            />
                        </div>
                    )}
                    {/* ── GROUPS TAB ── */}
                    {tab === "groups" && (
                        <div>
                            <GroupsTab token={token} currentRole={currentRole} />
                        </div>
                    )}
                    {/* ── TEAM TAB ── */}
                    {tab === "team" && (
                        <div style={{ maxWidth: 860, margin: "0 auto", padding: "16px 16px 0" }}>
                            <TeamTab token={token} currentUserId={currentUserId} />
                        </div>
                    )}
                    {tab === "templates" && (
                        <div>
                            <TemplatesTab token={token} />
                        </div>
                    )}
                    {/* ── SETTINGS (Токены / Вебхуки / Календарь / 2FA) ── */}
                    {(tab === "tokens" || tab === "webhooks" || tab === "ical" || tab === "2fa") && (
                        <div style={{ maxWidth: 860, margin: "0 auto", padding: "16px 16px 0" }}>
                            <div className="tab-bar" style={{ marginBottom: 16, display: "inline-flex" }}>
                                <button className={`tab-btn${tab === "2fa" ? " active" : ""}`} onClick={() => setTab("2fa")}>
                                    🔒 Профиль и 2FA
                                </button>
                                <button className={`tab-btn${tab === "tokens" ? " active" : ""}`} onClick={() => setTab("tokens")}>
                                    🔑 Токены
                                </button>
                                <button className={`tab-btn${tab === "webhooks" ? " active" : ""}`} onClick={() => setTab("webhooks")}>
                                    <Icon d={ICONS.link} /> Вебхуки
                                </button>
                                <button className={`tab-btn${tab === "ical" ? " active" : ""}`} onClick={() => setTab("ical")}>
                                    <Icon d={ICONS.calendar} /> Экспорт (iCal)
                                </button>
                            </div>
                            {tab === "2fa" && (
                                <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                                    <TwoFactorTab token={token} />
                                    <ChangePasswordCard token={token} />
                                </div>
                            )}
                            {tab === "tokens" && <TokensTab token={token} />}
                            {tab === "webhooks" && <WebhooksTab token={token} />}
                            {tab === "ical" && <CalendarTab token={token} />}
                        </div>
                    )}
                    {/* ── TRASH TAB ── */}
                    {tab === "trash" && (
                        <div>
                            <div className="card" style={{ marginTop: 0 }}>
                                <div className="section-header">
                                    <div>
                                        <div className="section-title">Корзина</div>
                                        <div className="section-sub">Мягко удалённые задачи — можно восстановить</div>
                                    </div>
                                    <button className="btn btn-ghost btn-sm" onClick={() => loadTrash(1)} disabled={loading}>
                                        <Icon d={ICONS.refresh} /> Обновить
                                    </button>
                                </div>
                                {loading ? (
                                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                                ) : trashTasks.length === 0 ? (
                                    <div className="empty-state"><div className="empty-icon">🗑️</div>Корзина пуста</div>
                                ) : (
                                    <>
                                        <div className="task-list">
                                            {trashTasks.map(task => (
                                                <TrashCard key={task.id} task={task}
                                                    onRestore={handleRestoreTask} onHardDelete={handleHardDelete} />
                                            ))}
                                        </div>
                                        <Pagination page={trashPage} totalPages={trashTotalPages} onPage={p => loadTrash(p)} />
                                    </>
                                )}
                            </div>
                        </div>
                    )}
                </>
            )}
        </div>
    );
}


export default App;
