import { useState } from "react";
import { apiRequest } from "../api";

export function ChangePasswordCard({ token }) {
    const [currentPassword, setCurrentPassword] = useState("");
    const [newPassword, setNewPassword] = useState("");
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    const [success, setSuccess] = useState(false);

    async function handleSubmit(e) {
        e.preventDefault();
        setSaving(true);
        setError(null);
        setSuccess(false);
        try {
            await apiRequest({
                path: "/users/me/password", method: "POST", token,
                body: { current_password: currentPassword, new_password: newPassword },
            });
            setSuccess(true);
            setCurrentPassword("");
            setNewPassword("");
        } catch (err) {
            setError(err.message);
        } finally {
            setSaving(false);
        }
    }

    return (
        <div className="card" style={{ maxWidth: 520 }}>
            <div className="section-header">
                <div className="section-title">🔑 Сменить пароль</div>
            </div>
            {success && <div className="alert" style={{ borderColor: "#22c55e", background: "#22c55e11", marginBottom: 12 }}>Пароль изменён</div>}
            {error && <div className="alert" style={{ marginBottom: 12 }}>{error}</div>}
            <form className="form" onSubmit={handleSubmit}>
                <div className="form-group">
                    <label className="form-label">Текущий пароль</label>
                    <input type="password" value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} required />
                </div>
                <div className="form-group">
                    <label className="form-label">Новый пароль</label>
                    <input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} required minLength={6} />
                </div>
                <button className="btn btn-primary btn-sm" type="submit" disabled={saving}>
                    {saving ? "…" : "Сменить"}
                </button>
            </form>
        </div>
    );
}


// ─── Two-Factor Auth Tab ──────────────────────────────────
