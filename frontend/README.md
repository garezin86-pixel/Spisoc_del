# Frontend для Spisoc_del_api

React-приложение для управления задачами через API backend-а.

## Установка

1. Установите зависимости в папке `frontend`:
   ```bash
   cd /media/alex/C078CB2878CB1BD2/python/Spisoc_del_api/frontend
   npm install
   ```

2. Запустите backend:
   ```bash
   cd /media/alex/C078CB2878CB1BD2/python/Spisoc_del_api
   python run.py
   ```

3. Запустите React-приложение:
   ```bash
   cd frontend
   npm run dev
   ```

4. Откройте адрес, который покажет Vite, например `http://localhost:5173`.

## Что поддерживается

- вход через `/auth/login`
- просмотр задач пользователя
- создание новой задачи
- отметка задачи выполненной / не выполненной
- удаление задачи
- фильтрация по типу задачи и статусу
- простая статистика задач

## Настройка

Если backend работает на другом хосте или порту, создайте файл `frontend/.env` с одним значением:

```env
VITE_API_BASE=http://localhost:8000
```
