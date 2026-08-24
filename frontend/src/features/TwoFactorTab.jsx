import { useState, useEffect, useCallback, useRef } from "react";
import QRCode from "qrcode";
import { apiRequest } from "../api";

export function TwoFactorTab({ token }) {
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Состояние процесса настройки
    const [setupData, setSetupData] = useState(null); // { secret, otpauth_url }
    const [confirmCode, setConfirmCode] = useState("");
    const [confirming, setConfirming] = useState(false);
    const [recoveryCodes, setRecoveryCodes] = useState(null); // показываются один раз
    const [starting, setStarting] = useState(false);

    // Состояние отключения
    const [disablePassword, setDisablePassword] = useState("");
    const [disableCode, setDisableCode] = useState("");
    const [disabling, setDisabling] = useState(false);
    const [showDisableForm, setShowDisableForm] = useState(false);

    const canvasRef = useRef(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await apiRequest({ path: "/auth/2fa/status", token });
            setStatus(data);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => { load(); }, [load]);

    useEffect(() => {
        if (setupData?.otpauth_url && canvasRef.current) {
            QRCode.toCanvas(canvasRef.current, setupData.otpauth_url, { width: 220 }, () => { });
        }
    }, [setupData]);

    async function handleStartSetup() {
        setStarting(true);
        setError(null);
        try {
            const data = await apiRequest({ path: "/auth/2fa/setup", method: "POST", token });
            setSetupData(data);
            setRecoveryCodes(null);
        } catch (err) {
            setError(err.message);
        } finally {
            setStarting(false);
        }
    }

    async function handleConfirm(e) {
        e.preventDefault();
        setConfirming(true);
        setError(null);
        try {
            const data = await apiRequest({
                path: "/auth/2fa/confirm", method: "POST", token,
                body: { code: confirmCode.trim() },
            });
            setRecoveryCodes(data.recovery_codes);
            setSetupData(null);
            setConfirmCode("");
            await load();
        } catch (err) {
            setError(err.message);
        } finally {
            setConfirming(false);
        }
    }

    async function handleDisable(e) {
        e.preventDefault();
        setDisabling(true);
        setError(null);
        try {
            await apiRequest({
                path: "/auth/2fa/disable", method: "POST", token,
                body: { password: disablePassword, code: disableCode },
            });
            setShowDisableForm(false);
            setDisablePassword("");
            setDisableCode("");
            await load();
        } catch (err) {
            setError(err.message);
        } finally {
            setDisabling(false);
        }
    }

    return (
        <div className="card" style={{ marginTop: 0, maxWidth: 520 }}>
            <div className="section-header">
                <div>
                    <div className="section-title">🔒 Двухфакторная аутентификация</div>
                    <div className="section-sub">
                        Дополнительный код из приложения-аутентификатора (Google Authenticator, Authy и т.п.)
                        при каждом входе — даже если пароль утечёт, войти без телефона не получится.
                    </div>
                </div>
            </div>

            {error && <div className="alert" style={{ marginBottom: 12 }}>{error}</div>}

            {recoveryCodes && (
                <div className="alert" style={{
                    marginBottom: 16, borderColor: "#22c55e", background: "#22c55e11",
                    display: "flex", flexDirection: "column", gap: 8,
                }}>
                    <div>
                        <strong>2FA включена!</strong> Сохраните эти recovery-коды — каждый работает один раз
                        и пригодится, если телефон с аутентификатором потеряется. Больше они не покажутся.
                    </div>
                    <div style={{
                        display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6,
                        fontFamily: "monospace", fontSize: 14, background: "var(--surface2)",
                        padding: 12, borderRadius: 6,
                    }}>
                        {recoveryCodes.map(c => <div key={c}>{c}</div>)}
                    </div>
                    <button
                        className="btn btn-sm btn-primary" style={{ alignSelf: "flex-start" }}
                        onClick={() => navigator.clipboard.writeText(recoveryCodes.join("\n")).catch(() => { })}
                    >
                        Скопировать все
                    </button>
                </div>
            )}

            {loading ? (
                <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
            ) : status?.enabled ? (
                <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                        <span className="meta-chip" style={{ background: "#22c55e22", color: "#22c55e" }}>включена</span>
                    </div>
                    {!showDisableForm ? (
                        <button className="btn btn-sm" onClick={() => setShowDisableForm(true)}>Отключить 2FA</button>
                    ) : (
                        <form className="form" onSubmit={handleDisable}>
                            <div className="form-group">
                                <label className="form-label">Пароль</label>
                                <input type="password" value={disablePassword} onChange={e => setDisablePassword(e.target.value)} required />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Код из аутентификатора (или recovery-код)</label>
                                <input value={disableCode} onChange={e => setDisableCode(e.target.value)} required />
                            </div>
                            <div style={{ display: "flex", gap: 8 }}>
                                <button className="btn btn-danger btn-sm" type="submit" disabled={disabling}>
                                    {disabling ? "…" : "Подтвердить отключение"}
                                </button>
                                <button className="btn btn-ghost btn-sm" type="button" onClick={() => setShowDisableForm(false)}>
                                    Отмена
                                </button>
                            </div>
                        </form>
                    )}
                </div>
            ) : setupData ? (
                <div>
                    <div style={{ marginBottom: 12 }}>
                        Отсканируйте QR-код приложением-аутентификатором, затем введите 6-значный код:
                    </div>
                    <canvas ref={canvasRef} style={{ marginBottom: 12, background: "#fff", padding: 8, borderRadius: 8 }} />
                    <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>
                        Не получается отсканировать? Введите секрет вручную: <code>{setupData.secret}</code>
                    </div>
                    <form className="form" onSubmit={handleConfirm}>
                        <div className="form-group">
                            <input
                                value={confirmCode} onChange={e => setConfirmCode(e.target.value)}
                                placeholder="123456" inputMode="numeric" maxLength={6} required autoFocus
                            />
                        </div>
                        <div style={{ display: "flex", gap: 8 }}>
                            <button className="btn btn-primary btn-sm" type="submit" disabled={confirming}>
                                {confirming ? "…" : "Подтвердить и включить"}
                            </button>
                            <button className="btn btn-ghost btn-sm" type="button" onClick={() => setSetupData(null)}>
                                Отмена
                            </button>
                        </div>
                    </form>
                </div>
            ) : (
                <div>
                    <span className="meta-chip" style={{ marginBottom: 12, display: "inline-block" }}>отключена</span>
                    <div>
                        <button className="btn btn-primary btn-sm" onClick={handleStartSetup} disabled={starting}>
                            {starting ? "…" : "Настроить 2FA"}
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}


// ─── Tokens Tab ───────────────────────────────────────────
