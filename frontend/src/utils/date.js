export function parseBackendDate(deadline) {
    if (!deadline) return null;
    const m = String(deadline).match(/^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})/);
    if (m) return new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]), Number(m[4]), Number(m[5]));
    const d = new Date(deadline);
    return isNaN(d.getTime()) ? null : d;
}


export function formatDeadline(deadline) {
    if (!deadline) return null;
    try {
        const d = parseBackendDate(deadline);
        if (!d) return null;
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const dDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
        const diff = dDay - today;
        const isFmt = /^\d{2}\.\d{2}/.test(String(deadline));
        return {
            fmt: isFmt ? String(deadline) : d.toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }),
            isOverdue: diff < 0,
            isToday: diff === 0,
        };
    } catch { return null; }
}
