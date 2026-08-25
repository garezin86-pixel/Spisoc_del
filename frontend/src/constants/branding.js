// frontend/src/constants/branding.js
//
// Название бренда для self-hosted клиентов с собственным именем/логотипом.
// Задаётся на этапе СБОРКИ (Vite инлайнит значение в бандл), не в рантайме —
// поэтому это frontend/.env, а не .env.prod бэкенда. Дефолт сохраняет
// текущий вид без изменений, если переменная не задана.
export const APP_NAME = import.meta.env.VITE_APP_NAME || "Spisoc";

// Буква на логотипе (див .logo-mark) — первая буква имени, тоже автоматически
// подстраивается под клиента вместо захардкоженной "S".
export const APP_INITIAL = APP_NAME.charAt(0).toUpperCase();
