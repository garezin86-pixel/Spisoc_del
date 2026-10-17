// frontend/src/constants/branding.js
//
// Название бренда для self-hosted клиентов с собственным именем/логотипом.
// Задаётся на этапе СБОРКИ (Vite инлайнит значение в бандл), не в рантайме —
// поэтому это frontend/.env, а не .env.prod бэкенда. Дефолт сохраняет
// текущий вид без изменений, если переменная не задана.
export const APP_NAME = import.meta.env.VITE_APP_NAME || "Spisoc";

// Буква на логотипе (див .logo-mark): VITE_APP_LOGO, а если не задана — первая буква имени.
export const APP_LOGO = import.meta.env.VITE_APP_LOGO || APP_NAME.charAt(0).toUpperCase();
export const APP_INITIAL = APP_LOGO;

// Подпись под названием. `??`, а не `||`: VITE_APP_DESCRIPTION= (пусто) — осознанно скрыть подпись.
export const APP_DESCRIPTION = import.meta.env.VITE_APP_DESCRIPTION ?? "Менеджер задач";
