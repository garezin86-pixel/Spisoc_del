import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "../api";

const EXAMPLES = [
    "Покажи клиентов без контакта больше месяца",
    "Покажи воронку",
    "Какие у меня задачи на сегодня?",
];
const CLIENT_EXAMPLES = [
    "Создай задачу позвонить завтра в 10",
    "Запиши заметку: просили скидку 5%",
    "Покажи сделки этого клиента",
];

/**
 * Ассистент в вебе: те же инструменты, права и подтверждения, что и в Telegram-боте (POST /ai/message, /ai/confirm,
 * /ai/choose). Запись — только после «Да»; если найдено несколько вариантов — кнопки выбора. Если открыта карточка
 * клиента, она уходит в контексте: «создай задачу позвонить завтра» относится к этому клиенту.
 * onChanged вызывается после выполненной записи — интерфейс перечитывает данные.
 * onOpenClient(id) — ответ ассистента просит открыть карточку клиента («открой карточку клиента X»).
 */
export function AIPanel({ token, clientId, onChanged, onOpenClient }) {
    const [open, setOpen] = useState(false);
    const [messages, setMessages] = useState([]); // { role: "user" | "assistant" | "error", text }
    const [pending, setPending] = useState(null); // { id, kind, text, options }
    const [input, setInput] = useState("");
    const [busy, setBusy] = useState(false);
    const [clientName, setClientName] = useState("");
    const endRef = useRef(null);

    // название открытого клиента — для чипа «контекст»
    useEffect(() => {
        if (!clientId || !token) { setClientName(""); return undefined; }
        let alive = true;
        apiRequest({ path: `/clients/${clientId}`, token }).then(c => { if (alive) setClientName(c?.name ?? ""); }).catch(() => { if (alive) setClientName(""); });
        return () => { alive = false; };
    }, [clientId, token]);

    useEffect(() => { endRef.current?.scrollIntoView?.({ block: "end" }); }, [messages, pending, open]);

    const push = useCallback((role, text) => setMessages(m => [...m, { role, text }]), []);

    const handle = useCallback(async (request) => {
        setBusy(true);
        try {
            const reply = await request();
            (reply.messages ?? []).forEach(text => push("assistant", text));
            setPending(reply.pending ?? null);
            if (reply.changed) onChanged?.();
            // команды интерфейсу: «открой карточку клиента …» открывает её на экране (дальше она — контекст команд)
            (reply.actions ?? []).forEach(action => {
                if (action.type === "open_client") onOpenClient?.(action.client_id);
            });
        } catch (e) {
            setPending(null);
            push("error", e.message || "Не удалось выполнить команду");
        } finally {
            setBusy(false);
        }
    }, [onChanged, onOpenClient, push]);

    const send = useCallback((raw) => {
        const text = (raw ?? input).trim();
        if (!text || busy) return;
        setInput("");
        setPending(null); // новая команда отменяет неотвеченный вопрос (так же делает сервер)
        push("user", text);
        return handle(() => apiRequest({
            path: "/ai/message", method: "POST", token,
            body: { text, ...(clientId ? { context: { client_id: clientId } } : {}) },
        }));
    }, [input, busy, clientId, token, handle, push]);

    const confirm = yes => {
        if (!pending || busy) return;
        push("user", yes ? "Да" : "Нет");
        const id = pending.id;
        setPending(null);
        return handle(() => apiRequest({ path: "/ai/confirm", method: "POST", token, body: { pending_id: id, confirm: yes } }));
    };

    const choose = option => {
        if (!pending || busy) return;
        push("user", option.label);
        const id = pending.id;
        setPending(null);
        return handle(() => apiRequest({ path: "/ai/choose", method: "POST", token, body: { pending_id: id, option_id: option.id } }));
    };

    if (!open) {
        return (
            <button type="button" className="ai-fab" onClick={() => setOpen(true)} title="Ассистент" aria-label="Открыть ассистента">
                ✨
            </button>
        );
    }

    const examples = clientId ? [...CLIENT_EXAMPLES, ...EXAMPLES.slice(0, 1)] : EXAMPLES;
    return (
        <div className="ai-panel" role="dialog" aria-label="Ассистент">
            <div className="ai-panel-header">
                <div>
                    <div className="ai-panel-title">✨ Ассистент</div>
                    {clientId && clientName && <div className="ai-panel-context">Клиент: {clientName}</div>}
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                    {messages.length > 0 && <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setMessages([]); setPending(null); }}>Очистить</button>}
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(false)} aria-label="Закрыть">✕</button>
                </div>
            </div>

            <div className="ai-panel-body">
                {messages.length === 0 && (
                    <div className="ai-empty">
                        <div style={{ marginBottom: 8 }}>Скажите, что сделать — как в Telegram-боте. Изменения я сначала подтверждаю.</div>
                        {examples.map(example => (
                            <button key={example} type="button" className="ai-example" onClick={() => send(example)} disabled={busy}>{example}</button>
                        ))}
                    </div>
                )}
                {messages.map((m, i) => (
                    <div key={i} className={`ai-msg ai-msg-${m.role}`}>{m.text}</div>
                ))}
                {busy && <div className="ai-msg ai-msg-assistant ai-typing">…</div>}
                {pending && (
                    <div className="ai-pending">
                        <div className="ai-pending-text">❓ {pending.text}</div>
                        {pending.kind === "confirm" ? (
                            <div className="ai-pending-actions">
                                <button type="button" className="btn btn-primary btn-sm" onClick={() => confirm(true)} disabled={busy}>✅ Да</button>
                                <button type="button" className="btn btn-ghost btn-sm" onClick={() => confirm(false)} disabled={busy}>❌ Нет</button>
                            </div>
                        ) : (
                            <div className="ai-pending-options">
                                {pending.options.map(o => (
                                    <button key={o.id} type="button" className="ai-example" onClick={() => choose(o)} disabled={busy}>{o.label}</button>
                                ))}
                                <button type="button" className="btn btn-ghost btn-sm" onClick={() => confirm(false)} disabled={busy}>❌ Отмена</button>
                            </div>
                        )}
                    </div>
                )}
                <div ref={endRef} />
            </div>

            <form className="ai-panel-input" onSubmit={e => { e.preventDefault(); send(); }}>
                <input
                    value={input} onChange={e => setInput(e.target.value)} maxLength={1000} autoFocus
                    placeholder={clientId ? "Команда по этому клиенту…" : "Что сделать?"}
                />
                <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !input.trim()}>➤</button>
            </form>
        </div>
    );
}
