import { useState, useEffect } from "react";
import { apiRequest } from "../api";
import { urlBase64ToUint8Array } from "../utils/push";

export function PushNotificationsCard({ token }) {
    const [supported] = useState(() => "serviceWorker" in navigator && "PushManager" in window);
    const [subscribed, setSubscribed] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [checked, setChecked] = useState(false);

    useEffect(() => {
        if (!supported) { setChecked(true); return; }
        (async () => {
            try {
                const reg = await navigator.serviceWorker.getRegistration();
                const sub = reg ? await reg.pushManager.getSubscription() : null;
                setSubscribed(!!sub);
            } catch { /* ignore — просто считаем неподписанным */ }
            finally { setChecked(true); }
        })();
    }, [supported]);

    async function handleEnable() {
        setBusy(true);
        setError(null);
        try {
            if (Notification.permission === "denied") {
                throw new Error("Уведомления заблокированы в настройках браузера для этого сайта.");
            }
            const permission = await Notification.requestPermission();
            if (permission !== "granted") {
                throw new Error("Разрешение на уведомления не получено.");
            }

            const reg = await navigator.serviceWorker.register("/sw.js");
            await navigator.serviceWorker.ready;

            const { public_key } = await apiRequest({ path: "/push/vapid-public-key", token });
            if (!public_key) {
                throw new Error("Push не настроен на сервере (нет VAPID-ключа).");
            }

            const subscription = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(public_key),
            });

            await apiRequest({ path: "/push/subscribe", method: "POST", token, body: subscription.toJSON() });
            setSubscribed(true);
        } catch (err) {
            setError(err.message);
        } finally {
            setBusy(false);
        }
    }

    async function handleDisable() {
        setBusy(true);
        setError(null);
        try {
            const reg = await navigator.serviceWorker.getRegistration();
            const sub = reg ? await reg.pushManager.getSubscription() : null;
            if (sub) {
                await apiRequest({ path: "/push/unsubscribe", method: "POST", token, body: { endpoint: sub.endpoint } });
                await sub.unsubscribe();
            }
            setSubscribed(false);
        } catch (err) {
            setError(err.message);
        } finally {
            setBusy(false);
        }
    }

    if (!supported) {
        return null; // старые браузеры / iOS Safari < 16.4 — молча не показываем блок
    }

    if (!checked) return null; // не мигаем состоянием, пока не проверили реальную подписку

    return (
        <div className="card">
            <div className="section-header">
                <div>
                    <div className="section-title">🔔 Push-уведомления в браузере</div>
                    <div className="section-sub">
                        Работает даже если вкладка закрыта — дублирует часть уведомлений Telegram-бота
                        для тех, кто не хочет держать Telegram открытым.
                    </div>
                </div>
                <button
                    className={`btn btn-sm ${subscribed ? "btn-ghost" : "btn-primary"}`}
                    onClick={subscribed ? handleDisable : handleEnable}
                    disabled={busy}
                >
                    {busy ? "…" : subscribed ? "Выключить" : "Включить"}
                </button>
            </div>
            {error && <div className="alert">{error}</div>}
        </div>
    );
}

// ─── StatsDonut — маленький пончиковый график для личной статистики ──────
