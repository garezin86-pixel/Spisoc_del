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

# Открываем порт
EXPOSE 8000

# Запуск приложения
CMD ["sh", "-c", "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port 8000"]
