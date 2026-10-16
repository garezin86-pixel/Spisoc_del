# AI-инструменты CRM и бот

Пакет `src/ai` — общий слой «фраза → действие в CRM». Бот (текст и голос) подключён к нему сейчас; веб-интерфейс и
API подключаются так же: создать `AIContext`, вызвать `AIAgent`, показать `Turn`.

## Как это устроено

```
фраза / голос ─► LLM (Groq) выбирает инструмент ─► реестр ─► сервис CRM ─► БД
                                                    │
                                   права, поиск клиента/сотрудника, подтверждение
```

| Модуль | Что делает |
|---|---|
| `src/ai/registry.py` | `Tool`, `ToolRegistry`: описание для LLM, роль-гейт `allowed`, `run`, `commit` |
| `src/ai/tools/crm.py` | `find_client`, `list_clients_without_contact`, `create_client`, `create_deal`, `move_deal_stage`, `list_deals`, `add_note` |
| `src/ai/tools/tasks.py` | `create_task` (можно с клиентом) и прежние команды: `get_tasks`, `update_task_status`, `update_task_priority`, `update_task_description`, `assign_task` |
| `src/ai/agent.py` | `AIAgent`: очередь вызовов, подтверждение, выбор из нескольких |
| `src/ai/resolve.py` | поиск клиента/сотрудника/стадии: регистр, ё/е, ООО/ТОВ, падежи («Петру» → «Петр») |
| `src/ai/llm.py` | единственное место, знающее про Groq |
| `src/bot/handlers/ai_assistant.py` | Telegram-адаптер: кнопки «Да/Нет», выбор, текстовые ответы «да/нет» |

В `src/ai` нет импортов `aiogram` и `src.bot` (проверяет `tests/test_ai_agent.py`).

## Правила

- **Чтение** (`find_client`, `list_*`, `get_tasks`) выполняется сразу.
- **Запись** — только после «да»: `run` возвращает `Confirm` с уже разрешёнными id, `commit` выполняется после
  подтверждения. Выполняется ровно то, что пользователь видел в вопросе.
- **Несколько подходящих записей** — `Choose`: бот показывает кнопки, инструмент запускается заново с выбранным id.
- **Несколько вызовов в одной фразе** идут по очереди: следующий готовится после решения по предыдущему. Отказ или
  сбой записи останавливает остальные вызовы. Не больше 5 вызовов за фразу.
- **Права — в коде, не в промпте:**
  1. `Tool.allowed(user)` — роль-гейт: недоступный инструмент не показывается LLM и не выполняется, даже если LLM его
     «придумала» (например, `create_client` у обычного сотрудника);
  2. предпроверки в `run` (ответственный за клиента/сделку) — отказ до вопроса «да/нет»;
  3. сервисы CRM проверяют права ещё раз при выполнении; `commit` повторно проверяет роль.
  `tests/test_ai_permissions.py` сверяет решения инструментов с поведением HTTP API по каждой роли.
- **Лимиты:** текст и голос используют один счётчик `check_voice_rate_limit` (`VOICE_RATE_LIMIT_COUNT` команд за
  `VOICE_RATE_LIMIT_WINDOW_SECONDS`), проверка — до вызова LLM. Текст длиннее 1000 символов не отправляется в LLM.

## Как добавить инструмент

```python
async def _run(ctx: AIContext, args: dict) -> Outcome:
    client = await resolve_client(ctx, "my_tool", args)      # ClientModel | Choose | Refuse
    if is_outcome(client):
        return client
    if not can_edit_client(client, ctx.user):                # предпроверка прав
        return Refuse("⛔ ...")
    return Confirm(text="Сделать X для «...»?", tool="my_tool", args={"client_id": client.id})   # запись
    # чтение: return Done("результат")

async def _commit(ctx: AIContext, args: dict) -> str:
    await ctx.deals.some_service_method(...)                 # только через сервисы CRM
    return "✅ Готово"

registry.register(Tool(name="my_tool", description="...", parameters={...}, run=_run, commit=_commit,
                       allowed=is_manager, hint="«фраза» — my_tool."))
```

Тексты результатов — обычный текст (без HTML): транспорт экранирует и оформляет их сам.

## Что в боте

- Любое текстовое сообщение в личном чате, которое не забрали меню, мастера (FSM) и команды, уходит в агента
  (роутер `ai_assistant` подключён последним).
- Ответ на вопрос о подтверждении: кнопки или текст «да» / «нет». Любой другой текст отменяет ожидающее действие и
  обрабатывается как новая команда.
- Нажимать кнопки может только тот, кто задал команду.

## Модель LLM

Модели Groq задаются в `.env`: `GROQ_LLM_MODEL` (по умолчанию `openai/gpt-oss-120b`) и `GROQ_STT_MODEL`
(`whisper-large-v3`). Groq регулярно отключает модели: `llama-3.3-70b-versatile` закрыта 16.08.2026 — запросы к ней
возвращают 404 `model_not_found`. Актуальные замены: https://console.groq.com/docs/deprecations. Для семейства GPT-OSS
код добавляет `reasoning_effort=low`, `include_reasoning=false` и увеличенный лимит токенов; для других моделей эти
параметры не передаются (если нужна особая настройка, правьте `_model_options` в `voice_ai.py`).
GPT-OSS не поддерживает параллельные вызовы инструментов: составная фраза может вернуть только первое действие.

## Ограничения

- `create_task(client)`: связь с клиентом — в названии и описании задачи («Клиент: … (#id)»), отдельного поля в
  задаче нет.
- HTTP-эндпоинта для веба пока нет: реестр и агент готовы, ожидающее действие (`Pending`) сериализуется в JSON.
- Качество выбора инструментов зависит от LLM; в тестах она подменена сценариями.
