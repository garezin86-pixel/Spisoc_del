import { useState, useEffect, useCallback } from "react";
import { apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { ICONS } from "../constants/icons";
import { WEBHOOK_EVENT_LABELS, WEBHOOK_EVENTS } from "../constants/webhooks";
import { formatTokenDate } from "../utils/token";

export function WebhooksTab({ token }) {
    const [webhooks, setWebhooks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [newUrl, setNewUrl] = useState("");
    const [newEvents, setNewEvents] = useState([]);
    const [creating, setCreating] = useState(false);
    const [justCreated, setJustCreated] = useState(null); // { id, secret } — показываем один раз
    const [copied, setCopied] = useState(false);
    const [testResults, setTestResults] = useState({}); // webhookId -> { delivered, status_code, error }
    const [testingId, setTestingId] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await apiRequest({ path: "/webhooks", token });
            setWebhooks(Array.isArray(data) ? data : []);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => { load(); }, [load]);

    function toggleNewEvent(ev) {
        setNewEvents(prev => prev.includes(ev) ? prev.filter(e => e !== ev) : [...prev, ev]);
    }

    async function handleCreate(e) {
        e.preventDefault();
        if (!newUrl.trim() || newEvents.length === 0) return;
        setCreating(true);
        setError(null);
        try {
            const created = await apiRequest({
                path: "/webhooks", method: "POST", token,
                body: { url: newUrl.trim(), events: newEvents },
            });
            setJustCreated({ id: created.id, secret: created.secret });
            setNewUrl("");
            setNewEvents([]);
            setCopied(false);
            await load();
        } catch (err) {
            setError(err.message);
        } finally {
            setCreating(false);
        }
    }

    async function handleDelete(id, url) {
        if (!window.confirm(`Удалить вебхук на «${url}»? События на этот URL больше не будут отправляться.`)) return;
        try {
            await apiRequest({ path: `/webhooks/${id}`, method: "DELETE", token });
            if (justCreated?.id === id) setJustCreated(null);
            await load();
        } catch (err) {
            setError(err.message);
        }
    }

    async function handleToggleActive(hook) {
        try {
            await apiRequest({ path: `/webhooks/${hook.id}`, method: "PATCH", token, body: { is_active: !hook.is_active } });
            await load();
        } catch (err) {
            setError(err.message);
        }
    }

    async function handleRotateSecret(id) {
        if (!window.confirm("Перевыпустить secret? Старый сразу перестанет проходить проверку подписи на вашей стороне.")) return;
        try {
            const rotated = await apiRequest({ path: `/webhooks/${id}/rotate-secret`, method: "POST", token });
            setJustCreated({ id: rotated.id, secret: rotated.secret });
            setCopied(false);
            await load();
        } catch (err) {
            setError(err.message);
        }
    }

    async function handleTest(id) {
        setTestingId(id);
        try {
            const result = await apiRequest({ path: `/webhooks/${id}/test`, method: "POST", token });
            setTestResults(prev => ({ ...prev, [id]: result }));
        } catch (err) {
            setTestResults(prev => ({ ...prev, [id]: { delivered: false, status_code: null, error: err.message } }));
        } finally {
            setTestingId(null);
        }
    }

    async function handleCopy() {
        try {
            await navigator.clipboard.writeText(justCreated.secret);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch { /* clipboard недоступен — пользователь скопирует вручную */ }
    }

    return (
        <div>
            <div className="card" style={{ marginTop: 0 }}>
                <div className="section-header">
                    <div>
                        <div className="section-title"><Icon d={ICONS.link} /> Исходящие вебхуки</div>
                        <div className="section-sub">
                            Противоположность API-токенам: не вы стучитесь к нам, а мы — POST-запросом —
                            уведомляем ваш URL, когда что-то произошло (задача готова, новый комментарий и т.д.).
                        </div>
                    </div>
                </div>

                {error && <div className="alert" style={{ marginBottom: 12 }}>{error}</div>}

                {justCreated && (
                    <div className="alert" style={{
                        marginBottom: 16, display: "flex", flexDirection: "column", gap: 8,
                        borderColor: "#22c55e", background: "#22c55e11",
                    }}>
                        <div>
                            <strong>Secret сохранён</strong> — покажем его только сейчас. Настройте проверку
                            подписи на своей стороне: заголовок <code>X-Webhook-Signature</code> содержит
                            <code> sha256=HMAC-SHA256(secret, raw_body)</code>.
                        </div>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                            <code style={{
                                flex: 1, padding: "8px 12px", background: "var(--surface2)",
                                borderRadius: 6, fontSize: 13, wordBreak: "break-all",
                            }}>
                                {justCreated.secret}
                            </code>
                            <button type="button" className="btn btn-sm btn-primary" onClick={handleCopy}>
                                {copied ? "✓ Скопировано" : "Скопировать"}
                            </button>
                        </div>
                        <button type="button" className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start" }}
                            onClick={() => setJustCreated(null)}>
                            Скрыть
                        </button>
                    </div>
                )}

                <form className="form" onSubmit={handleCreate} style={{ marginBottom: 20 }}>
                    <div className="form-group">
                        <label className="form-label">URL</label>
                        <input
                            value={newUrl}
                            onChange={e => setNewUrl(e.target.value)}
                            placeholder="https://example.com/webhooks/spisok-del"
                        />
                    </div>
                    <div className="form-group">
                        <label className="form-label">На какие события отправлять</label>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                            {WEBHOOK_EVENTS.map(ev => (
                                <label key={ev} style={{
                                    display: "flex", alignItems: "center", gap: 6,
                                    padding: "6px 10px", borderRadius: 8, cursor: "pointer",
                                    background: newEvents.includes(ev) ? "#22c55e22" : "var(--surface2)",
                                    border: `1px solid ${newEvents.includes(ev) ? "#22c55e" : "var(--border)"}`,
                                    fontSize: 13,
                                }}>
                                    <input type="checkbox" checked={newEvents.includes(ev)} onChange={() => toggleNewEvent(ev)} />
                                    {WEBHOOK_EVENT_LABELS[ev]}
                                </label>
                            ))}
                        </div>
                    </div>
                    <button className="btn btn-primary" type="submit" disabled={creating || !newUrl.trim() || newEvents.length === 0}>
                        <Icon d={ICONS.plus} /> {creating ? "Создание…" : "Создать вебхук"}
                    </button>
                </form>

                {loading ? (
                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                ) : webhooks.length === 0 ? (
                    <div className="empty-state"><div className="empty-icon">🔗</div>Вебхуков пока нет</div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        {webhooks.map(w => {
                            const result = testResults[w.id];
                            return (
                                <div key={w.id} style={{
                                    display: "flex", flexDirection: "column", gap: 8,
                                    padding: "10px 14px", borderRadius: 8,
                                    background: "var(--surface2)", border: "1px solid var(--border)",
                                }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 8, wordBreak: "break-all" }}>
                                                {w.url}
                                                <span className="meta-chip" style={
                                                    w.is_active
                                                        ? { background: "#22c55e22", color: "#22c55e" }
                                                        : { background: "#ef444422", color: "#ef4444" }
                                                }>
                                                    {w.is_active ? "включён" : "отключён"}
                                                </span>
                                                {w.failure_count >= 5 && w.is_active && (
                                                    <span className="meta-chip" style={{ background: "#f59e0b22", color: "#f59e0b" }}>
                                                        {w.failure_count} сбоев подряд
                                                    </span>
                                                )}
                                            </div>
                                            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4, display: "flex", flexWrap: "wrap", gap: 6 }}>
                                                {w.events.map(ev => (
                                                    <span key={ev} className="meta-chip">{WEBHOOK_EVENT_LABELS[ev] || ev}</span>
                                                ))}
                                            </div>
                                            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
                                                <code>{w.secret_prefix}…</code>
                                                {" · последняя доставка: "}
                                                {w.last_triggered_at
                                                    ? `${formatTokenDate(w.last_triggered_at)} (${w.last_status_code ?? "ошибка"})`
                                                    : "ни разу"}
                                            </div>
                                            {result && (
                                                <div style={{ fontSize: 12, marginTop: 4, color: result.delivered ? "#22c55e" : "#ef4444" }}>
                                                    Тест: {result.delivered ? `✓ доставлено (${result.status_code})` : `✗ ${result.error || result.status_code || "не доставлено"}`}
                                                </div>
                                            )}
                                        </div>
                                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                                            <button className="btn btn-sm" onClick={() => handleTest(w.id)} disabled={testingId === w.id}>
                                                {testingId === w.id ? "…" : "Тест"}
                                            </button>
                                            <button className="btn btn-sm" onClick={() => handleToggleActive(w)}>
                                                {w.is_active ? "Отключить" : "Включить"}
                                            </button>
                                            <button className="btn btn-sm" onClick={() => handleRotateSecret(w.id)}>
                                                Перевыпустить secret
                                            </button>
                                            <button className="btn btn-danger btn-sm" onClick={() => handleDelete(w.id, w.url)}>
                                                <Icon d={ICONS.trash} />
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
}


// ─── Dashboard Tab ────────────────────────────────────────
// ─── Push Notifications Card ───────────────────────────────
// Конвертирует VAPID public key из base64url в Uint8Array — именно в таком
// виде браузерный Push API ожидает applicationServerKey.
