# 🗺️ План развития проекта

> На основе анализа кода: FastAPI + SQLAdmin + SQLAlchemy + Aiogram + PostgreSQL

---

## 1. 🧱 Архитектура и структура кода

### 1.1 Dependency Injection через FastAPI
- Вынести `session_maker` в зависимости FastAPI (`Depends`)
- Убрать прямые вызовы `session_maker()` из admin-классов
- Изучить паттерн Unit of Work

### 1.2 Слоистая архитектура (уже частично есть)
- Закрепить разделение: `router → service → repository → model`
- Убедиться что нигде нет прямых запросов к БД вне репозиториев
- Добавить слой схем/DTO (Pydantic) между слоями

### 1.3 Dependency Inversion
- Сделать репозитории через абстрактные базовые классы (`ABC`)
- Это упростит тестирование (можно подменять mock-репозитории)

---

## 2. 🔐 Безопасность

### 2.1 Аутентификация и авторизация
- Добавить JWT-токены для API (если ещё нет)
- Роли пользователей: `admin`, `manager`, `user`
- Разграничение доступа к задачам по ролям (RBAC)
- Ограничить доступ к sqladmin по IP или двухфакторкой

### 2.2 Валидация входных данных
- Добавить Pydantic-схемы на все эндпоинты
- Валидация дедлайна: нельзя ставить дату в прошлом
- Санитизация комментариев (XSS-защита)

### 2.3 Rate Limiting
- Подключить `slowapi` для ограничения запросов
- Защита от брутфорса на авторизации

---

## 3. 🧪 Тестирование

### 3.1 Unit-тесты
- Тесты для сервисов (`notify_*`, бизнес-логика)
- Тесты для репозиториев с тестовой БД (SQLite in-memory)
- Использовать `pytest` + `pytest-asyncio`

### 3.2 Интеграционные тесты
- Тестировать API эндпоинты через `httpx.AsyncClient`
- Тесты на создание/редактирование задачи с проверкой уведомлений
- Фикстуры для тестовых пользователей и задач

### 3.3 Моки для Telegram-бота
- Мокировать `bot.send_message` в тестах
- Проверять что уведомления отправляются нужным пользователям

```python
# Пример структуры теста
async def test_notify_task_assigned(session, mock_bot):
    task = await create_test_task(session, user_id=1, author_id=2)
    await notify_task_assigned(session, task.id)
    mock_bot.send_message.assert_called_once()
```

---

## 4. ⚡ Производительность

### 4.1 Кэширование
- Подключить Redis для кэширования частых запросов
- Кэшировать список групп и пользователей (меняются редко)
- Использовать `fastapi-cache2` или `aiocache`

### 4.2 Оптимизация запросов
- Добавить индексы на часто фильтруемые поля: `user_id`, `group_id`, `is_done`, `deadline`
- Использовать `EXPLAIN ANALYZE` в PostgreSQL для проверки планов запросов
- Пагинация там, где её нет

### 4.3 Фоновые задачи
- Вынести отправку уведомлений в фоновые задачи (`BackgroundTasks` или Celery)
- Добавить напоминания о дедлайне (Celery Beat / APScheduler)

```python
# Напоминание за 24 часа до дедлайна
@scheduler.scheduled_job("interval", hours=1)
async def remind_deadlines():
    ...
```
---

## 5. 📬 Уведомления (расширение текущего модуля)

### 5.1 Новые типы уведомлений
- Напоминание о приближающемся дедлайне (за 24ч и за 1ч)
- Уведомление при просроченной задаче
- Еженедельная сводка задач пользователю
- Уведомление при назначении на группу

### 5.2 Настройки уведомлений
- Таблица `NotificationSettingsModel`: пользователь выбирает что получать
- Бот-команды для управления подписками: `/notifications on/off`

### 5.3 История уведомлений
- Таблица `NotificationLogModel`: когда, кому, что отправлено
- Отображение в sqladmin

---

## 6. 🤖 Telegram-бот (расширение)

