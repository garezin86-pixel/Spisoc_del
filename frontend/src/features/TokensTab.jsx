import { useState, useEffect, useCallback } from "react";
import { apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { ICONS } from "../constants/icons";
import { formatTokenDate } from "../utils/token";

export function TokensTab({ token }) {
    const [tokens, setTokens] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [newName, setNewName] = useState("");
    const [expiresInDays, setExpiresInDays] = useState("");
    const [scope, setScope] = useState("read_write");
    const [creating, setCreating] = useState(false);
    const [justCreated, setJustCreated] = useState(null); // { token, name } — показываем один раз
    const [copied, setCopied] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await apiRequest({ path: "/tokens", token });
            setTokens(Array.isArray(data) ? data : []);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => { load(); }, [load]);

    async function handleCreate(e) {
        e.preventDefault();
        if (!newName.trim()) return;
        setCreating(true);
        setError(null);
        try {
            const body = { name: newName.trim(), scope };
            if (expiresInDays) body.expires_in_days = Number(expiresInDays);
            const created = await apiRequest({ path: "/tokens", method: "POST", token, body });
            setJustCreated({ token: created.token, name: created.name, scope: created.scope });
            setNewName("");
            setExpiresInDays("");
            setScope("read_write");
            setCopied(false);
            await load();
        } catch (err) {
            setError(err.message);
        } finally {
            setCreating(false);
        }
    }

    async function handleRevoke(tokenId, name) {
        if (!window.confirm(`Отозвать токен «${name}»? Все интеграции, использующие его, сразу перестанут работать.`)) return;
        try {
            await apiRequest({ path: `/tokens/${tokenId}`, method: "DELETE", token });
            if (justCreated && tokens.find(t => t.id === tokenId)?.name === justCreated.name) {
                setJustCreated(null);
            }
            await load();
        } catch (err) {
            setError(err.message);
        }
    }

    async function handleCopy() {
        try {
            await navigator.clipboard.writeText(justCreated.token);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch { /* clipboard недоступен — пользователь скопирует вручную */ }
    }

    return (
        <div>
            <div className="card" style={{ marginTop: 0 }}>
                <div className="section-header">
                    <div>
                        <div className="section-title">🔑 Персональные API-токены</div>
                        <div className="section-sub">
                            Для скриптов и интеграций (Zapier-подобные сценарии), которым неудобно
                            перелогиниваться каждые 30 минут, как обычной веб-сессии.
                        </div>
                    </div>
                </div>

                {error && <div className="alert" style={{ marginBottom: 12 }}>{error}</div>}

                {justCreated && (
                    <div className="alert" style={{
                        marginBottom: 16, display: "flex", flexDirection: "column", gap: 8,
                        borderColor: "#22c55e", background: "#22c55e11",
                    }}>                        <div>
                            <strong>Токен «{justCreated.name}» создан</strong>
                            {" "}({justCreated.scope === "read_only" ? "read-only" : "read-write"}). Сохраните его сейчас —
                            повторно посмотреть не получится, хранится только хэш.
                        </div>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                            <code style={{
                                flex: 1, padding: "8px 12px", background: "var(--surface2)",
                                borderRadius: 6, fontSize: 13, wordBreak: "break-all",
                            }}>
                                {justCreated.token}
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
                    <div className="form-two-col">
                        <div className="form-group">
                            <label className="form-label">Название</label>
                            <input
                                value={newName}
                                onChange={e => setNewName(e.target.value)}
                                placeholder="Например: Zapier, личный скрипт…"
                            />
                        </div>
                        <div className="form-group">
                            <label className="form-label">Срок действия (дней)</label>
                            <input
                                type="number"
                                min="1"
                                max="3650"
                                value={expiresInDays}
                                onChange={e => setExpiresInDays(e.target.value)}
                                placeholder="Пусто — бессрочный"
                            />
                        </div>
                    </div>
                    <div className="form-group">
                        <label className="form-label">Уровень доступа</label>
                        <select value={scope} onChange={e => setScope(e.target.value)}>
                            <option value="read_write">Read-write — как обычная веб-сессия (создание, изменение, удаление)</option>
                            <option value="read_only">Read-only — только чтение (GET). Безопасно для разовых интеграций</option>
                        </select>
                    </div>
                    <button className="btn btn-primary" type="submit" disabled={creating || !newName.trim()}>
                        <Icon d={ICONS.plus} /> {creating ? "Создание…" : "Создать токен"}
                    </button>
                </form>

                {loading ? (
                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                ) : tokens.length === 0 ? (
                    <div className="empty-state"><div className="empty-icon">🔑</div>Токенов пока нет</div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        {tokens.map(t => {
                            const isExpired = t.expires_at && new Date(t.expires_at) < new Date();
                            return (
                                <div key={t.id} style={{
                                    display: "flex", alignItems: "center", gap: 12,
                                    padding: "10px 14px", borderRadius: 8,
                                    background: "var(--surface2)", border: "1px solid var(--border)",
                                }}>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 8 }}>
                                            {t.name}
                                            <span className="meta-chip" style={
                                                t.scope === "read_only"
                                                    ? { background: "#3b82f622", color: "#3b82f6" }
                                                    : { background: "#22c55e22", color: "#22c55e" }
                                            }>
                                                {t.scope === "read_only" ? "read-only" : "read-write"}
                                            </span>
                                            {isExpired && <span className="meta-chip" style={{ background: "#ef444422", color: "#ef4444" }}>Истёк</span>}
                                        </div>
                                        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                                            <code>{t.token_prefix}…</code>
                                            {" · создан "}{formatTokenDate(t.created_at)}
                                            {" · истекает: "}{t.expires_at ? formatTokenDate(t.expires_at) : "никогда"}
                                            {" · использован: "}{t.last_used_at ? formatTokenDate(t.last_used_at) : "ни разу"}
                                        </div>
                                    </div>
                                    <button className="btn btn-danger btn-sm" onClick={() => handleRevoke(t.id, t.name)}>
                                        <Icon d={ICONS.trash} /> Отозвать
                                    </button>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
}


// ─── Webhooks Tab ─────────────────────────────────────────
