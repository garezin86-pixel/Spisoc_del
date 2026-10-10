export function describeTimelineEvent(e) {
    const who = e.username || "Кто-то";
    if (e.entity_type === "comments") {
        if (e.action === "create") return `${who} прокомментировал(а) «${e.task_title}»`;
        if (e.action === "update") return `${who} отредактировал(а) комментарий к «${e.task_title}»`;
        if (e.action === "delete") return `${who} удалил(а) комментарий к «${e.task_title}»`;
        return `${who} · комментарий к «${e.task_title}»`;
    }
    if (e.entity_type === "deals") {
        const title = e.deal_title ?? "";
        if (e.action === "create") return `${who} создал(а) сделку «${title}»`;
        if (e.action === "delete") return `${who} удалил(а) сделку «${title}»`;
        const stage = (e.changes ?? []).find(c => c.field === "stage_id");
        if (e.action === "update" && stage) return `${who} перевёл(а) сделку «${title}»: ${stage.old} → ${stage.new}`;
        if (e.action === "update") return `${who} изменил(а) сделку «${title}»`;
        return `${who} · сделка «${title}»`;
    }
    if (e.action === "create") return `${who} создал(а) задачу «${e.task_title}»`;
    if (e.action === "delete") return `${who} удалил(а) задачу «${e.task_title}»`;
    if (e.action === "restore") return `${who} восстановил(а) задачу «${e.task_title}»`;
    if (e.action === "update") return `${who} изменил(а) задачу «${e.task_title}»`;
    return `${who} · «${e.task_title}»`;
}

// ─── UserProfilePage — карточка профиля: аватар, должность, статистика,
// задачи (через target_user_id) и активность (через Timeline/user_id) ─────
// Кэш ID пользователей без аватара — общий на всю сессию вкладки. Без него
// каждый отдельный <UserProfileAvatar> (например, десяток сообщений одного
// и того же человека в чате) заново бьёт по сети и получает 404.