### 6.1 Команды для пользователей
- `/mytasks` — список своих задач
- `/done <id>` — отметить задачу выполненной
- `/deadline <id>` — узнать дедлайн задачи

### 6.2 Инлайн-клавиатуры
- Кнопки "Выполнено / Отложить / Комментировать" прямо в уведомлении
- Deep linking: ссылка из уведомления ведёт в нужный раздел бота

### 6.3 FSM (конечные автоматы)
- Создание задачи через бот пошагово (Aiogram FSM)
- Добавление комментария через бот

---

## 7. 🗄️ База данных

### 7.1 Миграции
- Убедиться что используется Alembic
- Добавить `downgrade()` к каждой миграции
- Именовать миграции осмысленно

### 7.2 Мягкое удаление (Soft Delete)
- Добавить поле `deleted_at` к задачам/комментариям
- Вместо физического удаления — помечать удалёнными
- Фильтровать удалённые в запросах по умолчанию

### 7.3 Аудит изменений
- Таблица `AuditLogModel`: кто, когда, что изменил
- Автоматически заполнять через SQLAlchemy events или middleware

---

## 8. 📊 Мониторинг и логирование

### 8.1 Структурированные логи
- Подключить `structlog` вместо стандартного `logging`
- Логировать все действия в админке с указанием пользователя
- Уровни: DEBUG в dev, INFO/WARNING в prod

### 8.2 Метрики
- Подключить Prometheus + Grafana
- Метрики: количество задач, время ответа API, ошибки бота

### 8.3 Sentry
- Подключить Sentry для отслеживания исключений в продакшене
- Алерты на критические ошибки

---

## 9. 🐳 DevOps

### 9.1 Docker
- `Dockerfile` для приложения
- `docker-compose.yml`: app + postgres + redis + bot
- Отдельные конфиги для dev и prod

### 9.2 CI/CD
- GitHub Actions: запуск тестов на каждый push
- Автодеплой на сервер при merge в main
- Линтер (`ruff`) и форматтер (`black`) в пайплайне

### 9.3 Переменные окружения
- Все секреты только через `.env` + `pydantic-settings`
- Никаких хардкодов токенов/паролей в коде

---

## 10. 📚 Документация

### 10.1 API документация
- Заполнить `description`, `summary`, `tags` для всех эндпоинтов
- Добавить примеры запросов/ответов в Swagger

### 10.2 README
- Описание проекта, стек, как запустить локально
- Схема архитектуры (можно draw.io или mermaid)

### 10.3 Docstrings
- Добавить docstrings к сервисам и репозиториям
- Описывать не "что делает код", а "зачем и какие side-effects"

---

## 🎯 Рекомендуемый порядок внедрения

| Приоритет | Задача    |                Сложность |
|-----------|--------|-----------|
| 🔴 Высокий | Тесты (pytest + asyncio) |Средняя |
| 🔴 Высокий | Индексы в БД + Alembic | Низкая |
| 🔴 Высокий | Docker + .env |          Низкая |
| 🟡 Средний | JWT + роли |             Средняя |
| 🟡 Средний | Напоминания о дедлайнах | Средняя |
| 🟡 Средний | Структурированные логи | Низкая |
| 🟢 Низкий | Redis кэш |               Средняя |
| 🟢 Низкий | Prometheus + Grafana |    Высокая |
| 🟢 Низкий | CI/CD GitHub Actions |    Средняя |

# Spisok Del — оставшиеся улучшения

## 🔴 Критично — безопасность

- [ ] **Access token blocklist** — после logout access token живёт до истечения.
  Если нужна мгновенная блокировка — добавить Redis-set `blocklist:{jti}` с TTL = время жизни токена,
  проверять в `get_current_user`.

---

## 🟡 Важно — надёжность

- [ ] **Поле `description` в `update_task`** — не сохраняется при обновлении.
  В `TaskService.update_task` добавить блок:
  ```python
  if "description" in update_data:
      task.description = update_data["description"]
  ```

