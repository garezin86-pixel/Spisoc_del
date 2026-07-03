import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
    plugins: [react()],
    server: {
        proxy: {
            "/api": {
                target: "http://localhost:8000",
                changeOrigin: true,
            },
            // Локальное хранилище вложений — download-эндпоинт отдаёт
            // 302-редирект на относительный /attachments-storage/..., и без
            // этого правила Vite ловит его как неизвестный путь и отдаёт
            // index.html вместо файла (SPA fallback).
            "/attachments-storage": {
                target: "http://localhost:8000",
                changeOrigin: true,
            },
        },
    },
});
