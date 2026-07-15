// frontend/public/sw.js
//
// Service Worker для веб-push уведомлений. Живёт отдельно от React-кода
// приложения — выполняется в отдельном потоке браузера, независимо от того,
// открыта ли вкладка с приложением. Именно это отличает push от WebSocket:
// WebSocket работает только пока вкладка открыта, push — даже если закрыта.

self.addEventListener("install", () => {
    // Активируем новую версию SW сразу, не дожидаясь закрытия всех вкладок
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
    let payload = { title: "Список дел", body: "У вас новое уведомление", url: "/" };

    if (event.data) {
        try {
            payload = { ...payload, ...event.data.json() };
        } catch {
            payload.body = event.data.text();
        }
    }

    event.waitUntil(
        self.registration.showNotification(payload.title, {
            body: payload.body,
            // ВАЖНО: в проекте пока нет файла иконки (frontend/public/icon-192.png).
            // Без icon браузер покажет системную иконку по умолчанию — не критично,
            // но для брендированного вида добавьте PNG 192x192 сюда и раскомментируйте:
            // icon: "/icon-192.png",
            // badge: "/icon-192.png",
            data: { url: payload.url || "/" },
            tag: payload.tag || undefined, // одинаковый tag схлопывает повторные уведомления той же группы
        })
    );
});

// Клик по уведомлению — фокусируем уже открытую вкладку приложения, если
// такая есть, иначе открываем новую на нужном пути.
self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const targetUrl = event.notification.data?.url || "/";

    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if (client.url.includes(self.location.origin) && "focus" in client) {
                    client.navigate(targetUrl);
                    return client.focus();
                }
            }
            return self.clients.openWindow(targetUrl);
        })
    );
});
