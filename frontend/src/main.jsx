import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

// React.StrictMode убран — в dev он намеренно монтирует компоненты ДВАЖДЫ
// для поиска побочных эффектов. На мобильных это вызывает GPU-артефакты:
// CSS-анимации запускаются дважды, compositing-слои накладываются.
// Для отладки StrictMode можно вернуть локально, но не деплоить.
ReactDOM.createRoot(document.getElementById("root")).render(
    <App />
);
