import { useEffect, useState } from "react";
import { apiRequest } from "../api";

// Тексты ошибок бэкенда приходят на английском (USER_ALREADY_EXISTS и т.п.) — здесь
// переводим только то, что человек реально может увидеть на этом экране.
function friendlyError(err) {
    if (err.status === 403) return "Создание новых компаний отключено на этом сервере. Попросите ссылку-приглашение у администратора вашей компании.";
    if (err.status === 429) return "Слишком много попыток. Подождите минуту и повторите.";
    if (err.message === "User already exists") return "Это имя уже занято в вашей компании. Добавьте, например, отчество или инициал.";
    return err.message;
}

/**
 * Экран регистрации: «Новая компания» (создатель становится админом) или
 * «По приглашению» (ссылка от админа компании).
 *
 * initialInvite — токен из ссылки ?invite=…, если человек пришёл по ней.
 * onRegistered(resp) — вызывается ПОСЛЕ того как человек увидел свой логин
 * и нажал «Продолжить»: логин нигде больше не показывается (вход идёт по
 * нему, а не по имени), поэтому пропустить этот шаг нельзя.
 */
export function RegisterScreen({ initialInvite, onRegistered, onBackToLogin }) {
    const [options, setOptions] = useState(null); // { company_registration_enabled }
    const [mode, setMode] = useState(initialInvite ? "invite" : null); // "company" | "invite"
    const [inviteToken, setInviteToken] = useState(initialInvite || "");
    const [inviteCompany, setInviteCompany] = useState(null); // название компании по действующему токену
    const [inviteError, setInviteError] = useState(null);
    const [error, setError] = useState(null);
    const [busy, setBusy] = useState(false);
    const [done, setDone] = useState(null); // { login, resp }

    useEffect(() => {
        let cancelled = false;
        apiRequest({ path: "/auth/registration-options" })
            .then(o => {
                if (cancelled) return;
                setOptions(o);
                setMode(m => m ?? (o.company_registration_enabled ? "company" : "invite"));
            })
            .catch(() => {
                if (cancelled) return;
                // Не смогли узнать — оставляем «по приглашению»: оно работает всегда.
                setOptions({ company_registration_enabled: false });
                setMode(m => m ?? "invite");
            });
        return () => { cancelled = true; };
    }, []);

    // Проверяем токен сразу, чтобы показать название компании или понятную ошибку
    // ДО того, как человек наберёт имя и пароль.
    useEffect(() => {
        const t = inviteToken.trim();
        setInviteCompany(null);
        setInviteError(null);
        if (mode !== "invite" || t.length < 8) return undefined;
        let cancelled = false;
        const timer = setTimeout(() => {
            apiRequest({ path: `/auth/invite/${encodeURIComponent(t)}` })
                .then(r => { if (!cancelled) setInviteCompany(r.company_name); })
                .catch(err => {
                    if (!cancelled) setInviteError(err.status === 400
                        ? "Приглашение недействительно или истекло. Попросите администратора прислать новую ссылку."
                        : friendlyError(err));
                });
        }, 300);
        return () => { cancelled = true; clearTimeout(timer); };
    }, [mode, inviteToken]);

    async function handleSubmit(e) {
        e.preventDefault();
        const fd = new FormData(e.target);
        const password = fd.get("password");
        if (password !== fd.get("password2")) { setError("Пароли не совпадают"); return; }
        const body = { username: String(fd.get("username")).trim(), password };
        if (mode === "company") body.company_name = String(fd.get("company_name")).trim();
        else body.invite_token = inviteToken.trim();

        setBusy(true);
        setError(null);
        try {
            const resp = await apiRequest({ path: "/auth/register", method: "POST", body });
            setDone({ login: resp.login, resp });
        } catch (err) {
            setError(friendlyError(err));
        } finally {
            setBusy(false);
        }
    }

    const logo = (
        <div className="login-logo">
            <div className="logo-mark">{import.meta.env.VITE_APP_LOGO}</div>
            <div>
                <div className="brand-name">{import.meta.env.VITE_APP_NAME}</div>
                <div className="brand-tagline">{import.meta.env.VITE_APP_DESCRIPTION}</div>
            </div>
        </div>
    );

    // ── Шаг 2: показать логин ───────────────────────────────────────────────
    if (done) {
        return (
            <div className="login-page">
                <div className="auth-card">
                    {logo}
                    <div className="auth-title">Готово!</div>
                    <div className="auth-sub">Аккаунт создан. Запишите логин — вход выполняется по нему, а не по имени.</div>
                    <div className="alert" style={{ borderColor: "#22c55e", background: "#22c55e11", color: "inherit", marginBottom: 16 }}>
                        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Ваш логин для входа</div>
                        <code data-testid="register-login" style={{ fontSize: 20, fontWeight: 700, wordBreak: "break-all" }}>{done.login}</code>
                    </div>
                    <button className="btn btn-primary" style={{ width: "100%" }} onClick={() => onRegistered(done.resp)}>
                        Продолжить
                    </button>
                </div>
            </div>
        );
    }

    const companyAllowed = options?.company_registration_enabled;
    const ready = mode !== null;

    return (
        <div className="login-page">
            <div className="auth-card">
                {logo}
                <div className="auth-title">Регистрация</div>
                <div className="auth-sub">
                    {mode === "invite" ? "Присоединитесь к компании по приглашению" : "Создайте компанию — вы станете её администратором"}
                </div>

                {ready && companyAllowed && (
                    <div className="tab-bar" style={{ marginBottom: 16 }}>
                        <button type="button" className={`tab-btn${mode === "company" ? " active" : ""}`}
                            onClick={() => { setMode("company"); setError(null); }}>
                            Новая компания
                        </button>
                        <button type="button" className={`tab-btn${mode === "invite" ? " active" : ""}`}
                            onClick={() => { setMode("invite"); setError(null); }}>
                            По приглашению
                        </button>
                    </div>
                )}

                {!ready ? (
                    <div className="empty-state"><div className="empty-icon">⏳</div>Загрузка…</div>
                ) : (
                    <form className="form" onSubmit={handleSubmit}>
                        {mode === "company" ? (
                            <div className="form-group">
                                <label className="form-label" htmlFor="reg-company">Название компании</label>
                                <input id="reg-company" name="company_name" placeholder="ООО Ромашка" required minLength={2} maxLength={200} />
                            </div>
                        ) : (
                            <div className="form-group">
                                <label className="form-label" htmlFor="reg-invite">Код приглашения</label>
                                <input
                                    id="reg-invite" name="invite_token" value={inviteToken} required minLength={8} maxLength={64}
                                    pattern="[A-Za-z0-9_\-]+" placeholder="Вставьте код из ссылки"
                                    onChange={e => setInviteToken(e.target.value)}
                                />
                                {inviteCompany && (
                                    <div data-testid="invite-company" style={{ fontSize: 13, marginTop: 6, color: "#22c55e" }}>
                                        ✓ Вас приглашает компания «{inviteCompany}»
                                    </div>
                                )}
                                {inviteError && <div className="alert" style={{ marginTop: 6 }}>{inviteError}</div>}
                            </div>
                        )}
                        <div className="form-group">
                            <label className="form-label" htmlFor="reg-username">Ваше имя</label>
                            <input id="reg-username" name="username" placeholder="Иван Петров" required minLength={3} maxLength={50}
                                pattern="[A-Za-zА-Яа-яЁё0-9_ ]+" title="Буквы, цифры, пробел и подчёркивание" />
                            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
                                Так вас увидят коллеги. Логин для входа будет создан автоматически.
                            </div>
                        </div>
                        <div className="form-group">
                            <label className="form-label" htmlFor="reg-password">Пароль</label>
                            <input id="reg-password" name="password" type="password" placeholder="не короче 6 символов" required minLength={6} maxLength={100} autoComplete="new-password" />
                        </div>
                        <div className="form-group">
                            <label className="form-label" htmlFor="reg-password2">Повторите пароль</label>
                            <input id="reg-password2" name="password2" type="password" required minLength={6} maxLength={100} autoComplete="new-password" />
                        </div>
                        <button type="submit" className="btn btn-primary" style={{ marginTop: 4 }}
                            disabled={busy || (mode === "invite" && !!inviteError)}>
                            {busy ? "Создание…" : mode === "company" ? "Создать компанию" : "Присоединиться"}
                        </button>
                        {error && <div className="alert">{error}</div>}
                    </form>
                )}

                <button type="button" className="btn btn-ghost btn-sm" style={{ marginTop: 12 }} onClick={onBackToLogin}>
                    ← Уже есть аккаунт? Войти
                </button>
            </div>
        </div>
    );
}
