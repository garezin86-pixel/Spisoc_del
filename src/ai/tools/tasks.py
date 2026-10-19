# src/ai/tools/tasks.py
"""Инструменты задач: create_task (с привязкой к клиенту) и прежние голосовые команды по задачам.

Всё идёт через TaskService (права, уведомления, повторяющиеся задачи, блокирующие зависимости), а не прямой записью
в БД, как раньше делал голосовой обработчик. Запись — только после подтверждения.
"""

from typing import Any

from sqlalchemy import and_, func, or_, select

from src.ai.context import AIContext
from src.ai.registry import Tool, ToolRegistry
from src.ai.resolve import find_users, options_of
from src.ai.tools.common import clean_args, is_outcome, parse_local_deadline, resolve_client, short
from src.ai.types import Choose, Confirm, Done, Outcome, Refuse
from src.models.enums import TaskPriority, TaskStatus
from src.models.task import SpisokModel
from src.models.user import UserModel
from src.schemas.task import SpisokAddSchema, SpisokUpdate
from src.services.permissions import can_edit_task

PRIORITY_EMOJI = {"low": "⚪", "medium": "🔵", "high": "🟠", "critical": "🔴"}
PRIORITY_LABEL = {"low": "Низкий", "medium": "Средний", "high": "Высокий", "critical": "Критический"}
STATUS_LABEL = {
    "todo": "📋 Новая",
    "in_progress": "⚙️ В работе",
    "review": "👁 На проверке",
    "done": "✅ Выполнена",
    "backlog": "📥 В очереди",
}
_PRIORITIES = [p.value for p in TaskPriority]
_STATUSES = ["todo", "in_progress", "review", "done", "backlog"]


# ── исполнитель ──────────────────────────────────────────────────────────────
async def _resolve_assignee(
    ctx: AIContext, tool: str, args: dict[str, Any], key: str = "assignee_username"
) -> UserModel | Outcome:
    """Исполнитель: UserModel (в т.ч. сам пользователь, если не назван) либо Outcome (не найден / выберите)."""
    if args.get("_assignee_id"):
        user = await ctx.users.get_by_id(int(args["_assignee_id"]))
        return user or Refuse("🔍 Сотрудник не найден.")
    query = str(args.get(key) or "").strip()
    if not query:
        return ctx.user
    found = await find_users(ctx, query)
    if not found:
        return Refuse(f"🔍 Сотрудник «{query}» не найден.")
    if len(found) == 1:
        return found[0]
    return Choose(
        prompt=f"Найдено несколько сотрудников по запросу «{query}». Кому поручить?",
        tool=tool,
        param="_assignee_id",
        options=options_of(found, lambda u: f"@{u.username}" + (f" · {u.position}" if u.position else "")),
        args=clean_args(args) | ({"_client_id": args["_client_id"]} if args.get("_client_id") else {}),
    )


# ── create_task ──────────────────────────────────────────────────────────────
async def _create_task_run(ctx: AIContext, args: dict[str, Any]):
    title = str(args.get("title") or "").strip()
    if not title:
        return Refuse("Что за задача? Назовите её.")
    assignee = await _resolve_assignee(ctx, "create_task", args)
    if is_outcome(assignee):
        return assignee

    client = None
    if args.get("client") or args.get("_client_id"):
        client = await resolve_client(ctx, "create_task", {**args, **({"_assignee_id": assignee.id})})
        if is_outcome(client):
            if isinstance(client, Choose):  # после выбора клиента исполнитель уже известен — не спрашивать заново
                client.args = {**client.args, "_assignee_id": assignee.id}
            return client

    try:
        deadline = parse_local_deadline(ctx, args.get("deadline"), args.get("deadline_time"))
    except ValueError as exc:
        return Refuse(f"❌ {exc}")
    if deadline is not None and deadline < ctx.now():
        return Refuse(f"❌ Срок {deadline.strftime('%d.%m %H:%M')} уже прошёл — назовите время в будущем.")
    priority = args.get("priority") if args.get("priority") in _PRIORITIES else "medium"

    description = str(args.get("description") or "").strip()
    title = title[:200]
    client_id = client.id if client is not None else None
    SpisokAddSchema(
        title=title, description=description or None, deadline=deadline, user_id=assignee.id, client_id=client_id
    )  # проверка до вопроса «да/нет»

    who = "для вас" if assignee.id == ctx.user.id else f"для @{assignee.username}"
    when = f", срок {deadline.astimezone(ctx.tz).strftime('%d.%m %H:%M')}" if deadline else ""
    about = f", клиент «{client.name}»" if client is not None else ""
    resolved = {
        "title": title,
        "description": description or None,
        "priority": priority,
        "deadline": deadline.isoformat() if deadline else None,
        "assignee_id": assignee.id,
        "client_id": client_id,
        "client_name": client.name if client is not None else None,
    }
    text = f"Создать задачу «{title}» {who}{when}{about}?"
    return Confirm(text=text, tool="create_task", args=resolved)