- [ ] **Health check `/health`** — Render не знает жив ли сервис.
  ```python
  @router.get("/health")
  async def health(session: SessionDep):
      await session.execute(text("SELECT 1"))
      return {"status": "ok", "db": "ok"}
  ```

- [ ] **Глобальный exception handler** — 500 ошибки возвращают traceback клиенту.
  ```python
  @app.exception_handler(Exception)
  async def unhandled_exception_handler(request, exc):
      logger.error("unhandled_exception", error=str(exc))
      return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервера"})
  ```
На Render после деплоя укажи Health Check Path в настройках сервиса: /health — тогда Render будет пинговать его каждые 30 секунд и перезапускать сервис если он не отвечает.

---

## 🔵 Улучшение — тесты

- [ ] **Интеграционные тесты роутеров** — unit-тесты есть, HTTP-тесты отсутствуют.
  Использовать `httpx.AsyncClient` + `pytest-asyncio` + тестовая БД в памяти (SQLite).

- [ ] **Coverage report** — добавить в `pytest.ini` / `pyproject.toml`:
  ```ini
  [tool.pytest.ini_options]
  addopts = "--cov=src --cov-report=term-missing"
  ```
  Установить: `pip install pytest-cov`

- [ ] **CI pipeline (GitHub Actions)** — тесты не запускаются автоматически.
  Файл `.github/workflows/ci.yml` с запуском `pytest` на каждый push/PR.

---


## 🟢 Оптимизация — база данных

- [ ] **N+1 в уведомлениях** — `notify_task_assigned` грузит связи в цикле.
  Заменить на `selectinload` / один запрос с `joinedload` для всех получателей.

- [ ] **Connection pool config** — нет явных настроек `pool_size`.
  В `create_async_engine` добавить:
  ```python
  pool_size=10, max_overflow=20, pool_pre_ping=True
  ```

- [ ] **Полнотекстовый поиск** — `ILIKE '%text%'` не использует индексы.
  Добавить через Alembic:
  ```python
  op.execute("CREATE INDEX ix_tasks_title_gin ON spisok_del USING gin(to_tsvector('russian', title))")
  ```
  Заменить `ILIKE` на `to_tsvector` + `to_tsquery`.

---

## 🟣 Качество кода — архитектура

- [ ] **Рефакторинг `update_task`** — поля обновляются вручную по одному.
  Заменить на универсальный цикл:
  ```python
  for field, value in update_data.items():
      if field != "deadline":
          setattr(task, field, value)
  ```

- [ ] **Уведомления в фон в `add_task`** — `await notify_task_assigned(task.id)`
  блокирует ответ. Передать `BackgroundTasks` из роутера в сервис или
  использовать `asyncio.create_task`.

- [ ] **Типизация сервисов** — часть методов без `return type`.
  Добавить аннотации для `TaskService`, `GroupService`.

---

## ⚪ Developer experience

- [ ] **`pre-commit` hooks** — ruff есть, но запускается вручную.
  ```yaml
  # .pre-commit-config.yaml
  repos:
    - repo: https://github.com/astral-sh/ruff-pre-commit
      rev: v0.4.0
      hooks:
        - id: ruff
          args: [--fix]
        - id: ruff-format
  ```

- [ ] **`Makefile`** — нет единого способа запустить команды.
  ```makefile
  run:       uvicorn src.main:app --reload
  test:      pytest -v
  lint:      ruff check src
  migrate:   alembic upgrade head
  ```

- [ ] **`GET /users/me`** — нет удобного способа получить данные текущего пользователя.
  ```python
  @router.get("/me", response_model=UserSchema)
  async def get_me(current_user: UserModel = Depends(get_current_user)):
      return current_user
  ```


  Хороший разбор, в целом согласен с приоритетами. Мой взгляд по каждому пункту:
