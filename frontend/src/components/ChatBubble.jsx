import { useState, useEffect, useRef } from "react";
import { apiRequest } from "../api";
import { ChatPanel } from "../features/ChatPanel";

export function ChatBubble({ token, currentUserId, wsEvent }) {
    const [open, setOpen] = useState(false);
    const [pos, setPos] = useState(() => {
        try {
            const saved = JSON.parse(localStorage.getItem("spisoc_chat_bubble_pos") || "null");
            if (saved && typeof saved.x === "number" && typeof saved.y === "number") return saved;
        } catch { /* ignore */ }
        return { x: window.innerWidth - 76, y: window.innerHeight - 96 };
    });
    const [channels, setChannels] = useState([{ group_id: null, name: "Общий чат" }]);
    const [activeChannel, setActiveChannel] = useState(null);
    const [dmConversations, setDmConversations] = useState([]);
    const [activeDm, setActiveDm] = useState(null);
    const [unread, setUnread] = useState(0);

    const draggingRef = useRef(false);
    const movedRef = useRef(false);
    const dragStartRef = useRef({ x: 0, y: 0, posX: 0, posY: 0 });
    const bubbleRef = useRef(null);
    const openRef = useRef(open);
    openRef.current = open;
    const activeChannelRef = useRef(activeChannel);
    activeChannelRef.current = activeChannel;
    const activeDmRef = useRef(activeDm);
    activeDmRef.current = activeDm;

    // window.openDmWith — глобальный хук (по аналогии с window.openUserProfile),
    // чтобы открыть личный чат с конкретным пользователем из ЛЮБОГО места
    // приложения (например, кнопка "Написать" на странице "Команда"), не
    // прокидывая ChatBubble-состояние через пропсы во все компоненты.
    useEffect(() => {
        window.openDmWith = (userId, username) => {
            setDmConversations(prev =>
                prev.some(c => c.user_id === userId) ? prev : [{ user_id: userId, username, last_message: "", last_message_at: null }, ...prev]
            );
            setActiveDm(userId);
            setOpen(true);
            setUnread(0);
        };
        return () => { delete window.openDmWith; };
    }, []);

    useEffect(() => {
        apiRequest({ path: "/chat/channels", token }).then(data => {
            if (Array.isArray(data) && data.length) setChannels(data);
        }).catch(() => { /* тихо игнорируем — останется хотя бы общий канал */ });
    }, [token]);

    useEffect(() => {
        apiRequest({ path: "/chat/dm/conversations", token }).then(data => {
            if (Array.isArray(data)) setDmConversations(data);
        }).catch(() => { /* тихо игнорируем — список диалогов просто будет пуст */ });
    }, [token]);

    useEffect(() => {
        try { localStorage.setItem("spisoc_chat_bubble_pos", JSON.stringify(pos)); } catch { /* ignore */ }
    }, [pos]);

    // Бейдж непрочитанных для общего/группового канала — только пока попап
    // закрыт и только чужие сообщения. ЛС сюда не должны попадать (иначе
    // задвоятся со счётчиком ниже) — отличаем по recipient_id !== null.
    useEffect(() => {
        if (!wsEvent || wsEvent.event !== "chat_message") return;
        if (wsEvent.data?.recipient_id != null) return;
        if (wsEvent.data?.user_id === currentUserId) return;
        if (openRef.current && (wsEvent.data?.group_id ?? null) === (activeChannelRef.current ?? null)) return;
        setUnread(u => u + 1);
    }, [wsEvent, currentUserId]);

    // ЛС: обновляем список диалогов (новый диалог/поднимаем существующий
    // наверх) и считаем непрочитанные отдельно от общего канала.
    useEffect(() => {
        if (!wsEvent || wsEvent.event !== "chat_message") return;
        const { data } = wsEvent;
        if (data?.recipient_id == null) return;
        if (data.user_id !== currentUserId && data.recipient_id !== currentUserId) return;
        const partnerId = data.user_id === currentUserId ? data.recipient_id : data.user_id;
        setDmConversations(prev => {
            const existing = prev.find(c => c.user_id === partnerId);
            const updated = {
                user_id: partnerId,
                username: existing?.username ?? (data.user_id === currentUserId ? existing?.username : data.username) ?? `#${partnerId}`,
                last_message: data.content,
                last_message_at: data.created_at,
            };
            return [updated, ...prev.filter(c => c.user_id !== partnerId)];
        });
        if (data.user_id === currentUserId) return; // своё же сообщение — не считаем непрочитанным
        if (openRef.current && activeDmRef.current === partnerId) return;
        setUnread(u => u + 1);
    }, [wsEvent, currentUserId]);

    function clampPos(x, y) {
        return {
            x: Math.min(Math.max(8, x), window.innerWidth - 64),
            y: Math.min(Math.max(8, y), window.innerHeight - 64),
        };
    }

    function onPointerDown(e) {
        draggingRef.current = true;
        movedRef.current = false;
        dragStartRef.current = { x: e.clientX, y: e.clientY, posX: pos.x, posY: pos.y };
        bubbleRef.current?.setPointerCapture?.(e.pointerId);
    }
    function onPointerMove(e) {
        if (!draggingRef.current) return;
        const dx = e.clientX - dragStartRef.current.x;
        const dy = e.clientY - dragStartRef.current.y;
        if (Math.abs(dx) > 4 || Math.abs(dy) > 4) movedRef.current = true;
        setPos(clampPos(dragStartRef.current.posX + dx, dragStartRef.current.posY + dy));
    }
    function onPointerUp() {
        draggingRef.current = false;
        if (!movedRef.current) {
            setOpen(o => {
                const next = !o;
                if (next) setUnread(0);
                return next;
            });
        }
    }

    const openLeft = pos.x > window.innerWidth / 2;
    const openTop = pos.y > window.innerHeight / 2;
    const popupStyle = {
        position: "fixed",
        ...(openLeft ? { right: window.innerWidth - pos.x + 16 } : { left: pos.x }),
        ...(openTop ? { bottom: window.innerHeight - pos.y + 16 } : { top: pos.y + 60 }),
    };

    return (
        <>
            <div
                ref={bubbleRef}
                className="chat-bubble"
                style={{ left: pos.x, top: pos.y }}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                title="Командный чат"
            >
                💬
                {unread > 0 && <span className="notif-badge">{unread > 99 ? "99+" : unread}</span>}
            </div>
            {open && (
                <div className="chat-popup" style={popupStyle}>
                    <ChatPanel
                        token={token}
                        currentUserId={currentUserId}
                        channels={channels}
                        activeChannel={activeChannel}
                        setActiveChannel={setActiveChannel}
                        dmConversations={dmConversations}
                        activeDm={activeDm}
                        setActiveDm={setActiveDm}
                        onNewDmConversation={(conv) => setDmConversations(prev =>
                            prev.some(c => c.user_id === conv.user_id) ? prev : [conv, ...prev]
                        )}
                        onCloseDm={(userId) => {
                            setDmConversations(prev => prev.filter(c => c.user_id !== userId));
                            setActiveDm(prev => (prev === userId ? null : prev));
                        }}
                        wsEvent={wsEvent}
                        onClose={() => setOpen(false)}
                    />
                </div>
            )}
        </>
    );
}
