import { useState } from "react";
import { apiRequest } from "../api";

export function ForceChangePasswordScreen({ token, onDone, onLogout }) {
    const [currentPassword, setCurrentPassword] = useState("");
    const [newPassword, setNewPassword] = useState("");
    const [newPassword2, setNewPassword2] = useState("");
    const [error, setError] = useState(null);
    const [saving, setSaving] = useState(false);

    async function handleSubmit(e) {
        e.preventDefault();
        if (newPassword !== newPassword2) {
            setError("Новые пароли не совпадают");
            return;
        }
        if (newPassword.length < 6) {
            setError("Пароль должен быть не короче 6 символов");
            return;
        }
        setSaving(true);
        setError(null);
        try {
            await apiRequest({
                path: "/users/me/password", method: "POST", token,
                body: { current_password: currentPassword, new_password: newPassword },
            });
            onDone();
        } catch (err) {
            setError(err.message);
        } finally {
            setSaving(false);
        }
    }

    return (
        <div className="login-page">
            <div className="auth-card">
                <div className="auth-title">Смените пароль</div>
                <div className="auth-sub">
                    Ваш текущий пароль был автоматически сгенерирован и прислан в Telegram —
                    задайте свой перед тем, как продолжить.
                </div>
                <form className="form" onSubmit={handleSubmit}>
                    <div className="form-group">
                        <label className="form-label">Текущий (временный) пароль</label>
                        <input type="password" value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} required />
                    </div>
                    <div className="form-group">
                        <label className="form-label">Новый пароль</label>
                        <input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} required minLength={6} />
                    </div>
                    <div className="form-group">
                        <label className="form-label">Повторите новый пароль</label>
                        <input type="password" value={newPassword2} onChange={e => setNewPassword2(e.target.value)} required minLength={6} />
                    </div>
                    <button type="submit" className="btn btn-primary" disabled={saving}>
                        {saving ? "…" : "Сменить пароль"}
                    </button>
                    {error && <div className="alert">{error}</div>}
                </form>
                <button className="btn btn-ghost btn-sm" style={{ marginTop: 8 }} onClick={onLogout}>
                    Выйти
                </button>
            </div>
        </div>
    );
}


// ─── Смена пароля (по желанию, не только принудительно) ────