Полностью согласен:
Проекты — самое важное. Сейчас задачи висят в воздухе, нет контекста. Проект = новая таблица + project_id в задачах. Это фундамент для всего остального.
Приоритеты — буквально один день работы. Enum в модели, колонка в БД, фильтр в API, иконка на фронте. Отдача огромная при минимальных затратах.
Dashboard — у тебя уже есть get_user_stats в TaskService, он считает total/done/pending. Осталось только сделать страницу на фронте.
Активность по задаче — у тебя уже есть audit_log в БД. Это буквально вывести существующие данные в красивый timeline на фронте.

Где не согласен:
Канбан — красиво, но drag & drop это много фронтенд-работы ради UX. Сначала сделай проекты и приоритеты, потом канбан будет органично встроен.
Вложения — требует S3/хранилища, это инфраструктурная задача. Для текущего этапа преждевременно.
Учёт времени — полезно, но только если есть реальные пользователи которые просят это. Не стоит строить без запроса.

Мой порядок для твоего проекта:

Приоритеты — быстро, сразу видно пользу
Dashboard — данные уже есть, нужен только UI
Проекты — фундамент для масштабирования
Активность по задаче — audit_log уже есть
Telegram-команды — у тебя сильный бот, докрутить до полноценного клиента логично

Что уже есть
Бот работает через клавиатуру — кнопки меню. Это хорошо для новичков, но неудобно для быстрых действий. Опытный пользователь хочет написать /done 42 и всё.

План: текстовые команды
Уровень 1 — быстрые действия (1-2 дня)
Это самое ценное — команды без диалога:
/done 42        — закрыть задачу #42
/undone 42      — снять отметку с задачи #42
/task 42        — показать задачу #42 с деталями
/del 42         — удалить задачу в корзину
Реализация простая — парсим аргумент из команды и вызываем уже существующие сервисы.
Уровень 2 — просмотр (1 день)
/my             — мои задачи (первые 10)
/today          — задачи на сегодня
/overdue        — просроченные
/stats          — моя статистика: всего/готово/просрочено
У тебя _filter_and_send и get_user_stats уже написаны — это буквально алиасы на существующие хендлеры.
Уровень 3 — создание (2-3 дня)
/new Название задачи                        — создать без дедлайна
/new Название задачи | 25.06.2025 18:00     — с дедлайном
/new Название | дедлайн | @username         — с назначением
Парсим строку по разделителю | и создаём задачу одной командой.
Уровень 4 — поиск и фильтры (1 день)
/find отчёт     — поиск задач по названию
/group 3        — задачи группы #3

Регистрация команд в меню бота
Сейчас в global_navigation.py только /start. Нужно добавить все команды чтобы они появились в подсказке Telegram:
pythonBotCommand(command="my", description="📋 Мои задачи"),
BotCommand(command="today", description="📅 На сегодня"),
BotCommand(command="overdue", description="⚠️ Просроченные"),
BotCommand(command="stats", description="📊 Моя статистика"),
BotCommand(command="done", description="✅ Закрыть задачу: /done 42"),
BotCommand(command="task", description="🔍 Показать задачу: /task 42"),
BotCommand(command="new", description="➕ Создать задачу"),
BotCommand(command="find", description="🔎 Найти задачу"),

Приоритет реализации

/done, /undone, /task — самые частые действия
/my, /today, /overdue — алиасы готовы
/stats — данные есть в get_user_stats
/new с парсингом строки
/find

С чего начнём — с быстрых действий или просмотра?


Канбан — после проектов сам напросится

Главная проблема
Сейчас у задачи два состояния: is_done = false → is_done = true. Канбан требует минимум 4 колонки. Значит нужно либо добавить поле status в БД, либо эмулировать колонки из существующих данных.

Подход B — Поле status (правильно, требует миграции)
Добавляем enum в БД:
pythonclass TaskStatus(str, Enum):
    backlog  = "backlog"   # Очередь
    todo     = "todo"      # Новые
    in_progress = "in_progress"  # В работе
    review   = "review"    # На проверке
    done     = "done"      # Готово
is_done становится производным: is_done = (status == "done").
Плюсы: полноценный канбан, любое количество колонок, легко расширять.