async def _create_task_commit(ctx: AIContext, args: dict[str, Any]) -> str:
    from datetime import datetime

    deadline = datetime.fromisoformat(args["deadline"]) if args.get("deadline") else None
    task = await ctx.tasks.add_task(
        SpisokAddSchema(
            title=args["title"],
            description=args.get("description"),
            deadline=deadline,
            user_id=int(args["assignee_id"]),
            client_id=int(args["client_id"]) if args.get("client_id") else None,
            priority=TaskPriority(args.get("priority") or "medium"),
        ),
        ctx.user,
    )
    emoji = PRIORITY_EMOJI.get(task.priority.value, "🔵")
    when = f"\n📅 {deadline.astimezone(ctx.tz).strftime('%d.%m.%Y %H:%M')}" if deadline else ""
    label = PRIORITY_LABEL.get(task.priority.value, task.priority.value)
    client = f"\n👤 {task.client_name}" if task.client_name else ""
    return f"✅ Создана: {task.title} [#{task.id}]\n{emoji} {label}{when}{client}"


# ── поиск задач (прежняя логика голосового обработчика) ──────────────────────
def _task_line(task: SpisokModel) -> str:
    priority = task.priority.value if task.priority else "medium"
    status = task.status.value if task.status else "todo"
    client = f" · 👤 {task.client_name}" if task.client_name else ""
    return (
        f"{PRIORITY_EMOJI.get(priority, '🔵')} {task.title} — {STATUS_LABEL.get(status, status)} [#{task.id}]{client}"
    )


def _text_condition(query: str):
    """Условие поиска по тексту: «50» и «#50» — номер задачи (или слово в названии), слова короче 3 букв не теряются.

    Раньше слова короче трёх символов отбрасывались, и «найди задачу 50» превращалось в «покажи всё».
    """
    parts = [w.strip("#.,;:!?«»\"'") for w in query.split()]
    parts = [w for w in parts if w]
    conditions = []
    for word in parts:
        if word.isdigit():
            conditions.append(SpisokModel.id == int(word))
        if len(word) > 2 or word.isdigit():
            conditions.append(SpisokModel.title.ilike(f"%{word}%"))
    return or_(*conditions) if conditions else SpisokModel.title.ilike(f"%{query.strip()}%")


def _visible_tasks(ctx: AIContext):
    return [
        SpisokModel.deleted_at.is_(None),
        or_(SpisokModel.user_id == ctx.user.id, SpisokModel.author_id == ctx.user.id),
    ]


async def _search_condition(ctx: AIContext, query: str):
    """Одно число («50», «#50») — это номер задачи: если такая видна пользователю, ищем только её, а не все задачи
    со «50» в названии. Нет такого номера — обычный поиск по тексту."""
    number = query.strip().lstrip("#")
    if number.isdigit():
        exists = await ctx.session.scalar(
            select(SpisokModel.id).where(and_(*_visible_tasks(ctx), SpisokModel.id == int(number)))
        )
        if exists is not None:
            return SpisokModel.id == int(number)
    return _text_condition(query)


