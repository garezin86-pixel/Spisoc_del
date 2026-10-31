import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, apiRequest, clearTokens, getRefreshToken, saveTokens, setTokenRefreshHandler } from "./api";
import { AIPanel } from "./components/AIPanel";
import { ChatBubble } from "./components/ChatBubble";
import { ClientPicker } from "./components/ClientPicker";
import { PushNotificationsCard } from "./features/PushNotificationsCard";
import { Sidebar } from "./components/layout/Sidebar";
import { TaskRow } from "./components/TaskRow";
import { TopBar } from "./components/layout/TopBar";
import { groupOfTab } from "./constants/navigation";
import { APP_DESCRIPTION, APP_LOGO, APP_NAME } from "./constants/branding";
import { CommandPalette } from "./components/CommandPalette";
import { Icon } from "./components/Icon";
import { Pagination } from "./components/Pagination";
import { SidebarDeadlineWidget } from "./components/SidebarDeadlineWidget";
import { TaskCard } from "./components/TaskCard";
import { TrashCard } from "./components/TrashCard";
import { initialForm } from "./constants/forms";
import { ICONS } from "./constants/icons";
import { STATUS_LIST } from "./constants/status";
import { CalendarTab } from "./features/CalendarTab";
import { ChangePasswordCard } from "./features/ChangePasswordCard";
import { ClientsTab } from "./features/ClientsTab";
import { DashboardTab } from "./features/DashboardTab";
import { HomeTab } from "./features/HomeTab";
import { DeadlineCalendarTab } from "./features/DeadlineCalendarTab";
import { DealsBoard } from "./features/DealsBoard";
import { ForceChangePasswordScreen } from "./features/ForceChangePasswordScreen";
import { GroupsTab } from "./features/GroupsTab";
import { InvitesPanel } from "./features/InvitesPanel";
import { KanbanTab } from "./features/KanbanTab";
import { ProjectsTab } from "./features/ProjectsTab";
import { RegisterScreen } from "./features/RegisterScreen";
import { TeamTab } from "./features/TeamTab";
import { TemplatesTab } from "./features/TemplatesTab";
import { TimelineTab } from "./features/TimelineTab";
import { TokensTab } from "./features/TokensTab";
import { TwoFactorTab } from "./features/TwoFactorTab";
import { UserProfilePage } from "./features/UserProfilePage";
import { WebhooksTab } from "./features/WebhooksTab";
import { useWebSocket } from "./hooks/useWebSocket";
import { loginError } from "./utils/authErrors";
import { extractItems } from "./utils/extractItems";
import { decodeToken } from "./utils/token";