Минусы: миграция БД, нужно обновить все места где используется is_done.
Рекомендую Подход B — одна миграция сейчас сэкономит много боли потом.

Бэкенд — что нужно сделать
1. Миграция
sqlCREATE TYPE taskstatus AS ENUM ('backlog', 'todo', 'in_progress', 'review', 'done');
ALTER TABLE spisok_del ADD COLUMN status taskstatus DEFAULT 'todo';
-- Перенос данных:
UPDATE spisok_del SET status = 'done' WHERE is_done = true;
UPDATE spisok_del SET status = 'todo' WHERE is_done = false;
2. Новый эндпоинт PATCH для перемещения между колонками
PATCH /tasks/{task_id}/status
Body: { "status": "in_progress" }
Это отдельный эндпоинт от update_task — потому что перемещение карточки это атомарная операция, не частичное обновление.
3. Новый эндпоинт для канбан-вида
GET /tasks/kanban?project_id=1
Возвращает задачи сгруппированные по колонкам:
json{
  "backlog":     [...],
  "todo":        [...],
  "in_progress": [...],
  "review":      [...],
  "done":        [...]
}
Один запрос вместо пяти — важно для производительности.

Фронтенд — что нужно сделать
1. Новая вкладка «Канбан» в хедере (рядом с «Проекты»)
2. CSS для колонок — горизонтальный скролл:
css.kanban-board {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  min-height: 500px;
}
.kanban-column {
  min-width: 260px;
  max-width: 300px;
  flex-shrink: 0;
}
3. Drag & Drop — через браузерный draggable API (без библиотек):
jsx// При начале перетаскивания
onDragStart={e => e.dataTransfer.setData("taskId", task.id)}

// При отпускании в колонку
onDrop={e => moveTask(e.dataTransfer.getData("taskId"), column)}
При drop вызываем PATCH /tasks/{id}/status — оптимистичное обновление (сразу двигаем карточку, откатываем при ошибке).
4. Фильтр по проекту — селект вверху канбана:
Показывать: [Все задачи ▼]  [Мои задачи ▼]

Интеграция с проектами
Канбан без проектов показывает все твои задачи.

Канбан внутри проекта показывает только задачи этого проекта.
На странице проекта кнопка «Открыть канбан» — переходит на /kanban?project_id=5.

Порядок реализации

Миграция — добавить status, перенести данные из is_done
PATCH /tasks/{id}/status — эндпоинт смены статуса
GET /tasks/kanban — эндпоинт группировки
Базовый UI — 5 колонок, карточки без drag & drop
Drag & Drop — добавляем перетаскивание
Фильтр по проекту — связка с проектами

Шаги 1-4 дают рабочий канбан за 2-3 дня. Шаг 5 — ещё 1-2 дня.



План реализации: Шаблоны задач------------------------------------------------------------

Backend (FastAPI + PostgreSQL)
1. Миграция БД
Две новые таблицы:
sql-- Шаблон
task_templates
  id            SERIAL PRIMARY KEY
  title         VARCHAR(255) NOT NULL
  description   TEXT
  owner_id      INTEGER FK → users(id)
  created_at    TIMESTAMP

-- Задачи внутри шаблона
task_template_items
  id            SERIAL PRIMARY KEY
  template_id   INTEGER FK → task_templates(id) ON DELETE CASCADE
  title         VARCHAR(255) NOT NULL
  priority      priority_enum  -- переиспользуем существующий enum
  order_index   INTEGER
2. Pydantic схемы (schemas/template.py)
TemplateItemCreate   — title, priority, order_index
TemplateCreate       — title, description, items: list
TemplateResponse     — полный объект с items
3. CRUD функции (crud/template.py)
create_template(db, user_id, data)
get_templates(db, user_id)
get_template(db, template_id, user_id)
update_template(db, template_id, data)
delete_template(db, template_id, user_id)
apply_template(db, template_id, project_id, user_id)  ← главная функция
apply_template — клонирует все task_template_items в реальные задачи внутри выбранного проекта.
4. Роутер (routers/templates.py) с префиксом /api/templates
GET    /                      — список шаблонов пользователя
POST   /                      — создать шаблон
GET    /{id}                  — получить шаблон
PUT    /{id}                  — обновить шаблон
DELETE /{id}                  — удалить шаблон
POST   /{id}/apply            — применить шаблон → создать задачи в проекте