async def _search_tasks(ctx: AIContext, query: str, limit: int = 5) -> list[SpisokModel]:
    result = await ctx.session.execute(
        select(SpisokModel)
        .where(and_(*_visible_tasks(ctx), await _search_condition(ctx, query)))
        .order_by(SpisokModel.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def _get_tasks(ctx: AIContext, args: dict[str, Any]):
    conditions = _visible_tasks(ctx)
    scope_note = "Я ищу среди задач, где вы исполнитель или автор."
    if args.get("client") or args.get("_client_id"):
        client = await resolve_client(ctx, "get_tasks", args)
        if is_outcome(client):
            return client
        # Задачи клиента видны всей команде (как в карточке клиента), а не только исполнителю/автору
        conditions = [SpisokModel.deleted_at.is_(None), SpisokModel.client_id == client.id]
        scope_note = f"Ищу все задачи клиента «{client.name}»."
    if str(args.get("search") or "").strip():
        conditions.append(await _search_condition(ctx, str(args["search"])))
    if args.get("status") in _STATUSES:
        conditions.append(SpisokModel.status == TaskStatus(args["status"]))
    if args.get("priority") in _PRIORITIES:
        conditions.append(SpisokModel.priority == TaskPriority(args["priority"]))
    if args.get("overdue"):
        conditions += [SpisokModel.deadline < ctx.now(), SpisokModel.status != TaskStatus.done]
    where = and_(*conditions)
    total = await ctx.session.scalar(select(func.count()).select_from(SpisokModel).where(where)) or 0
    result = await ctx.session.execute(
        select(SpisokModel).where(where).order_by(SpisokModel.created_at.desc()).limit(10)
    )
    tasks = list(result.scalars().all())
    if not tasks:
        return Done(f"🔍 Задачи не найдены. {scope_note}")
    more = f" (показаны первые {len(tasks)})" if total > len(tasks) else ""
    return Done("\n".join([f"🔍 Найдено: {total}{more}", *[_task_line(t) for t in tasks]]))


async def _resolve_task(ctx: AIContext, tool: str, args: dict[str, Any]) -> SpisokModel | Outcome:
    """Задача по ключевым словам: SpisokModel либо Outcome (не найдена / выберите / нет прав)."""
    if args.get("_task_id"):
        task = await ctx.tasks.get_task(int(args["_task_id"]), ctx.user)
        return task
    query = str(args.get("search") or "").strip()
    if not query:
        return Refuse("Какую задачу? Назовите её или часть названия.")
    found = await _search_tasks(ctx, query)
    if not found:
        return Refuse(f"🔍 Задача «{query}» не найдена.")
    if len(found) == 1:
        return found[0]
    return Choose(
        prompt=f"Найдено несколько задач по запросу «{query}». Какая?",
        tool=tool,
        param="_task_id",
        options=options_of(found, lambda t: f"{short(t.title, 40)} [#{t.id}]"),
        args=clean_args(args),
    )


async def _check_edit(ctx: AIContext, task: SpisokModel) -> Refuse | None:
    if not await can_edit_task(task, ctx.user, ctx.groups):
        return Refuse("⛔ Менять эту задачу нельзя: нет доступа.")
    return None


# ── изменение задач ──────────────────────────────────────────────────────────
async def _status_run(ctx: AIContext, args: dict[str, Any]):
    if args.get("status") not in _STATUSES:
        return Refuse(f"❌ Неизвестный статус: {args.get('status')}")
    task = await _resolve_task(ctx, "update_task_status", args)
    if is_outcome(task):
        return task
    if (denied := await _check_edit(ctx, task)) is not None:
        return denied
    label = STATUS_LABEL[args["status"]]
    return Confirm(
        text=f"Изменить статус задачи «{task.title}» на {label}?",
        tool="update_task_status",
        args={"task_id": task.id, "title": task.title, "status": args["status"]},
    )


async def _status_commit(ctx: AIContext, args: dict[str, Any]) -> str:
    await ctx.tasks.update_task_status(int(args["task_id"]), TaskStatus(args["status"]), ctx.user)
    return f"✅ {args['title']}\n→ {STATUS_LABEL[args['status']]}"


async def _priority_run(ctx: AIContext, args: dict[str, Any]):
    if args.get("priority") not in _PRIORITIES:
        return Refuse(f"❌ Неизвестный приоритет: {args.get('priority')}")
    task = await _resolve_task(ctx, "update_task_priority", args)
    if is_outcome(task):
        return task
    if (denied := await _check_edit(ctx, task)) is not None:
        return denied
    p = args["priority"]
    return Confirm(
        text=f"Изменить приоритет задачи «{task.title}» на {PRIORITY_EMOJI[p]} {PRIORITY_LABEL[p]}?",
        tool="update_task_priority",
        args={"task_id": task.id, "title": task.title, "priority": p},
    )


async def _priority_commit(ctx: AIContext, args: dict[str, Any]) -> str:
    await ctx.tasks.update_task(int(args["task_id"]), SpisokUpdate(priority=TaskPriority(args["priority"])), ctx.user)
    p = args["priority"]
    return f"✅ {args['title']}\n→ {PRIORITY_EMOJI[p]} {PRIORITY_LABEL[p]}"


async def _description_run(ctx: AIContext, args: dict[str, Any]):
    description = str(args.get("description") or "").strip()
    if not description:
        return Refuse("Какое описание записать?")
    task = await _resolve_task(ctx, "update_task_description", args)
    if is_outcome(task):
        return task
    if (denied := await _check_edit(ctx, task)) is not None:
        return denied
    return Confirm(
        text=f"Заменить описание задачи «{task.title}» на «{short(description, 120)}»?",
        tool="update_task_description",
        args={"task_id": task.id, "title": task.title, "description": description},
    )


async def _description_commit(ctx: AIContext, args: dict[str, Any]) -> str:
    await ctx.tasks.update_task(int(args["task_id"]), SpisokUpdate(description=args["description"]), ctx.user)
    return f"📝 {args['title']}\n→ описание обновлено"


async def _assign_run(ctx: AIContext, args: dict[str, Any]):
    task = await _resolve_task(ctx, "assign_task", args)
    if is_outcome(task):
        return task
    if (denied := await _check_edit(ctx, task)) is not None:
        return denied
    assignee = await _resolve_assignee(ctx, "assign_task", {**args, "_task_id": task.id})
    if is_outcome(assignee):
        return assignee
    if not str(args.get("assignee_username") or "").strip() and not args.get("_assignee_id"):
        return Refuse("Кому назначить задачу?")
    return Confirm(
        text=f"Назначить задачу «{task.title}» на @{assignee.username}?",
        tool="assign_task",
        args={"task_id": task.id, "title": task.title, "assignee_id": assignee.id, "assignee_name": assignee.username},
    )


async def _assign_commit(ctx: AIContext, args: dict[str, Any]) -> str:
    await ctx.tasks.reassign_task(int(args["task_id"]), ctx.user, int(args["assignee_id"]), None)
    return f"✅ {args['title']}\n→ 👤 @{args['assignee_name']}"


# ── регистрация ──────────────────────────────────────────────────────────────
_SEARCH = {"type": "string", "description": "Ключевые слова для поиска задачи"}


def register(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="create_task",
            description="Создать новую задачу; можно поручить сотруднику и привязать к клиенту",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Что сделать (до 100 символов): «Позвонить клиенту»"},
                    "description": {"type": "string", "description": "Подробности задачи"},
                    "priority": {"type": "string", "enum": _PRIORITIES, "description": "Приоритет"},
                    "deadline": {"type": "string", "description": "Дата YYYY-MM-DD"},
                    "deadline_time": {"type": "string", "description": "Время HH:MM"},
                    "assignee_username": {
                        "type": "string",
                        "description": "Кому поручить, имя в начальной форме: «Петру» → «Петр». Не названо — себе",
                    },
                    "client": {"type": "string", "description": "Клиент, к которому относится задача"},
                },
                "required": ["title"],
            },
            run=_create_task_run,
            commit=_create_task_commit,
            hint="«создай/добавь/запиши задачу ...» — create_task (имя исполнителя в начальной форме).",
        )
    )
    registry.register(
        Tool(
            name="get_tasks",
            description="Найти или показать задачи пользователя",
            parameters={
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Текст для поиска по названию"},
                    "status": {"type": "string", "enum": _STATUSES, "description": "Фильтр по статусу"},
                    "priority": {"type": "string", "enum": _PRIORITIES, "description": "Фильтр по приоритету"},
                    "overdue": {"type": "boolean", "description": "Только просроченные задачи"},
                    "client": {"type": "string", "description": "Показать задачи, привязанные к этому клиенту"},
                },
                "required": [],
            },
            run=_get_tasks,
            hint="«найди задачу», «покажи задачи», «какие просрочены» — get_tasks.",
        )
    )
    registry.register(
        Tool(
            name="update_task_status",
            description="Изменить статус задачи",
            parameters={
                "type": "object",
                "properties": {
                    "search": _SEARCH,
                    "status": {"type": "string", "enum": _STATUSES, "description": "Новый статус"},
                },
                "required": ["search", "status"],
            },
            run=_status_run,
            commit=_status_commit,
            hint="«выполни», «закрой», «отметь», «в работе» — update_task_status.",
        )
    )
    registry.register(
        Tool(
            name="update_task_priority",
            description="Изменить приоритет задачи",
            parameters={
                "type": "object",
                "properties": {
                    "search": _SEARCH,
                    "priority": {"type": "string", "enum": _PRIORITIES, "description": "Новый приоритет"},
                },
                "required": ["search", "priority"],
            },
            run=_priority_run,
            commit=_priority_commit,
            hint="«сделай срочной», «повысь приоритет», «низкий приоритет» — update_task_priority.",
        )
    )
    registry.register(
        Tool(
            name="assign_task",
            description="Назначить исполнителя задачи",
            parameters={
                "type": "object",
                "properties": {
                    "search": _SEARCH,
                    "assignee_username": {"type": "string", "description": "Исполнитель, имя в начальной форме"},
                },
                "required": ["search", "assignee_username"],
            },
            run=_assign_run,
            commit=_assign_commit,
            hint="«назначь», «переназначь» — assign_task.",
        )
    )
    registry.register(
        Tool(
            name="update_task_description",
            description="Изменить описание задачи",
            parameters={
                "type": "object",
                "properties": {"search": _SEARCH, "description": {"type": "string", "description": "Новое описание"}},
                "required": ["search", "description"],
            },
            run=_description_run,
            commit=_description_commit,
            hint="«измени описание», «добавь описание», «обнови описание» — update_task_description.",
        )
    )
