# Spisoc_del_api

Простой проект API с Telegram-ботом, админкой и PostgreSQL/SQLAlchemy.

## Быстрый запуск

```bash
python -m venv venv_linux
source venv_linux/bin/activate
pip install -r requirements.txt
```

## Переменные окружения

Создай файл `.env` рядом с `run.py` и укажи:

- `SECRET_KEY`
- `ALGORITHM` (например, `HS256`)
- `ACCESS_TOKEN_EXPIRE_MINUTES` (например, `30`)
- `DATABASE_URL`
- `ADMIN_SECRET_KEY`
- `BOT_TOKEN`

## Запуск

```bash
python run.py
```

## Тесты

```bash
python -m pip install pytest
pytest
```

## Фронтенд

В папке `frontend/` создан React-интерфейс для управления задачами и авторизации через API.

Запуск:

```bash
cd frontend
npm install
npm run dev
```

Откройте адрес, который покажет Vite (обычно `http://localhost:5173`).

Если backend работает не на `http://localhost:8000`, то создайте `frontend/.env` и установите:

```env
VITE_API_BASE=http://localhost:8000
```
