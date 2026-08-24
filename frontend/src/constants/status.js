export const STATUS_LIST = [
    { key: "backlog", label: "Очередь", icon: "📥", color: "#6b7280" },
    { key: "todo", label: "Новые", icon: "🆕", color: "#7c6af0" },
    { key: "in_progress", label: "В работе", icon: "🚧", color: "#f59e0b" },
    { key: "review", label: "На проверке", icon: "🔎", color: "#3b82f6" },
    { key: "done", label: "Готово", icon: "✅", color: "#22c55e" },
];


export const STATUS_META = Object.fromEntries(STATUS_LIST.map(s => [s.key, s]));

// Выпадающее меню выбора статуса — заменяет кнопки "Вперёд"/"Назад"
