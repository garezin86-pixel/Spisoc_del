// Структура навигации: верхняя панель переключает ГРУППЫ, боковое меню показывает
// СТРАНИЦЫ активной группы. `tab` — значение состояния `tab` в App.jsx.
const TEMPLATE_ICON = "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zm-1 1.5L18.5 9H13V3.5zM6 20V4h5v7h7v9H6z";

export const NAV_GROUPS = [
    {
        id: "work",
        label: "Работа",
        items: [
            { tab: "home", label: "Главная", icon: "home" },
            { tab: "tasks", label: "Задачи", icon: "check", count: "tasks" },
            { tab: "projects", label: "Проекты", icon: "folder" },
            { tab: "calendar", label: "Календарь", icon: "calendar" },
            { tab: "timeline", label: "Лента", icon: "clock" },
            { tab: "dashboard", label: "Статистика", icon: "chart" },
            { tab: "templates", label: "Шаблоны", path: TEMPLATE_ICON },
        ],
    },
    {
        id: "crm",
        label: "CRM",
        items: [
            { tab: "clients", label: "Клиенты", icon: "user" },
            { tab: "deals", label: "Воронка", icon: "kanban" },
        ],
    },
    {
        id: "comm",
        label: "Коммуникации",
        items: [
            { tab: "groups", label: "Группы", icon: "group" },
            { tab: "team", label: "Команда", icon: "user" },
        ],
    },
    {
        id: "tools",
        label: "Инструменты",
        items: [
            { tab: "tokens", label: "API-токены", icon: "link" },
            { tab: "webhooks", label: "Вебхуки", icon: "refresh" },
            { tab: "ical", label: "iCal-календарь", icon: "calendar" },
        ],
    },
];

// Всегда внизу бокового меню, вне зависимости от группы.
export const FOOTER_ITEMS = [
    { tab: "trash", label: "Корзина", icon: "trash", count: "trash" },
    { tab: "2fa", label: "Настройки", icon: "shield" },
];

export function groupOfTab(tab) {
    const g = NAV_GROUPS.find(group => group.items.some(i => i.tab === tab));
    return g ? g.id : null;
}

// Вкладки, которые рисуются внутри общей страницы «Настройки/Инструменты».
export const TOOLS_TABS = ["tokens", "webhooks", "ical", "2fa"];
