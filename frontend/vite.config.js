import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// В Docker (Codespace) бэкенд живёт в отдельном контейнере "app", поэтому
// "localhost" изнутри контейнера frontend указывает сам на себя, а не на
// бэкенд. Задаём target через переменную окружения VITE_API_PROXY_TARGET
// (прокидывается из docker-compose.codespace.yml), а для локальной
// Windows-разработки (run2.py, всё в одной ОС) оставляем дефолт localhost.
const API_PROXY_TARGET = process.env.VITE_API_PROXY_TARGET || "http://localhost:8000";

export default defineConfig({
    plugins: [react()],
    server: {
        proxy: {
            "/api": {
                target: API_PROXY_TARGET,
                changeOrigin: true,
                ws: true, // без этого /api/ws не апгрейдится до WebSocket — handshake виснет по таймауту
            },
            // SQLAdmin живёт на бэкенде. Ссылка "Админка" в меню относительная ("/admin/"),
            // поэтому в разработке проксируем её туда же. changeOrigin НЕ включаем: админка
            // строит абсолютные URL редиректов из заголовка Host, и с исходным Host они
            // остаются на адресе Vite, а не уводят на :8000.
            "/admin": {
                target: API_PROXY_TARGET,
            },
            // Локальное хранилище вложений — download-эндпоинт отдаёт
            // 302-редирект на относительный /attachments-storage/..., и без
            // этого правила Vite ловит его как неизвестный путь и отдаёт
            // index.html вместо файла (SPA fallback).
            "/attachments-storage": {
                target: API_PROXY_TARGET,
                changeOrigin: true,
            },
        },
    },
});