function App() {
    const [token, setToken] = useState(localStorage.getItem("spisoc_token"));
    const [tab, setTab] = useState("home"); // "home" | "tasks" | "projects" | "groups" | "trash" | "dashboard" | "templates" | ...
    const [homeRefreshKey, setHomeRefreshKey] = useState(0); // растёт на каждое WS-событие dashboard_changed
    const [clientToOpen, setClientToOpen] = useState(null); // клиент, карточку которого открыть при переходе с главной
    const [aiClientId, setAiClientId] = useState(null); // открытая карточка клиента — контекст для ассистента
    const [aiRefreshKey, setAiRefreshKey] = useState(0); // растёт, когда ассистент что-то изменил
    const [mfaPending, setMfaPending] = useState(null); // { mfaToken } — ждём код 2FA перед выдачей токенов
    const [show2faNudge, setShow2faNudge] = useState(false);
    const [mustChangePassword, setMustChangePassword] = useState(false);
    // Ссылка-приглашение ?invite=<код> сразу открывает регистрацию с подставленным кодом.
    const [inviteFromUrl] = useState(() => new URLSearchParams(window.location.search).get("invite") || "");
    const [authScreen, setAuthScreen] = useState(inviteFromUrl ? "register" : "login"); // "login" | "register"

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
    // Фоновая перезагрузка списка по WebSocket: события склеиваем (debounce), чтобы пачка событий = один запрос.
    const wsReloadTimerRef = useRef(null);
    // Режим вкладки «Задачи»: "list" — список, "board" — канбан. Хранится между сеансами.
    const [taskView, setTaskView] = useState(() => localStorage.getItem("spisoc_tasks_view") === "board" ? "board" : "list");
    const taskViewRef = useRef(taskView);
    const [boardKey, setBoardKey] = useState(0);
    useEffect(() => { taskViewRef.current = taskView; localStorage.setItem("spisoc_tasks_view", taskView); }, [taskView]);
    // Смены статуса, отправленные на сервер, но ещё не «устоявшиеся»: id задачи → { status, seq }.
    // Накладываются поверх любого результата loadTasks, чтобы запоздавший ответ со старым
    // статусом не откатывал локальное (оптимистичное) обновление.
    const pendingStatusRef = useRef(new Map());
    const statusSeqRef = useRef(0);

    const handleWsEvent = useCallback((event, data) => {
        const currentTab = tabRef.current;
        if (event === "task_created" || event === "task_updated" || event === "kanban_moved" || event === "task_deleted") {
            if (currentTab === "tasks") {
                // «Тихо»: без экрана «Загрузка задач…» — иначе после смены статуса (событие приходит и автору
                // изменения) список пропадал бы на время запроса, и новый статус был виден с задержкой.
                clearTimeout(wsReloadTimerRef.current);
                wsReloadTimerRef.current = setTimeout(() => {
                    if (taskViewRef.current === "board") setBoardKey(k => k + 1);
                    else loadTasks(tasksPageRef.current, viewModeRef.current, { silent: true });
                }, 300);
            }
        } else if (event === "dashboard_changed") {
            if (currentTab === "home") setHomeRefreshKey(k => k + 1); // на других вкладках главная заново загрузится при открытии
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
    const projectNames = new Map(appProjects.map(p => [p.id, p.name]));

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

    // Оболочка: мобильное меню, чат из верхней панели, последняя активная группа
    const [navOpen, setNavOpen] = useState(false);
    // Админ платформы (доступ в SQLAdmin) — не то же самое, что role="admin" (админ своей компании).
    // Признак приходит только в GET /users/me, ссылка «Админка» в меню пользователя зависит от него.
    const [isPlatformAdmin, setIsPlatformAdmin] = useState(false);
    useEffect(() => {
        if (!token) { setIsPlatformAdmin(false); return undefined; }
        let cancelled = false;
        apiRequest({ path: "/users/me", token })
            .then(me => { if (!cancelled) setIsPlatformAdmin(!!me?.is_platform_admin); })
            .catch(() => { if (!cancelled) setIsPlatformAdmin(false); });
        return () => { cancelled = true; };
    }, [token]);
    const [showCreate, setShowCreate] = useState(false);       // форма «Новая задача» (по кнопке)
    const [expandedTaskId, setExpandedTaskId] = useState(null); // раскрытая строка списка задач
    const [chatUnread, setChatUnread] = useState(0);
    const [chatToggleKey, setChatToggleKey] = useState(0);
    const [lastGroup, setLastGroup] = useState("work");
    const activeGroup = groupOfTab(tab) ?? lastGroup;   // какие страницы показывает боковое меню
    const chipGroup = groupOfTab(tab);                    // какая группа подсвечена сверху (null для Корзины/Настроек)
    useEffect(() => { const g = groupOfTab(tab); if (g) setLastGroup(g); }, [tab]);
    // Канбан теперь режим вкладки «Задачи»: старые ссылки/командная палитра с tab="kanban" ведут туда же
    useEffect(() => { if (tab === "kanban") { setTaskView("board"); setTab("tasks"); } }, [tab]);
    // Статусы могли поменяться на доске (канбан грузит свои данные) — при возврате в «Список» обновляем его,
    // иначе одна и та же задача в списке и на доске показывала бы разные статусы.
    const prevTaskViewRef = useRef(taskView);
    useEffect(() => {
        if (prevTaskViewRef.current === taskView) return;
        prevTaskViewRef.current = taskView;
        if (taskView === "list" && tabRef.current === "tasks") {
            loadTasks(tasksPageRef.current, viewModeRef.current, { silent: true });
        }
    }, [taskView]); // eslint-disable-line react-hooks/exhaustive-deps
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

    const loadTasks = useCallback(async (page = 1, filterUserGroup, { silent = false } = {}) => {
        // Отменяем предыдущий запрос если он ещё выполняется
        if (tasksAbortRef.current) tasksAbortRef.current.abort();
        const controller = new AbortController();
        tasksAbortRef.current = controller;

        const mode = filterUserGroup ?? viewModeRef.current;
        if (!silent) setLoading(true);
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
            const pending = pendingStatusRef.current;
            setTasks(extractItems(data).map(t => {
                const p = pending.get(t.id);
                return p ? { ...t, status: p.status, is_done: p.status === "done" } : t;
            }));
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
        } catch (err) { setError(loginError(err)); }
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
        } catch (err) { setError(loginError(err)); }
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
                client_id: form.client_id ? Number(form.client_id) : null,
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
            setShowCreate(false);
            setBoardKey(k => k + 1);
            await loadTasks(1);
        } catch (err) { handleAuthError(err); }
    }

    async function handleToggleTask(task, newStatus) {
        if (!newStatus) return;
        const nextIsDone = newStatus === "done";
        const seq = ++statusSeqRef.current;
        pendingStatusRef.current.set(task.id, { status: newStatus, seq });
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
            if (pendingStatusRef.current.get(task.id)?.seq === seq) pendingStatusRef.current.delete(task.id);
            setTasks(prev => prev.map(t => t.id === task.id ? task : t));
            handleAuthError(err);
            return;
        }
        // Ещё ~1.5 с держим наложение: запрос списка, начатый до записи на сервере, мог вернуться позже.
        setTimeout(() => {
            if (pendingStatusRef.current.get(task.id)?.seq === seq) pendingStatusRef.current.delete(task.id);
        }, 1500);
    }

    async function handleUpdateTask(task, updates) {
        setTasks(prev => prev.map(t => t.id === task.id ? { ...t, ...updates } : t));
        try {
            const saved = await apiRequest({ path: `/tasks/${task.id}`, method: "PATCH", token, body: updates });
            // название клиента приходит с сервера: при смене клиента локальная копия его не знает
            setTasks(prev => prev.map(t => t.id === task.id ? { ...t, client_id: saved?.client_id ?? null, client_name: saved?.client_name ?? null } : t));
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
            // На вкладке «Задачи» проект не выбирается — импортируем без привязки к проекту

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

    // Переход по разделу из бокового меню / верхней панели (сохраняет прежние побочные эффекты кнопок вкладок)
    function navigateTo(next) {
        if (next === "dashboard") loadDashboard();
        if (next === "clients") setClientToOpen(null);
        setProfileUserId(null);
        setTab(next);
    }

    // ── Login screen ─────────────────────────────────────
    if (!token && authScreen === "register") {
        return (
            <RegisterScreen
                initialInvite={inviteFromUrl}
                onBackToLogin={() => { setAuthScreen("login"); setError(null); }}
                onRegistered={(resp) => {
                    saveTokens(resp.access_token, resp.refresh_token);
                    // Код приглашения одноразово «сжигать» не нужно, но и оставлять в адресной строке незачем.
                    window.history.replaceState({}, "", window.location.pathname);
                    setAuthScreen("login");
                    setToken(resp.access_token);
                    setMustChangePassword(false);
                }}
            />
        );
    }

    if (!token) {
        return (
            <div className="login-page">
                <div className="auth-card">
                    <div className="login-logo">
                        <div className="logo-mark">{APP_LOGO}</div>
                        <div>
                            <div className="brand-name">{APP_NAME}</div>
                            <div className="brand-tagline">{APP_DESCRIPTION}</div>
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
                            <button type="button" className="btn btn-ghost btn-sm"
                                onClick={() => { setAuthScreen("register"); setError(null); }}>
                                Нет аккаунта? Зарегистрироваться
                            </button>
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
        <div className="app-layout">
            <Sidebar
                variant="side"
                activeGroup={activeGroup}
                tab={tab}
                counts={{ tasks: tasksTotal || 0, trash: trashTotal || 0 }}
                onNavigate={navigateTo}
            />
            <div className="app-main">
            <TopBar
                token={token}
                activeGroup={chipGroup}
                onNavigate={navigateTo}
                onOpenPalette={() => setPaletteOpen(true)}
                onOpenMenu={() => setNavOpen(true)}
                theme={theme}
                onToggleTheme={() => setTheme(t => t === "dark" ? "light" : "dark")}
                chatUnread={chatUnread}
                onToggleChat={() => setChatToggleKey(k => k + 1)}
                currentUserId={currentUserId}
                currentUsername={currentUsername}
                currentRole={currentRole}
                onOpenProfile={setProfileUserId}
                isPlatformAdmin={isPlatformAdmin}
                adminUrl={import.meta.env.DEV ? "http://127.0.0.1:8000/admin/" : "https://spisoc-del.onrender.com/admin/"}
                onLogout={logout}
                onOpenTask={(title) => { setTab("tasks"); setSearchQuery(title); }}
            />
        <div className="page-shell">
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
                <div className="cl-page">
                    <div className="cl-head">
                        <div>
                            <h1 className="cl-title">Задачи</h1>
                            <div className="cl-sub">
                                {taskView === "board" ? "Перетаскивайте карточки между колонками, чтобы менять статус" : tasksTotal == null
                                    ? "Загрузка…"
                                    : tasksTotal > 0
                                        ? `${tasksTotal} задач${searchQuery.trim() ? " (по запросу)" : ""} · стр. ${tasksPage}/${tasksTotalPages}`
                                        : "Нет задач"}
                            </div>
                        </div>
                        <div className="cl-actions">
                            <div className="seg" role="group" aria-label="Режим просмотра">
                                <button type="button" className={`seg-btn${taskView === "list" ? " active" : ""}`} aria-pressed={taskView === "list"} onClick={() => setTaskView("list")}>Список</button>
                                <button type="button" className={`seg-btn${taskView === "board" ? " active" : ""}`} aria-pressed={taskView === "board"} onClick={() => setTaskView("board")}>Канбан</button>
                            </div>
                            {taskView === "list" && (
                                <>
                            <button className="btn btn-ghost" onClick={handleExportCsv} disabled={exporting}>{exporting ? "Экспорт…" : "Экспорт"}</button>
                            <input ref={importInputRef} type="file" accept=".csv,.xlsx" style={{ display: "none" }} onChange={handleImportFile} />
                            <button className="btn btn-ghost" onClick={() => importInputRef.current?.click()} disabled={importing}>{importing ? "Импорт…" : "Импорт"}</button>
                            <button className="btn btn-ghost" onClick={() => loadTasks(tasksPage, viewMode)} disabled={loading}>
                                <Icon d={ICONS.refresh} /> {loading ? "…" : "Обновить"}
                            </button>
                                </>
                            )}
                            <button className="btn btn-primary" onClick={() => setShowCreate(v => !v)} aria-expanded={showCreate}>
                                <Icon d={ICONS.plus} /> Новая задача
                            </button>
                        </div>
                    </div>

                    {showCreate && (
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
                                <label className="form-label">Клиент</label>
                                <ClientPicker
                                    token={token} value={form.client_id ? Number(form.client_id) : null} name={form.client_name}
                                    onChange={(id, name) => setForm({ ...form, client_id: id ?? "", client_name: name })}
                                />
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
                    )}

                    {taskView === "board" ? (
                        <KanbanTab token={token} embedded refreshKey={boardKey} />
                    ) : (
                    <div className="tk-layout">
                        <div className="tk-main">
                            <div className="cl-tabs" role="tablist" aria-label="Чьи задачи">
                                {[{ key: "user", label: "Мои задачи" }, { key: "author", label: "Я автор" }].map(opt => (
                                    <button key={opt.key} type="button" role="tab" aria-selected={viewMode === opt.key}
                                        className={`cl-tab${viewMode === opt.key ? " active" : ""}`} onClick={() => setViewMode(opt.key)}>{opt.label}</button>
                                ))}
                            </div>

                            <div className="cl-filters">
                                <input className="form-input cl-search" type="text" aria-label="Поиск по задачам" value={searchQuery}
                                    onChange={e => setSearchQuery(e.target.value)} placeholder="Поиск по названию и описанию…" />
                                <select className="form-input dl-select" aria-label="Статус" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                                    <option value="">Статус: все</option>
                                    <option value="backlog">Очередь</option>
                                    <option value="todo">Новые</option>
                                    <option value="in_progress">В работе</option>
                                    <option value="review">На проверке</option>
                                    <option value="done">Готово</option>
                                </select>
                                <select className="form-input dl-select" aria-label="Приоритет" value={filterPriority || ""} onChange={e => setFilterPriority(e.target.value || null)}>
                                    <option value="">Приоритет: все</option>
                                    <option value="critical">🔴 Критический</option>
                                    <option value="high">🟠 Высокий</option>
                                    <option value="medium">🔵 Средний</option>
                                    <option value="low">⚪ Низкий</option>
                                </select>
                                <select className="form-input dl-select" aria-label="Срок" value={filterType} onChange={e => setFilterType(e.target.value)}>
                                    <option value="">Срок: любой</option>
                                    <option value="today">На сегодня</option>
                                    <option value="overdue">Просроченные</option>
                                    <option value="planned">Запланированные</option>
                                    <option value="deadline_null">Без дедлайна</option>
                                </select>
                                <select className="form-input dl-select" aria-label="Тег" value={tagFilter} onChange={e => setTagFilter(e.target.value)}>
                                    <option value="">Тег: все</option>
                                    {allTags.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                                </select>
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

                            <div className="card tr-card">
                                {loading ? (
                                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка задач…</div>
                                ) : tasks.length === 0 ? (
                                    <div className="empty-state">
                                        <div className="empty-icon">{searchQuery.trim() ? "🔍" : "📋"}</div>
                                        {searchQuery.trim() ? `Ничего не найдено по запросу «${searchQuery}»` : "Задач нет. Создайте первую!"}
                                    </div>
                                ) : (
                                    <>
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

                                        <div className="tr-table" role="table" aria-label="Список задач">
                                            <div className="tr-head" role="row">
                                                <input
                                                    type="checkbox" className="tr-check" aria-label="Выбрать все задачи на странице"
                                                    checked={visibleTasks.length > 0 && visibleTasks.every(t => selectedTaskIds.has(t.id))}
                                                    onChange={toggleSelectAllVisible}
                                                />
                                                <span>Задача</span><span>Срок</span><span>Статус</span><span>Исп.</span>
                                            </div>
                                            {visibleTasks.map(task => (
                                                <TaskRow
                                                    key={task.id} task={task}
                                                    projectName={projectNames.get(task.project_id)}
                                                    selected={selectedTaskIds.has(task.id)} onToggleSelect={toggleTaskSelection}
                                                    expanded={expandedTaskId === task.id}
                                                    onToggleExpand={() => setExpandedTaskId(id => id === task.id ? null : task.id)}
                                                    onToggleStatus={handleToggleTask}
                                                >
                                                    <TaskCard task={task} embedded
                                                        groups={groups} users={users} token={token}
                                                        onOpenClient={(id) => { setClientToOpen(id); setTab("clients"); }}
                                                        allTags={allTags}
                                                        onTagsCreated={loadTags}
                                                        onTagsUpdated={handleTaskTagsUpdated}
                                                        onToggle={handleToggleTask}
                                                        onDelete={handleDeleteTask}
                                                        onUpdate={handleUpdateTask}
                                                        onReassign={handleReassignTask}
                                                        currentUserId={currentUserId}
                                                        currentRole={currentRole} />
                                                </TaskRow>
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
                        </div>

                        <aside className="tk-rail">
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
                            <SidebarDeadlineWidget
                                token={token}
                                onOpenTask={(title) => { setSearchQuery(title); }}
                                onOpenFullCalendar={() => setTab("calendar")}
                            />
                        </aside>
                    </div>
                    )}
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
                    {/* ── HOME TAB: что делать сегодня ── */}
                    {tab === "home" && (
                        <div>
                            <HomeTab
                                token={token}
                                username={currentUsername}
                                refreshKey={homeRefreshKey}
                                onOpenTask={(title) => { setTab("tasks"); setSearchQuery(title); }}
                                onOpenClient={(id) => { setClientToOpen(id); setTab("clients"); }}
                                onOpenDeals={() => setTab("deals")}
                                canManage={canManage}
                                users={users}
                                currentUserId={currentUserId}
                            />
                        </div>
                    )}
                    {/* ── DASHBOARD TAB (статистика задач) ── */}
                    {tab === "dashboard" && (
                        <div>
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
                        <div>
                            <TimelineTab token={token} />
                        </div>
                    )}
                    {/* ── PROJECTS TAB ── */}
                    {tab === "projects" && (
                        <div>
                            <ProjectsTab token={token} canManage={canManage}
                                currentUserId={currentUserId} currentRole={currentRole}
                                onOpenClient={(id) => { setClientToOpen(id); setTab("clients"); }} />
                        </div>
                    )}
                    {/* ── CLIENTS TAB (lite CRM) ── */}
                    {tab === "clients" && (
                        <div>
                            <ClientsTab
                                token={token} canManage={canManage} currentUserId={currentUserId} initialClientId={clientToOpen}
                                onSelectedChange={(id) => {
                                    setAiClientId(id);
                                    // карточку закрыли — «клиент к открытию» сбрасываем, иначе повторная просьба открыть того же клиента не сработает
                                    if (id === null) setClientToOpen(null);
                                }}
                                refreshSignal={aiRefreshKey}
                            />
                        </div>
                    )}
                    {/* ── DEALS TAB: воронка всех сделок компании ── */}
                    {tab === "deals" && (
                        <div>
                            <DealsBoard token={token} canManage={canManage} currentUserId={currentUserId} isAdmin={currentRole === "admin"} />
                        </div>
                    )}
                    {/* ── CALENDAR TAB (визуальный календарь дедлайнов) ── */}
                    {tab === "calendar" && (
                        <div>
                            <DeadlineCalendarTab
                                token={token}
                                onOpenTask={(title) => { setTab("tasks"); setSearchQuery(title); }}
                                onOpenClient={(id) => { setClientToOpen(id); setTab("clients"); }}
                                currentUserId={currentUserId}
                                canManage={canManage}
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
                        <div className="cl-page">
                            <TeamTab token={token} currentUserId={currentUserId} />
                            {currentRole === "admin" && <InvitesPanel token={token} />}
                        </div>
                    )}
                    {tab === "templates" && (
                        <div>
                            <TemplatesTab token={token} />
                        </div>
                    )}
                    {/* ── SETTINGS (Токены / Вебхуки / Календарь / 2FA) ── */}
                    {tab === "2fa" && (
                        <div className="cl-page">
                            <div className="cl-head">
                                <div>
                                    <h1 className="cl-title">Настройки</h1>
                                    <div className="cl-sub">Безопасность аккаунта и уведомления</div>
                                </div>
                            </div>
                            <div className="st-cols">
                                <TwoFactorTab token={token} />
                                <div className="st-col">
                                    <ChangePasswordCard token={token} />
                                    <PushNotificationsCard token={token} />
                                </div>
                            </div>
                        </div>
                    )}
                    {/* Инструменты: каждая страница самостоятельная (раньше — вкладки внутри «Настроек») */}
                    {tab === "tokens" && <TokensTab token={token} />}
                    {tab === "webhooks" && <WebhooksTab token={token} />}
                    {tab === "ical" && <CalendarTab token={token} />}
                    {/* ── TRASH TAB ── */}
                    {tab === "trash" && (
                        <div className="cl-page">
                            <div className="cl-head">
                                <div>
                                    <h1 className="cl-title">Корзина</h1>
                                    <div className="cl-sub">Мягко удалённые задачи — можно восстановить</div>
                                </div>
                                <div className="cl-actions">
                                    <button className="btn btn-ghost" onClick={() => loadTrash(1)} disabled={loading}>
                                        <Icon d={ICONS.refresh} /> Обновить
                                    </button>
                                </div>
                            </div>
                            {loading ? (
                                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                            ) : trashTasks.length === 0 ? (
                                <div className="empty-state"><div className="empty-icon">🗑️</div>Корзина пуста</div>
                            ) : (
                                <div className="card tr-card">
                                    <div className="tr-table">
                                        {trashTasks.map(task => (
                                            <TrashCard key={task.id} task={task}
                                                onRestore={handleRestoreTask} onHardDelete={handleHardDelete} />
                                        ))}
                                    </div>
                                    <Pagination page={trashPage} totalPages={trashTotalPages} onPage={p => loadTrash(p)} />
                                </div>
                            )}
                        </div>
                    )}
                </>
            )}
        </div>
            </div>
            {navOpen && (
                <Sidebar
                    variant="drawer"
                    activeGroup={activeGroup}
                    tab={tab}
                    counts={{ tasks: tasksTotal || 0, trash: trashTotal || 0 }}
                    onNavigate={navigateTo}
                    onClose={() => setNavOpen(false)}
                    theme={theme}
                    onToggleTheme={() => setTheme(t => t === "dark" ? "light" : "dark")}
                />
            )}
            <CommandPalette
                open={paletteOpen}
                onClose={() => setPaletteOpen(false)}
                token={token}
                setTab={setTab}
                setSearchQuery={setSearchQuery}
                setTheme={setTheme}
                onLogout={logout}
            />

            <ChatBubble token={token} currentUserId={currentUserId} wsEvent={chatWsEvent} hideLauncher toggleKey={chatToggleKey} onUnreadChange={setChatUnread} />
            <AIPanel
                token={token}
                clientId={tab === "clients" ? aiClientId : null}
                onChanged={() => { setAiRefreshKey(k => k + 1); setHomeRefreshKey(k => k + 1); }}
                onOpenClient={(id) => { setClientToOpen(id); setTab("clients"); }}
            />

        </div>
    );
}


export default App;