Frontend (React)
1. Новый таб в навигации рядом с Projects:
[ Задачи ] [ Канбан ] [ Проекты ] [ Шаблоны ]
2. Компонент TemplatesTab.jsx
Три состояния внутри одного компонента:
list     — список карточек шаблонов
create   — форма создания/редактирования
apply    — модалка выбора проекта для применения
3. Логика форм
Форма создания шаблона — динамический список задач:

добавить задачу (+ добавить)
удалить задачу (×)
drag-and-drop порядка (переиспользовать логику из KanbanTab)
выбор приоритета через существующий PRIORITY_COLORS

4. Применение шаблона
При нажатии "Использовать":

модалка с дропдауном существующих проектов
кнопка "Создать задачи" → POST /api/templates/{id}/apply
после успеха — редирект на вкладку Задачи с фильтром по этому проекту

5. API вызовы (все через apiRequest из api.js):
getTemplates()
createTemplate(data)
updateTemplate(id, data)
deleteTemplate(id)
applyTemplate(id, projectId)

Порядок реализации
День 1 — Backend
  ├── миграция (две таблицы)
  ├── схемы Pydantic
  ├── CRUD функции
  └── роутер + регистрация в main.py

День 2 — Frontend (список + создание)
  ├── TemplatesTab.jsx — список карточек
  ├── форма создания с динамическими задачами
  └── удаление шаблона

День 3 — Frontend (применение)
  ├── модалка выбора проекта
  ├── вызов apply endpoint
  └── UX polish

Что переиспользуем из существующего кода

priority_enum — не создаём заново, берём существующий
PRIORITY_COLORS — для визуала приоритетов в форме
apiRequest из api.js — все запросы через него
drag-and-drop логику из KanbanTab — для сортировки задач в шаблоне
стили карточек из ProjectsTab — карточки шаблонов выглядят похоже


Когда будешь готов начать — стартуем с миграции и backend'а. Всё расписано, можно брать и делать по шагам.

---------------------------------------------------------------------------------------------

О, это уже реально интересная фича. И она имеет смысл именно в Telegram — голосовые там отправляют постоянно.

Как это работает технически
Пользователь → голосовое сообщение
      ↓
Telegram Bot API → получает .ogg файл
      ↓
Whisper (OpenAI) → транскрибация в текст
      ↓
Gemini / GPT → парсит текст → JSON с задачей
      ↓
FastAPI → создаёт задачу в БД
      ↓
Бот отвечает: "✅ Задача создана: Созвон с клиентом [high]"

Что нужно
Транскрибация голоса — тут Gemini не поможет, нужен отдельный сервис:

Whisper API (OpenAI) — платный, но очень точный, $0.006 за минуту
Whisper локально — бесплатно, но нужны ресурсы сервера, на Render free tier не потянет
Groq Whisper — бесплатный тир, очень быстрый, хороший вариант

Парсинг в задачу — вот тут Gemini Flash бесплатно справится отлично:
Текст: "нужно позвонить Ивану по поводу договора, это срочно, лучше до пятницы"

→ { title: "Позвонить Ивану по договору", priority: "critical", deadline: "пятница" }

Реальная оценка
Это уже не просто "AI для галочки" — это фича которой нет у большинства таск-менеджеров в Telegram. Whisper распознаёт русский язык очень хорошо.
Groq — самый разумный старт: бесплатный тир, Whisper large-v3, быстрее реального времени.

Вариант 1 (мой фаворит)
STT → Groq  https://groq.com/
Parse → Gemini

Плюсы:

уже знаком с Gemini
Вариант 2 (ещё проще)
STT → Groq
Parse → Groq LLM

То есть вообще без Gemini.
