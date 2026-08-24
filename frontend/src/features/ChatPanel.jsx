import { useState, useEffect, useCallback, useRef } from "react";
import { apiRequest } from "../api";
import { UserProfileAvatar } from "../components/UserProfileAvatar";
import { useHorizontalWheelScroll } from "../hooks/useHorizontalWheelScroll";
import { extractItems } from "../utils/extractItems";

export function ChatPanel({
    token, currentUserId, channels, activeChannel, setActiveChannel,
    dmConversations, activeDm, setActiveDm, onNewDmConversation, onCloseDm,
    wsEvent, onClose,
}) {
    const [messages, setMessages] = useState([]);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [hasMore, setHasMore] = useState(true);
    const [draft, setDraft] = useState("");
    const [sending, setSending] = useState(false);
    const [error, setError] = useState(null);
    const [dmPickerOpen, setDmPickerOpen] = useState(false);
    const [dmSearch, setDmSearch] = useState("");
    const [pickerUsers, setPickerUsers] = useState([]);
    const [pickerLoading, setPickerLoading] = useState(false);
    const listRef = useRef(null);
    const shouldStickToBottom = useRef(true);
    const channelsRowRef = useHorizontalWheelScroll();
    const dmRowRef = useHorizontalWheelScroll();

    const isDm = activeDm != null;

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = new URLSearchParams({ limit: "50" });
            let data;
            if (isDm) {
                data = await apiRequest({ path: `/chat/dm/${activeDm}?${params.toString()}`, token });
            } else {
                if (activeChannel != null) params.set("group_id", activeChannel);
                data = await apiRequest({ path: `/chat/messages?${params.toString()}`, token });
            }
            const items = Array.isArray(data) ? data : [];
            setMessages(items);
            setHasMore(items.length === 50);
            shouldStickToBottom.current = true;
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [token, activeChannel, activeDm, isDm]);

    useEffect(() => { load(); }, [load]);

    useEffect(() => {
        if (shouldStickToBottom.current && listRef.current) {
            listRef.current.scrollTop = listRef.current.scrollHeight;
        }
    }, [messages]);

    function onScroll() {
        const el = listRef.current;
        if (!el) return;
        shouldStickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    }

    async function loadMore() {
        if (!messages.length || loadingMore) return;
        setLoadingMore(true);
        try {
            const el = listRef.current;
            const prevHeight = el?.scrollHeight || 0;
            const params = new URLSearchParams({ limit: "50", before_id: String(messages[0].id) });
            let data;
            if (isDm) {
                data = await apiRequest({ path: `/chat/dm/${activeDm}?${params.toString()}`, token });
            } else {
                if (activeChannel != null) params.set("group_id", activeChannel);
                data = await apiRequest({ path: `/chat/messages?${params.toString()}`, token });
            }
            const older = Array.isArray(data) ? data : [];
            setHasMore(older.length === 50);
            setMessages(prev => [...older, ...prev]);
            requestAnimationFrame(() => {
                if (el) el.scrollTop = el.scrollHeight - prevHeight;
            });
        } catch {
            // не критично — просто не подгрузили
        } finally {
            setLoadingMore(false);
        }
    }

    // Живые обновления: событие приходит для ЛЮБОГО канала/диалога —
    // фильтруем по текущему открытому. ЛС отличаем по recipient_id !== null
    // (у сообщений общего/группового канала recipient_id всегда null).
    useEffect(() => {
        if (!wsEvent) return;
        const { event, data } = wsEvent;
        if (isDm) {
            const isThisDm = data?.recipient_id != null && (
                (data.user_id === activeDm && data.recipient_id === currentUserId) ||
                (data.user_id === currentUserId && data.recipient_id === activeDm)
            );
            if (!isThisDm) return;
        } else {
            const isGeneralMatch = (data?.recipient_id ?? null) == null && (data?.group_id ?? null) === (activeChannel ?? null);
            if (!isGeneralMatch) return;
        }
        if (event === "chat_message") {
            setMessages(prev => (prev.some(m => m.id === data.id) ? prev : [...prev, data]));
        } else if (event === "chat_message_deleted") {
            setMessages(prev => prev.filter(m => m.id !== data.id));
        }
    }, [wsEvent, activeChannel, activeDm, isDm, currentUserId]);

    // Подстраховка на случай проблем с доставкой WS (например, если сокет
    // незаметно отвалился): пока попап открыт, раз в 5 сек тихо подтягиваем
    // самые свежие сообщения канала/диалога и домешиваем недостающие (дедуп
    // по id, как и в WS-обработчике выше) — без сброса скролла и без "моргания".
    useEffect(() => {
        const interval = setInterval(async () => {
            try {
                const params = new URLSearchParams({ limit: "50" });
                let data;
                if (isDm) {
                    data = await apiRequest({ path: `/chat/dm/${activeDm}?${params.toString()}`, token });
                } else {
                    if (activeChannel != null) params.set("group_id", activeChannel);
                    data = await apiRequest({ path: `/chat/messages?${params.toString()}`, token });
                }
                if (!Array.isArray(data) || data.length === 0) return;
                setMessages(prev => {
                    const known = new Set(prev.map(m => m.id));
                    const fresh = data.filter(m => !known.has(m.id));
                    if (fresh.length === 0) return prev;
                    return [...prev, ...fresh].sort((a, b) => a.id - b.id);
                });
            } catch {
                // тихо игнорируем — это просто подстраховка, не основной путь
            }
        }, 5000);
        return () => clearInterval(interval);
    }, [token, activeChannel, activeDm, isDm]);

    async function send() {
        const content = draft.trim();
        if (!content || sending) return;
        setSending(true);
        setDraft("");
        try {
            const saved = isDm
                ? await apiRequest({ path: `/chat/dm/${activeDm}`, token, method: "POST", body: { content } })
                : await apiRequest({ path: "/chat/messages", token, method: "POST", body: { content, group_id: activeChannel } });
            shouldStickToBottom.current = true;
            // Добавляем сразу из ответа POST, не дожидаясь WS — надёжнее, чем
            // полагаться только на broadcast (задержки/потеря сети и т.п.).
            // Если следом всё же прилетит WS-событие на то же сообщение —
            // дедуп по id (см. эффект ниже) не даст задвоить.
            if (saved?.id) {
                setMessages(prev => (prev.some(m => m.id === saved.id) ? prev : [...prev, saved]));
            }
        } catch (err) {
            setError(err.message);
            setDraft(content);
        } finally {
            setSending(false);
        }
    }

    async function handleDelete(id) {
        try {
            await apiRequest({ path: `/chat/messages/${id}`, token, method: "DELETE" });
            setMessages(prev => prev.filter(m => m.id !== id));
        } catch (err) {
            alert(err.message);
        }
    }

    useEffect(() => {
        if (!dmPickerOpen) return;
        setPickerLoading(true);
        // ⚠️ size ограничен le=100 на бэкенде (см. PaginationParams) — запрос
        // с size=200 падал с 422, catch тихо оставлял pickerUsers пустым,
        // из-за чего поиск всегда показывал "никого не нашли".
        apiRequest({ path: "/users?page=1&size=100", token })
            .then(data => setPickerUsers(extractItems(data)))
            .catch(() => setPickerUsers([]))
            .finally(() => setPickerLoading(false));
    }, [dmPickerOpen, token]);

    function pickDmUser(u) {
        onNewDmConversation?.({ user_id: u.id, username: u.username, last_message: "", last_message_at: null });
        setActiveDm(u.id);
        setDmPickerOpen(false);
        setDmSearch("");
    }

    const filteredPickerUsers = pickerUsers.filter(u =>
        u.id !== currentUserId && (!dmSearch || (u.username || "").toLowerCase().includes(dmSearch.toLowerCase()))
    );

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
            <div style={{ borderBottom: "1px solid var(--border)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 12px 4px" }}>
                    <div ref={channelsRowRef} style={{ display: "flex", gap: 4, overflowX: "auto", flex: 1, minWidth: 0 }}>
                        {channels.map(c => (
                            <button
                                key={c.group_id ?? "general"}
                                className={`tab-btn${!isDm && (activeChannel ?? null) === (c.group_id ?? null) ? " active" : ""}`}
                                style={{ fontSize: 12, padding: "4px 10px", flexShrink: 0, whiteSpace: "nowrap" }}
                                onClick={() => { setActiveDm(null); setActiveChannel(c.group_id); }}
                            >
                                {c.group_id == null ? "💬" : "👥"} {c.name}
                            </button>
                        ))}
                    </div>
                    {onClose && (
                        <button className="btn btn-ghost btn-sm" onClick={onClose} style={{ flexShrink: 0 }}>✕</button>
                    )}
                </div>

                <div ref={dmRowRef} style={{ position: "relative", display: "flex", alignItems: "center", gap: 4, padding: "0 12px 8px", overflowX: "auto" }}>
                    {dmConversations.map(c => (
                        <button
                            key={c.user_id}
                            className={`tab-btn${isDm && activeDm === c.user_id ? " active" : ""}`}
                            style={{
                                fontSize: 12, padding: "4px 6px 4px 10px", flexShrink: 0,
                                whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 6,
                            }}
                            onClick={() => setActiveDm(c.user_id)}
                        >
                            <span>👤 {c.username}</span>
                            {onCloseDm && (
                                <span
                                    role="button"
                                    title="Закрыть диалог"
                                    onClick={(e) => { e.stopPropagation(); onCloseDm(c.user_id); }}
                                    style={{
                                        display: "inline-flex", alignItems: "center", justifyContent: "center",
                                        width: 16, height: 16, borderRadius: "50%",
                                        opacity: 0.6, fontSize: 11, lineHeight: 1,
                                    }}
                                    onMouseEnter={(e) => { e.currentTarget.style.opacity = 1; e.currentTarget.style.background = "rgba(255,255,255,0.15)"; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.opacity = 0.6; e.currentTarget.style.background = "transparent"; }}
                                >
                                    ✕
                                </span>
                            )}
                        </button>
                    ))}
                    {/* <button
                        className="btn btn-ghost btn-sm"
                        style={{ fontSize: 12, flexShrink: 0, whiteSpace: "nowrap" }}
                        onClick={() => setDmPickerOpen(o => !o)}
                    >
                        + Личное
                    </button> */}

                    {dmPickerOpen && (
                        <div style={{
                            position: "absolute", top: "100%", left: 12, zIndex: 20,
                            width: 220, maxHeight: 220, overflowY: "auto",
                            background: "var(--surface)", border: "1px solid var(--border)",
                            borderRadius: 8, padding: 8, boxShadow: "0 8px 24px rgba(0,0,0,0.25)",
                        }}>
                            {/* <input
                                className="input input-sm"
                                placeholder="Найти пользователя…"
                                value={dmSearch}
                                onChange={e => setDmSearch(e.target.value)}
                                autoFocus
                                style={{
                                    marginBottom: 6, width: "100%",
                                    background: "#2a3040",
                                    border: "1px solid rgba(255,255,255,0.18)",
                                }}
                            /> */}
                            {pickerLoading ? (
                                <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "4px 2px" }}>Загрузка…</div>
                            ) : filteredPickerUsers.length === 0 ? (
                                <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "4px 2px" }}>Никого не найдено</div>
                            ) : (
                                filteredPickerUsers.map(u => (
                                    <div
                                        key={u.id}
                                        onClick={() => pickDmUser(u)}
                                        style={{ padding: "6px 8px", cursor: "pointer", fontSize: 13, borderRadius: 6 }}
                                        onMouseEnter={e => { e.currentTarget.style.background = "var(--surface2)"; }}
                                        onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
                                    >
                                        {u.username}
                                    </div>
                                ))
                            )}
                        </div>
                    )}
                </div>
            </div>

            <div ref={listRef} onScroll={onScroll} style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 10, padding: "10px 12px" }}>
                {loading ? (
                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                ) : messages.length === 0 ? (
                    <div className="empty-state"><div className="empty-icon">{isDm ? "✉️" : "💬"}</div>
                        {isDm ? "Пока нет сообщений — напишите первым" : "Пока никто ничего не написал"}
                    </div>
                ) : (
                    <>
                        {hasMore && (
                            <button className="btn btn-ghost btn-sm" onClick={loadMore} disabled={loadingMore}
                                style={{ alignSelf: "center", marginBottom: 6 }}>
                                {loadingMore ? "Загрузка…" : "Загрузить более раннюю историю"}
                            </button>
                        )}
                        {messages.map(m => {
                            const isOwn = m.user_id === currentUserId;
                            return (
                                <div key={m.id} style={{ display: "flex", gap: 8, alignItems: "flex-start", flexDirection: isOwn ? "row-reverse" : "row" }}>
                                    <div style={{ cursor: "pointer" }} onClick={() => window.openUserProfile?.(m.user_id)}>
                                        <UserProfileAvatar userId={m.user_id} username={m.username} size={28} />
                                    </div>
                                    <div style={{ maxWidth: "72%" }}>
                                        <div style={{ display: "flex", gap: 6, alignItems: "baseline", flexDirection: isOwn ? "row-reverse" : "row" }}>
                                            <span
                                                style={{ fontSize: 12, fontWeight: 600, cursor: "pointer" }}
                                                onClick={() => window.openUserProfile?.(m.user_id)}
                                            >
                                                {m.username}
                                            </span>
                                            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                                                {new Date(m.created_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}
                                            </span>
                                        </div>
                                        <div style={{
                                            marginTop: 3, padding: "7px 11px", borderRadius: 12,
                                            background: isOwn ? "var(--accent)" : "var(--surface2)",
                                            color: isOwn ? "#fff" : "var(--text)",
                                            fontSize: 13, whiteSpace: "pre-wrap", wordBreak: "break-word",
                                        }}>
                                            {m.content}
                                        </div>
                                        {isOwn && (
                                            <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(m.id)}
                                                style={{ fontSize: 11, padding: "2px 6px", marginTop: 2, color: "var(--text-muted)" }}>
                                                удалить
                                            </button>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </>
                )}
            </div>

            {error && <div className="alert" style={{ margin: "0 12px 8px" }}>{error}</div>}

            <div style={{ display: "flex", gap: 8, padding: "10px 12px", borderTop: "1px solid var(--border)" }}>
                <input
                    className="input"
                    placeholder={isDm ? "Написать личное сообщение…" : "Написать сообщение…"}
                    value={draft}
                    onChange={e => setDraft(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                    style={{ marginBottom: 0, flex: 1 }}
                />
                <button className="btn btn-primary" onClick={send} disabled={sending || !draft.trim()}>
                    ➤
                </button>
            </div>
        </div>
    );
}

// ─── ChatBubble — плавающий перетаскиваемый кружок в углу экрана. Клик (не
// перетаскивание) открывает всплывающее окно с ChatPanel. Позиция и
// последний открытый канал запоминаются в localStorage. ───────────────────
