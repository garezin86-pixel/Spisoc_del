import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { APP_NAME } from "./constants/branding";
import "./styles.css";

// <title> в index.html — статичный дефолт "Spisoc": Vite-плейсхолдер
// %VITE_APP_NAME% тут не подходит — он не умеет fallback на дефолт, если
// переменная не задана (просто оставляет "%VITE_APP_NAME%" как текст).
// Поэтому title выставляется тут же, тем же способом, что и остальной
// брендинг (см. constants/branding.js) — единообразно с одним фолбэком.
document.title = APP_NAME;

// React.StrictMode убран — в dev он намеренно монтирует компоненты ДВАЖДЫ
// для поиска побочных эффектов. На мобильных это вызывает GPU-артефакты:
// CSS-анимации запускаются дважды, compositing-слои накладываются.
// Для отладки StrictMode можно вернуть локально, но не деплоить.
ReactDOM.createRoot(document.getElementById("root")).render(
    <App />
);
