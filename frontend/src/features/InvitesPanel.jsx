import { useState, useEffect, useCallback } from "react";
import { apiRequest } from "../api";
import { Icon } from "../components/Icon";
import { ICONS } from "../constants/icons";
import { formatTokenDate } from "../utils/token";

// Ссылка для веба: открывает экран регистрации с уже подставленным кодом.
export function webInviteLink(token, origin = window.location.origin) {
    return `${origin}/?invite=${encodeURIComponent(token)}`;
}

function CopyButton({ text, label }) {
    const [copied, setCopied] = useState(false);
    async function copy() {
        try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch { /* clipboard недоступен — человек скопирует вручную из поля */ }
    }
    return (
        <button type="button" className="btn btn-sm btn-ghost" onClick={copy}>
            {copied ? "✓ Скопировано" : label}
        </button>
    );
}

/**
 * Приглашения в компанию. Показывать только role="admin" (бэкенд всё равно
 * вернёт 403 остальным). Ссылка действует 7 дней, без лимита использований,
 * пока её не отозвали; присоединившийся получает роль «Участник».
 */
export function InvitesPanel({ token }) {
    const [invites, setInvites] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [creating, setCreating] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await apiRequest({ path: "/workspace/invites", token });
            setInvites(Array.isArray(data) ? data : []);
            setError(null);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => { load(); }, [load]);

    async function handleCreate() {
        setCreating(true);
        setError(null);
        try {
            await apiRequest({ path: "/workspace/invites", method: "POST", token });
            await load();
        } catch (err) {
            setError(err.message);
        } finally {
            setCreating(false);
        }
    }

    async function handleRevoke(id) {
        if (!window.confirm("Отозвать приглашение? Ссылка сразу перестанет работать (уже присоединившиеся сотрудники останутся).")) return;
        try {
            await apiRequest({ path: `/workspace/invites/${id}`, method: "DELETE", token });
            await load();
        } catch (err) {
            setError(err.message);
        }
    }

    return (
        <div className="card" style={{ marginBottom: 16 }}>
            <div className="section-header">
                <div>
                    <div className="section-title">✉️ Приглашения</div>
                    <div className="section-sub">
                        Отправьте ссылку сотруднику — он зарегистрируется сам и попадёт в вашу компанию.
                        Ссылка действует 7 дней, пока вы её не отзовёте.
                    </div>
                </div>
                <button className="btn btn-primary btn-sm" onClick={handleCreate} disabled={creating}>
                    <Icon d={ICONS.plus} /> {creating ? "Создание…" : "Новое приглашение"}
                </button>
            </div>

            {error && <div className="alert" style={{ marginBottom: 12 }}>{error}</div>}

            {loading ? (
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
            ) : invites.length === 0 ? (
                <div className="empty-state"><div className="empty-icon">✉️</div>Действующих приглашений нет</div>
            ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {invites.map(inv => {
                        const web = webInviteLink(inv.token);
                        return (
                            <div key={inv.id} data-testid="invite-row" style={{
                                padding: "10px 14px", borderRadius: 8,
                                background: "var(--surface2)", border: "1px solid var(--border)",
                            }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                                    <code style={{ flex: 1, minWidth: 0, fontSize: 12, wordBreak: "break-all" }}>{web}</code>
                                    <CopyButton text={web} label="Ссылка для веба" />
                                    {inv.bot_link && <CopyButton text={inv.bot_link} label="Ссылка для Telegram" />}
                                    <button className="btn btn-danger btn-sm" onClick={() => handleRevoke(inv.id)}>
                                        <Icon d={ICONS.trash} /> Отозвать
                                    </button>
                                </div>
                                <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
                                    создано {formatTokenDate(inv.created_at)} · действует до {formatTokenDate(inv.expires_at)}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
