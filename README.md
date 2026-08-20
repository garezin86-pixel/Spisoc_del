# 📋 Spisok Del (Список Дел)

Полнофункциональная система управления задачами: REST API, Telegram-бот и веб-интерфейс в одном проекте. Разрабатывается как pet-проект, но с продакшн-подходом к архитектуре, тестам и CI.

![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> Замени `OWNER/REPO` в бейдже CI на свой `<пользователь>/<репозиторий>` после публикации.

## ✨ Возможности

**Задачи**
- Полный жизненный цикл задачи: `backlog → todo → in_progress → review → done`
- Канбан-доска с drag-and-drop
- Визуальный **календарь дедлайнов** (месячная сетка + компактный виджет в сайдбаре)
- Дедлайны, приоритеты, повторяющиеся задачи, зависимости между задачами (с обнаружением циклов)
- Чек-листы, комментарии, вложения (Cloudflare R2 или локальное хранилище)
- Шаблоны задач, массовые операции, фильтр-пресеты, полнотекстовый поиск
- Импорт/экспорт CSV, экспорт дедлайнов в iCal (подписка из Google Calendar / Outlook)
- Корзина с восстановлением, soft delete

**Совместная работа**
- Проекты и группы, ролевая модель (user / manager / admin)
- Командный чат: групповые каналы + личные сообщения
- Двусторонний мост чата с Telegram (сообщения из веба долетают в бота и обратно)
- Упоминания (@mentions) с уведомлениями
- Глобальная лента активности, дашборд с графиками (recharts)

**Telegram-бот**
- Полноценный клиент на aiogram 3: создание/редактирование задач, FSM-сценарии, роли
- Голосовые команды: распознавание речи (Groq Whisper) + LLM (Groq LLaMA 3.3-70B) с контекстной памятью в Redis
- Регистрация с автогенерацией логина/пароля и подтверждением у администратора

**Платформа и безопасность**
- JWT-аутентификация с refresh-токенами (ротация + защита от повторного использования)
- 2FA (TOTP) с резервными кодами
- Персональные токены доступа (PAT) с ограниченными правами
- Исходящие вебхуки с HMAC-подписью
- Web Push уведомления (VAPID), realtime через WebSocket
- Rate limiting, аудит-лог, admin-панель (SQLAdmin) с trash-view и soft delete
- Command Palette (Ctrl+K) для быстрой навигации

## Стек

| Слой | Технология |
|---|---|
| Backend | FastAPI, SQLAlchemy (async), Alembic |
| База данных | PostgreSQL + asyncpg |
| Кэш / realtime | Redis (fastapi-cache2, WebSocket-хаб) |
| Telegram-бот | aiogram 3 |
| Голос / LLM | Groq (Whisper STT, LLaMA 3.3-70B) |
| Планировщик | APScheduler |
| Фронтенд | React + Vite |
| Admin-панель | SQLAdmin |
| Мониторинг | Prometheus + Grafana |
| Логирование | structlog |
| Трекинг ошибок | Sentry |

## Архитектура

```
┌──────────────┐     ┌────────────────────────────────────────────┐
│   Browser    │────▶│              FastAPI App                   │
│  (React SPA) │     │                                            │
└──────────────┘     │  ┌──────────┐  ┌──────────┐  ┌────────┐  │
                     │  │ Routers  │  │ Services │  │ Repos  │  │
┌──────────────┐     │  └────┬─────┘  └────┬─────┘  └───┬────┘  │
│ Telegram Bot │────▶│       │              │             │       │
│  (aiogram 3) │     │       ▼              ▼             ▼       │
└──────────────┘     │  ┌──────────────────────────────────────┐ │
                     │  │         PostgreSQL (asyncpg)         │ │
┌──────────────┐     │  └──────────────────────────────────────┘ │
│  SQLAdmin    │────▶│                                            │
│  /admin      │     │  ┌──────────┐  ┌──────────────────────┐  │
└──────────────┘     │  │  Redis   │  │  APScheduler         │  │
                     │  │  Cache   │  │  (reminders, cron)   │  │
                     │  └──────────┘  └──────────────────────┘  │
                     └────────────────────────────────────────────┘
```

**Слои приложения:**

- **Routers** — только HTTP-прослойка: валидация входа, вызов сервиса, инвалидация кэша
- **Services** — бизнес-логика: права доступа, оркестрация, отправка уведомлений
- **Repositories** — SQL-запросы: построение и выполнение запросов, маппинг ORM
- **Models** — SQLAlchemy ORM-модели
- **Schemas** — Pydantic-схемы для запросов/ответов

## Быстрый запуск (локально)

### 1. Требования

- Python 3.12+
- PostgreSQL 14+
- Redis 6+
- Node.js 18+ (для фронтенда)

### 2. Клонирование и виртуальное окружение

```bash
git clone <repo-url>
cd spisok-del

python -m venv venv
source venv/bin/activate          # Linux/macOS
# venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 3. Переменные окружения

```bash
cp .env.example .env
```

Отредактируй `.env`:

```env
# JWT
SECRET_KEY=your-secret-key-min-32-chars
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# База данных
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/spisok_del_db

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Admin-панель
ADMIN_SECRET_KEY=your-admin-secret

# Telegram
BOT_TOKEN=your-bot-token-from-botfather
SUPER_ADMIN_TG_ID=your-telegram-id

# CORS (для деплоя)
FRONTEND_URL=https://your-domain.com

# Web Push (VAPID) — сгенерировать один раз:
# python scripts/generate_vapid_keys.py
VAPID_PRIVATE_KEY=
VAPID_PUBLIC_KEY=
VAPID_CLAIMS_EMAIL=you@example.com

# Groq — голосовые команды в Telegram-боте (STT + LLM). Необязательно:
# без ключа бот работает, просто без распознавания голоса.
GROQ_API_KEY=
```

### 4. База данных

```bash
# Создать БД
createdb spisok_del_db

# Применить миграции
alembic upgrade head
```

### 5. Создать первого admin-пользователя

```bash
python -c "
import asyncio
from src.admin.make_admin import make_admin
asyncio.run(make_admin('admin', 'your-password'))
"
```

Или через скрипт после запуска:

```bash
python src/admin/make_admin.py admin your-password
```

### 6. Запуск backend

```bash
python run.py
# или напрямую через uvicorn:
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

API доступен на `http://localhost:8000`
Swagger UI: `http://localhost:8000/docs`
Admin-панель: `http://localhost:8000/admin`

### 7. Запуск фронтенда

```bash
cd frontend
npm install
npm run dev
```

Фронтенд доступен на `http://localhost:5173`.

Если backend не на `localhost:8000`, создай `frontend/.env.local`:

```env
VITE_API_BASE=http://your-backend-host:8000
```

### 8. Запуск Telegram-бота

Бот запускается автоматически вместе с `run.py`. Для изолированного запуска:

```bash
python -m src.bot.runner
```

## Деплой на Render (production)

1. Создай Web Service из репозитория.
2. **Build command:** `pip install -r requirements.txt && cd frontend && npm install && npm run build`
3. **Start command:** `uvicorn src.main:app --host 0.0.0.0 --port $PORT`
4. Добавь все переменные из `.env.prod.example` в Environment Variables.
5. Redis — отдельный Render Redis instance, укажи `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`.

> ⚠️ На free-tier Render сервисы засыпают через 15 минут бездействия.
> Первый запрос после сна может занять ~30 секунд (cold start).

## Запуск тестов

```bash
pytest
# с подробным выводом:
pytest -v
# конкретный модуль:
pytest tests/test_unit_services.py -v
```

Тесты используют mock-репозитории — PostgreSQL и Redis для unit-тестов не нужны.
Интеграционным тестам (`test_integration_*.py`) нужна тестовая база — см. `.env.example` / `ci.yml`.

На момент публикации: **795 тестов, все зелёные**. Линт (`ruff check .`) и форматирование
(`ruff format --check .`) проходят без замечаний.

## Линт и форматирование

```bash
ruff check .            # линт
ruff format .            # автоформатирование
ruff format --check .   # проверка без изменений (используется в CI)
```

Pre-commit хуки настроены в `.pre-commit-config.yaml`.

## Docker

```bash
# Локальная разработка
docker compose -f docker-compose.dev.yml up

# Production
# --env-file обязателен: без него ${POSTGRES_USER:?...}, ${POSTGRES_PASSWORD:?...}
# и ${GRAFANA_ADMIN_PASSWORD:?...} не увидят значения из .env.prod (env_file:
# внутри сервисов не участвует в подстановке ${...} самого compose-файла) —
# деплой либо упадёт с ошибкой "variable is not set", либо (в старых версиях
# compose) тихо возьмёт дев-дефолты вроде postgres:postgres.
docker compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## API

Документация автогенерируется FastAPI:

- **Swagger UI:** `/docs`
- **ReDoc:** `/redoc`
- **OpenAPI JSON:** `/openapi.json`

Все эндпоинты требуют заголовок `Authorization: Bearer <token>` кроме `POST /api/auth/login`.

## Мониторинг

- Prometheus метрики: `/metrics`
- Grafana дашборд: `http://localhost:3000` (при запуске через docker-compose)

Настройка в `monitoring/prometheus.yml`.

## Структура проекта

```
src/
├── routers/       # HTTP-слой: валидация входа, вызов сервиса
├── services/       # Бизнес-логика, права доступа, оркестрация
├── repositories/    # SQL-запросы, маппинг ORM
├── models/          # SQLAlchemy ORM-модели
├── schemas/          # Pydantic-схемы запросов/ответов
├── bot/               # Telegram-бот (aiogram 3)
├── admin/             # SQLAdmin-панель
└── core/              # Конфиг, безопасность, метрики, кэш, лимитер

frontend/src/
├── App.jsx           # Основное SPA (один файл, все вкладки)
├── api.js            # HTTP-клиент, refresh-токены
└── AttachmentsPanel.jsx
```

## Лицензия

Проект распространяется под лицензией [MIT](LICENSE) — используй, форкай, дорабатывай свободно.

## Автор

Пет-проект, разрабатывается и поддерживается одним человеком. Issues и pull request'ы приветствуются.
