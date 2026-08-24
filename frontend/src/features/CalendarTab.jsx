import { useState, useEffect, useCallback } from "react";
import { apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { ICONS } from "../constants/icons";

export function CalendarTab({ token }) {
    const [feedUrl, setFeedUrl] = useState(null);
    const [loading, setLoading] = useState(true);
    const [creating, setCreating] = useState(false);
    const [copied, setCopied] = useState(false);
    const [error, setError] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await apiRequest({ path: "/calendar/token", token });
            setFeedUrl(data?.feed_url ?? null);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => { load(); }, [load]);

    async function handleCreateOrRotate() {
        setCreating(true);
        setError(null);
        try {
            const data = await apiRequest({ path: "/calendar/token", method: "POST", token });
            setFeedUrl(data.feed_url);
            setCopied(false);
        } catch (err) {
            setError(err.message);
        } finally {
            setCreating(false);
        }
    }

    async function handleCopy() {
        try {
            await navigator.clipboard.writeText(feedUrl);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch { /* clipboard недоступен — пользователь скопирует вручную */ }
    }

    // webcal:// — специальная схема, по которой Google Calendar/Outlook/Apple
    // Calendar понимают "это ссылка на подписку", а не просто файл для скачивания.
    const webcalUrl = feedUrl ? feedUrl.replace(/^https?:\/\//, "webcal://") : null;
    const googleCalendarUrl = webcalUrl ? `https://calendar.google.com/calendar/r?cid=${encodeURIComponent(webcalUrl)}` : null;

    return (
        <div>
            <div className="card" style={{ marginTop: 0 }}>
                <div className="section-header">
                    <div>
                        <div className="section-title"><Icon d={ICONS.calendar} /> Календарь дедлайнов</div>
                        <div className="section-sub">
                            Подпишитесь на дедлайны своих задач в Google Calendar, Outlook или Apple Calendar —
                            они будут показываться в вашем основном календаре без захода в приложение.
                            Календарь сам периодически перечитывает ссылку, ничего обновлять вручную не нужно.
                        </div>
                    </div>
                </div>

                {error && <div className="alert" style={{ marginBottom: 12 }}>{error}</div>}

                {loading ? (
                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                ) : !feedUrl ? (
                    <div className="empty-state">
                        <div className="empty-icon">📅</div>
                        Ссылка ещё не создана
                        <div style={{ marginTop: 12 }}>
                            <button className="btn btn-primary" onClick={handleCreateOrRotate} disabled={creating}>
                                <Icon d={ICONS.plus} /> {creating ? "Создание…" : "Создать ссылку"}
                            </button>
                        </div>
                    </div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                            <code style={{
                                flex: 1, padding: "8px 12px", background: "var(--surface2)",
                                borderRadius: 6, fontSize: 13, wordBreak: "break-all",
                            }}>
                                {feedUrl}
                            </code>
                            <button type="button" className="btn btn-sm btn-primary" onClick={handleCopy}>
                                {copied ? "✓ Скопировано" : "Скопировать"}
                            </button>
                        </div>

                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                            <a className="btn btn-sm" href={googleCalendarUrl} target="_blank" rel="noreferrer">
                                Добавить в Google Calendar
                            </a>
                            <a className="btn btn-sm" href={webcalUrl}>
                                Добавить в Outlook / Apple Calendar
                            </a>
                            <button className="btn btn-sm" onClick={handleCreateOrRotate} disabled={creating}>
                                {creating ? "…" : "Перевыпустить ссылку"}
                            </button>
                        </div>

                        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                            Ссылку не стоит выкладывать публично — по ней доступны дедлайны ваших задач без
                            дополнительного пароля. Если она куда-то утекла — нажмите «Перевыпустить», старая
                            сразу перестанет работать.
                            <br />
                            В Google Calendar: «Другие календари» → «+» → «По URL» — если кнопка выше не сработала
                            автоматически, вставьте ссылку туда вручную.
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}


// ─── Принудительная смена пароля (после автосоздания через бота) ──
