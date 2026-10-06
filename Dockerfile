# ── Этап 1: сборка React-интерфейса ──────────────────────────────────────────
# Те же Node 20 и команды (`npm ci`, `npm run build`), что в CI
# (.github/workflows/ci.yml). Debian-вариант (slim), а не alpine — тот же libc,
# что в CI. Этот этап в итоговый образ не попадает: из него берётся только dist.
FROM node:20-slim AS frontend-build
WORKDIR /frontend

# Сначала только манифесты: слой с node_modules кэшируется, пока зависимости не менялись.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# Брендинг Vite вшивает в бандл на этапе сборки (см. frontend/.env.example).
# Если frontend/.env нет, берём значения из .env.example: экран входа выводит
# VITE_APP_LOGO / VITE_APP_NAME / VITE_APP_DESCRIPTION без запасных значений, и
# без них логотип и название были бы пустыми. Свой frontend/.env имеет приоритет.
RUN { [ -f .env ] || cp .env.example .env; } && npm run build


# ── Этап 2: приложение (FastAPI + бот) ───────────────────────────────────────
# Базовый образ
FROM python:3.12.2-slim

# Рабочая папка
WORKDIR /app

# ffmpeg — нужен для конвертации TTS-аудио (Edge TTS отдаёт только MP3)
# в OGG/Opus, который Telegram принимает как голосовое сообщение.
# --no-install-recommends держит образ компактным (не тянет лишние пакеты).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем проект
COPY . .

# Собранный интерфейс: src/main.py отдаёт его из /app/frontend/dist (если папка есть).
# Копируется ДО chown ниже, чтобы файлы принадлежали appuser. Собранный на хосте
# frontend/dist в образ не попадает (.dockerignore) — берётся только этот, из этапа сборки.
COPY --from=frontend-build /frontend/dist ./frontend/dist

# Непривилегированный пользователь — без этого процесс (uvicorn, alembic,
# aiogram) работает от root. Если где-то в зависимостях найдётся RCE,
# атакующий сразу получит root внутри контейнера. storage/attachments
# создаём и передаём во владение заранее — приложение пишет туда вложения
# при локальном сторадже (см. ATTACHMENTS_STORAGE_PATH).
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/storage/attachments \
    && chown -R appuser:appuser /app
USER appuser

# Открываем порт
EXPOSE 8000

# Запуск приложения
#
# --proxy-headers --forwarded-allow-ips=... нужны, чтобы request.client.host
# (rate-limiter, ADMIN_ALLOWED_IPS, METRICS_ALLOWED_IPS) видел реального
# клиента, а не IP прокси. ВАЖНО: порт 8000 в docker-compose.yml публикуется
# на хост напрямую ("8000:8000") — если перед приложением нет
# nginx/Caddy/Cloudflare, доверять "*" нельзя: любой снаружи сможет
# подделать X-Forwarded-For и обойти rate-limit/IP-allowlist. Поэтому по
# умолчанию используется 127.0.0.1 — то же самое поведение, что и без этих
# флагов вообще (заголовкам никто не доверяет). Если поставишь reverse
# proxy — задай FORWARDED_ALLOW_IPS в .env.prod на его реальный IP/CIDR
# в docker-сети (не "*").
CMD ["sh", "-c", "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=${FORWARDED_ALLOW_IPS:-127.0.0.1}"]
