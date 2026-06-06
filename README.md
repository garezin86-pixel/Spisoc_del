# Spisok Del

Система управления задачами с REST API, Telegram-ботом и веб-интерфейсом.

## Стек

| Слой | Технология |
|---|---|
| Backend | FastAPI, SQLAlchemy (async), Alembic |
| База данных | PostgreSQL + asyncpg |
| Кэш | Redis (fastapi-cache2) |
| Telegram-бот | aiogram 3 |
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

## Docker

```bash
# Локальная разработка
docker compose -f docker-compose.dev.yml up

# Production
docker compose -f docker-compose.prod.yml up -d
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
