export const ROLE_LABELS = { admin: "Админ", manager: "Менеджер", user: "Участник" };


export const ROLE_COLORS = {
    admin: { color: "var(--red)", bg: "var(--red-dim)" },
    manager: { color: "var(--amber)", bg: "var(--amber-dim)" },
    user: { color: "var(--accent-light)", bg: "rgba(124,106,240,0.12)" },
};

// Горизонтальные ряды вкладок (каналы чата, ЛС-диалоги и т.п.) раньше можно
// было прокручивать только стрелками/drag — обычное колесо мыши скроллило
// страницу насквозь, а не сам ряд. Хук вешает нативный (не-passive) wheel
// listener и переводит вертикальный скролл колеса в горизонтальный внутри
// элемента; preventDefault нужен, чтобы страница за рядом не скроллилась
// одновременно — через React onWheel (passive по умолчанию) это не сделать.
