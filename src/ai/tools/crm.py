# src/ai/tools/crm.py
"""CRM-инструменты: клиенты, сделки, заметки. Вызывают сервисы CRM; права — в `allowed`/`run` и в самих сервисах."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from src.ai.context import AIContext
from src.ai.permissions import can_create_clients, can_edit_client, can_manage_deal, is_manager
from src.ai.registry import Tool, ToolRegistry
from src.ai.resolve import find_clients, name_score, norm, options_of
from src.ai.tools.common import (
    format_money,
    is_outcome,
    parse_amount,
    resolve_client,
    resolve_owner,
    short,
)
from src.ai.types import Choose, Confirm, Done, Outcome, Refuse
from src.models.deal import DealModel, StageKind, StageModel
from src.models.enums import TaskStatus
from src.models.interaction import InteractionModel, InteractionType
from src.models.task import SpisokModel
from src.schemas.client import ClientCreate
from src.schemas.deal import DealCreate, DealMove
from src.schemas.interaction import InteractionCreate

_INTERACTION_LABELS = {
    "note": "заметку",
    "call": "запись о звонке",
    "meeting": "запись о встрече",
    "email": "запись о письме",
    "message": "запись о сообщении",
}


async def _owner_names(ctx: AIContext) -> dict[int, str]:
    return {u.id: u.username for u in await ctx.users.get_all()}


# ── find_client ──────────────────────────────────────────────────────────────
async def _find_client(ctx: AIContext, args: dict[str, Any]):
    query = str(args.get("query") or "").strip()
    if not query:
        return Refuse("Уточните, кого искать: название, телефон или email.")
    found = await find_clients(ctx, query, limit=6)
    if not found:
        return Done(f"🔍 Клиент «{query}» не найден.")
    if len(found) == 1:
        await ctx.remember_client(found[0])  # «найди клиента X» → «создай ему задачу» относится к X
    owners = await _owner_names(ctx)
    lines = [f"🔍 Найдено: {len(found)}"]
    for c in found[:5]:
        extra = [x for x in (c.phone, c.email) if x]
        owner = f"ответственный @{owners[c.owner_id]}" if c.owner_id in owners else "без ответственного"
        lines.append(f"• {c.name} — {', '.join(extra + [owner])}")
    return Done("\n".join(lines))


# ── open_client ──────────────────────────────────────────────────────────────
async def _open_client(ctx: AIContext, args: dict[str, Any]):
    """Сводка по клиенту; в вебе — ещё и команда «открыть карточку» (в Telegram её просто нет, хватает текста)."""
    client = await resolve_client(ctx, "open_client", args)
    if is_outcome(client):
        return client
    owners = await _owner_names(ctx)
    deals_total = (await ctx.deals.list_deals(0, 1, client_id=client.id))[1]
    open_tasks = (
        await ctx.session.scalar(
            select(func.count())
            .select_from(SpisokModel)
            .where(
                SpisokModel.deleted_at.is_(None),
                SpisokModel.client_id == client.id,
                SpisokModel.status != TaskStatus.done,
            )
        )
        or 0
    )
    last_contact = await ctx.session.scalar(
        select(func.max(InteractionModel.occurred_at)).where(
            InteractionModel.client_id == client.id, InteractionModel.deleted_at.is_(None)
        )
    )
    owner = f"@{owners[client.owner_id]}" if client.owner_id in owners else "не назначен"
    lines = [f"📇 {client.name} — {_TYPE_LABELS.get(client.client_type, client.client_type)}"]
    contacts = [x for x in (client.phone, client.email) if x]
    if contacts:
        lines.append(", ".join(contacts))
    lines.append(f"Ответственный: {owner}")
    last = last_contact.strftime("%d.%m.%Y") if last_contact else "контактов ещё не было"
    lines.append(f"Сделок: {deals_total} · открытых задач: {open_tasks} · последний контакт: {last}")
    return Done("\n".join(lines), actions=[{"type": "open_client", "client_id": client.id}])


# ── list_clients ─────────────────────────────────────────────────────────────
_TYPE_LABELS = {"company": "компания", "person": "частное лицо"}


async def _list_clients(ctx: AIContext, args: dict[str, Any]):
    client_type = args.get("client_type")
    if client_type not in _TYPE_LABELS:
        client_type = None
    search = str(args.get("search") or "").strip() or None
    owner = await resolve_owner(ctx, "list_clients", args)
    if is_outcome(owner):
        return owner
    if owner is None and args.get("mine"):
        owner = ctx.user
    clients, total = await ctx.clients.get_clients(
        search, 0, 15, owner_id=owner.id if owner else None, client_type=client_type
    )
    scope = ["ваши" if owner.id == ctx.user.id else f"@{owner.username}"] if owner else []
    if client_type:
        scope.append("частные лица" if client_type == "person" else "компании")
    title = f"👥 Клиенты ({', '.join(scope)})" if scope else "👥 Клиенты"
    if not clients:
        return Done(f"🔍 {title}: никого не найдено.")
    owners = await _owner_names(ctx)
    lines = [f"{title}: {total}"]
    for c in clients:
        owner = f"@{owners[c.owner_id]}" if c.owner_id in owners else "без ответственного"
        lines.append(f"• {c.name} — {_TYPE_LABELS.get(c.client_type, c.client_type)}, {owner}")
    if total > len(clients):
        lines.append(f"…и ещё {total - len(clients)}")
    return Done("\n".join(lines))


# ── list_clients_without_contact ─────────────────────────────────────────────
async def _clients_without_contact(ctx: AIContext, args: dict[str, Any]):
    try:
        raw_days = args.get("days")
        days = 30 if raw_days in (None, "") else int(raw_days)  # 0 — не «по умолчанию», а ошибка ниже
    except (TypeError, ValueError):
        return Refuse("Укажите срок числом дней, например 30.")
    if not 1 <= days <= 3650:
        return Refuse("Срок должен быть от 1 до 3650 дней.")
    all_owners = bool(args.get("all_owners"))
    scope_all = all_owners and is_manager(ctx.user)
    rows, total = await ctx.dashboard_repo.stale_clients(
        None if scope_all else ctx.user.id, ctx.now() - timedelta(days=days), 10
    )
    scope = "всех ответственных" if scope_all else "ваших"
    if all_owners and not scope_all:
        note = "\n(Показаны ваши клиенты: смотреть чужих могут admin и manager.)"
    elif not scope_all and is_manager(ctx.user):
        # admin/manager по умолчанию видят свой список: подсказываем, как посмотреть всех,
        # чтобы «нет» не вводило в заблуждение
        note = "\nℹ️ Это только ваши клиенты. Клиенты всех ответственных: «клиенты без контакта у всех»."
    else:
        note = ""
    if total == 0:
        return Done(f"✅ Нет {scope} клиентов без контакта дольше {days} дн.{note}")
    lines = [f"📞 Клиентов {scope} без контакта дольше {days} дн.: {total}"]
    for client, last_at in rows:
        baseline = last_at if last_at is not None else client.created_at
        if baseline.tzinfo is None:
            baseline = baseline.replace(tzinfo=ctx.now().tzinfo)
        gone = (ctx.now() - baseline).days
        lines.append(
            f"• {client.name} — {gone} дн. без контакта"
            if last_at
            else f"• {client.name} — контактов ещё не было ({gone} дн. в базе)"
        )
    if total > len(rows):
        lines.append(f"…и ещё {total - len(rows)}")
    return Done("\n".join(lines) + note)


# ── create_client ────────────────────────────────────────────────────────────
def _client_data(args: dict[str, Any]) -> ClientCreate:
    return ClientCreate(
        name=str(args.get("name") or ""),
        client_type=args.get("client_type") or "company",
        phone=args.get("phone") or None,
        email=args.get("email") or None,
        notes=args.get("notes") or None,
    )


async def _create_client_run(ctx: AIContext, args: dict[str, Any]):
    data = _client_data(args)  # ValidationError → отказ с понятным текстом (в реестре)
    same = [c for c in await find_clients(ctx, data.name, limit=5) if norm(c.name) == norm(data.name)]
    warning = f"\n⚠️ Клиент с таким названием уже есть (#{same[0].id}) — будет дубль." if same else ""
    kind = "частное лицо" if data.client_type == "person" else "компания"
    extra = ", ".join(x for x in (data.phone, data.email) if x)
    text = f"Создать клиента «{data.name}» ({kind}{', ' + extra if extra else ''})?{warning}"
    return Confirm(text=text, tool="create_client", args=data.model_dump(mode="json", exclude_none=True))


async def _create_client_commit(ctx: AIContext, args: dict[str, Any]) -> str:
    client = await ctx.clients.create_client(ClientCreate(**args), ctx.user)
    return f"✅ Клиент «{client.name}» создан (#{client.id})."


# ── create_deal ──────────────────────────────────────────────────────────────
def _deal_fields(title: str, amount: Decimal | None, currency: str | None, close_date: str | None) -> dict[str, Any]:
    """Поля DealCreate без пустых: валюту нельзя передать как None (схема запрещает «очистить»)."""
    fields: dict[str, Any] = {"title": title, "amount": amount}
    if currency:
        fields["currency"] = currency
    if close_date:
        fields["expected_close_date"] = date.fromisoformat(close_date)
    return fields


async def _create_deal_run(ctx: AIContext, args: dict[str, Any]):
    client = await resolve_client(ctx, "create_deal", args)
    if is_outcome(client):
        return client
    if not can_edit_client(client, ctx.user):
        return Refuse("⛔ Создавать сделки по этому клиенту могут его ответственный, admin и manager.")
    try:
        amount = parse_amount(args.get("amount"))
    except ValueError as exc:
        return Refuse(f"❌ {exc}")
    title = str(args.get("title") or "").strip() or f"Сделка — {client.name}"
    currency = (str(args.get("currency")).strip().upper() if args.get("currency") else None) or None
    close_date = str(args["expected_close_date"]) if args.get("expected_close_date") else None
    data = DealCreate(**_deal_fields(title, amount, currency, close_date))
    _, stages = await ctx.deals.get_pipeline(ctx.user, None)
    first_open = next((s for s in stages if s.kind == StageKind.open.value), None)
    parts = [f"Создать сделку «{data.title}» для «{client.name}»"]
    if amount is not None:
        parts.append(f"на {format_money(amount, data.currency or 'UAH')}")
    if first_open:
        parts.append(f"(стадия «{first_open.name}»)")
    resolved = {
        "client_id": client.id,
        "client_name": client.name,
        "title": data.title,
        "amount": str(amount) if amount is not None else None,
        "currency": data.currency,
        "expected_close_date": close_date,
    }
    return Confirm(text=" ".join(parts) + "?", tool="create_deal", args=resolved)


async def _create_deal_commit(ctx: AIContext, args: dict[str, Any]) -> str:
    amount = parse_amount(args.get("amount"))
    data = DealCreate(**_deal_fields(args["title"], amount, args.get("currency"), args.get("expected_close_date")))
    deal = await ctx.deals.create_deal(int(args["client_id"]), data, ctx.user)
    amount = f" на {format_money(deal.amount, deal.currency)}" if deal.amount is not None else ""
    return f"✅ Сделка «{deal.title}» создана (#{deal.id}) для «{args['client_name']}»{amount}."


# ── list_deals ───────────────────────────────────────────────────────────────
async def _resolve_stage(
    ctx: AIContext, tool: str, args: dict[str, Any], stages: list[StageModel], query: str
) -> StageModel | Outcome:
    """Стадия воронки по названию: StageModel, либо Outcome (не найдена / выберите)."""
    if args.get("_stage_id"):
        stage = next((s for s in stages if s.id == int(args["_stage_id"])), None)
        return stage or Refuse("🔍 Такой стадии нет в воронке.")
    scored = sorted(((name_score(query, s.name), s) for s in stages), key=lambda p: -p[0])
    matches = [s for score, s in scored if score > 0]
    top = [s for score, s in scored if score and score == scored[0][0]]
    if len(top) == 1:
        return top[0]
    if not matches:
        names = ", ".join(f"«{s.name}»" for s in stages)
        return Refuse(f"🔍 Стадия «{query}» не найдена. В воронке: {names}.")
    return Choose(
        prompt=f"Какая стадия имеется в виду по запросу «{query}»?",
        tool=tool,
        param="_stage_id",
        options=options_of(matches, lambda s: s.name),
        args={k: v for k, v in args.items() if not k.startswith("_")},
    )


async def _list_deals(ctx: AIContext, args: dict[str, Any]):
    _, stages = await ctx.deals.get_pipeline(ctx.user, None)
    stage_by_id = {s.id: s for s in stages}
    stage_id = None
    stage_query = str(args.get("stage") or "").strip()
    if stage_query or args.get("_stage_id"):
        stage = await _resolve_stage(ctx, "list_deals", args, stages, stage_query)
        if is_outcome(stage):
            return stage
        stage_id = stage.id
    client_id = None
    if args.get("client") or args.get("_client_id"):
        client = await resolve_client(ctx, "list_deals", args)
        if is_outcome(client):
            return client
        client_id = client.id
    owner = await resolve_owner(ctx, "list_deals", args)
    if is_outcome(owner):
        return owner
    if owner is not None:
        owner_id = owner.id
    elif client_id is not None or (args.get("all_owners") and is_manager(ctx.user)):
        owner_id = None
    else:
        owner_id = ctx.user.id
    deals, total = await ctx.deals.list_deals(0, 15, client_id=client_id, stage_id=stage_id, owner_id=owner_id)
    if client_id is not None:
        scope = "по клиенту"
    elif owner_id is None:
        scope = "всех ответственных"
    elif owner is not None and owner.id != ctx.user.id:
        scope = f"@{owner.username}"
    else:
        scope = "ваши"
    where = f" на стадии «{stage_by_id[stage_id].name}»" if stage_id in stage_by_id else ""
    if not deals:
        return Done(f"🔍 Сделок ({scope}){where} нет.")
    names = await ctx.client_repo.get_names({d.client_id for d in deals})
    lines = [f"💼 Сделки ({scope}){where}: {total}"]
    for d in deals:
        stage = stage_by_id.get(d.stage_id)
        amount = format_money(d.amount, d.currency) if d.amount is not None else "без суммы"
        lines.append(f"• {d.title} — {names.get(d.client_id, '?')} · {stage.name if stage else '?'} · {amount}")
    if total > len(deals):
        lines.append(f"…и ещё {total - len(deals)}")
    return Done("\n".join(lines))


# ── pipeline_summary ─────────────────────────────────────────────────────────
def _totals_text(totals) -> str:
    return " · ".join(format_money(t.amount, t.currency) for t in totals if t.amount) or "без сумм"


async def _pipeline_summary(ctx: AIContext, args: dict[str, Any]):
    owner = await resolve_owner(ctx, "pipeline_summary", args)
    if is_outcome(owner):
        return owner
    if owner is None and args.get("mine"):
        owner = ctx.user
    summary = await ctx.deals.get_summary(ctx.user, owner_id=owner.id if owner else None)
    who = ("ваша" if owner.id == ctx.user.id else f"@{owner.username}") if owner else "вся компания"
    lines = [f"📊 Воронка «{summary.pipeline_name}» ({who})"]
    for stage in summary.stages:
        lines.append(f"• {stage.name}: {stage.count} · {_totals_text(stage.totals)}")
    c = summary.conversion
    if c.closed:
        lines.append(f"Закрыто: выиграно {c.won}, проиграно {c.lost} (успешных {round((c.win_rate or 0) * 100)}%)")
    if not any(s.count for s in summary.stages):
        lines.append("Сделок пока нет.")
    return Done("\n".join(lines))


# ── move_deal_stage ──────────────────────────────────────────────────────────
async def _resolve_deal(ctx: AIContext, args: dict[str, Any], stages: list[StageModel]) -> DealModel | Outcome:
    """Сделка по клиенту и/или ключевым словам из названия: DealModel либо Outcome."""
    if args.get("_deal_id"):
        return await ctx.deals.get_deal(int(args["_deal_id"]))
    keyword = str(args.get("deal") or "").strip()
    client_id = None
    if args.get("client") or args.get("_client_id"):
        client = await resolve_client(ctx, "move_deal_stage", args)
        if is_outcome(client):
            return client
        client_id = client.id
    elif not keyword:
        return Refuse("Уточните клиента или название сделки.")
    owner_id = None if (client_id is not None or is_manager(ctx.user)) else ctx.user.id
    deals, _ = await ctx.deals.list_deals(0, 100, client_id=client_id, owner_id=owner_id)
    kinds = {s.id: s.kind for s in stages}
    candidates = [d for d in deals if kinds.get(d.stage_id) == StageKind.open.value] or deals
    if keyword:
        candidates = [d for d in candidates if name_score(keyword, d.title)] or []
    if not candidates:
        return Refuse("🔍 Подходящая сделка не найдена.")
    if len(candidates) == 1:
        return candidates[0]
    stage_names = {s.id: s.name for s in stages}
    return Choose(
        prompt="Какая сделка имеется в виду?",
        tool="move_deal_stage",
        param="_deal_id",
        options=options_of(candidates, lambda d: f"{d.title} · {stage_names.get(d.stage_id, '?')}"),
        args={k: v for k, v in args.items() if not k.startswith("_") or k == "_client_id"},
    )


async def _move_deal_run(ctx: AIContext, args: dict[str, Any]):
    target_query = str(args.get("stage") or "").strip()
    if not target_query and not args.get("_stage_id"):
        return Refuse("Уточните, на какую стадию перевести сделку.")
    _, stages = await ctx.deals.get_pipeline(ctx.user, None)
    deal = await _resolve_deal(ctx, args, stages)
    if is_outcome(deal):
        return deal
    if not can_manage_deal(deal, ctx.user):
        return Refuse("⛔ Переводить сделку могут её ответственный, admin и manager.")
    current = next((s for s in stages if s.id == deal.stage_id), None)
    if current is None:
        return Refuse("Сделка лежит в другой воронке — переведите её в веб-интерфейсе.")
    target = await _resolve_stage(ctx, "move_deal_stage", {**args, "_deal_id": deal.id}, stages, target_query)
    if is_outcome(target):
        return target
    names = await ctx.client_repo.get_names({deal.client_id})
    client_name = names.get(deal.client_id, "?")
    if target.id == current.id:
        return Done(f"Сделка «{deal.title}» уже на стадии «{current.name}».")
    lost_reason = str(args.get("lost_reason") or "").strip() or None
    if target.kind == StageKind.lost.value and not lost_reason:
        return Refuse(
            "Для проигранной сделки нужна причина. Повторите команду, назвав её: «…, потому что выбрали конкурента»."
        )
    if target.kind == StageKind.won.value and deal.amount is None:
        return Refuse("Для выигранной сделки нужна сумма — укажите её в карточке сделки.")
    reason = f" Причина: {lost_reason}." if lost_reason and target.kind == StageKind.lost.value else ""
    text = f"Перевести сделку «{deal.title}» ({client_name}) со стадии «{current.name}» на «{target.name}»?{reason}"
    resolved = {
        "deal_id": deal.id, "deal_title": deal.title, "stage_id": target.id, "stage_name": target.name,
        "lost_reason": lost_reason if target.kind == StageKind.lost.value else None,
    }  # fmt: skip
    return Confirm(text=text, tool="move_deal_stage", args=resolved)


async def _move_deal_commit(ctx: AIContext, args: dict[str, Any]) -> str:
    await ctx.deals.move_deal(
        int(args["deal_id"]), DealMove(stage_id=int(args["stage_id"]), lost_reason=args.get("lost_reason")), ctx.user
    )
    return f"✅ Сделка «{args['deal_title']}» переведена на стадию «{args['stage_name']}»."


# ── add_note ─────────────────────────────────────────────────────────────────
async def _add_note_run(ctx: AIContext, args: dict[str, Any]):
    text = str(args.get("text") or "").strip()
    if not text:
        return Refuse("Что записать? Продиктуйте текст заметки.")
    kind = str(args.get("type") or "note")
    if kind not in {t.value for t in InteractionType}:
        kind = "note"
    client = await resolve_client(ctx, "add_note", args)
    if is_outcome(client):
        return client
    if not can_edit_client(client, ctx.user):
        return Refuse("⛔ Писать в историю этого клиента могут его ответственный, admin и manager.")
    InteractionCreate(type=InteractionType(kind), summary=text)  # проверка длины и пустоты до вопроса «да/нет»
    question = f"Добавить {_INTERACTION_LABELS[kind]} к «{client.name}»: «{short(text, 150)}»?"
    return Confirm(
        text=question,
        tool="add_note",
        args={"client_id": client.id, "client_name": client.name, "type": kind, "text": text},
    )


async def _add_note_commit(ctx: AIContext, args: dict[str, Any]) -> str:
    await ctx.interactions.create(
        int(args["client_id"]), InteractionCreate(type=InteractionType(args["type"]), summary=args["text"]), ctx.user
    )
    return f"✅ Записано в историю клиента «{args['client_name']}»."


# ── регистрация ──────────────────────────────────────────────────────────────
def register(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="find_client",
            description="Найти клиента по названию, телефону или email",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Название компании, ФИО, телефон или email"}},
                "required": ["query"],
            },
            run=_find_client,
            hint="«найди клиента», «есть ли клиент», «телефон клиента» — find_client.",
        )
    )
    registry.register(
        Tool(
            name="open_client",
            description=(
                "Открыть карточку клиента: показать сводку (контакты, ответственный, сделки, задачи, последний "
                "контакт); в веб-интерфейсе карточка откроется на экране. Дальше «этот клиент» — он"
            ),
            parameters={
                "type": "object",
                "properties": {"client": {"type": "string", "description": "Название клиента, телефон или email"}},
                "required": ["client"],
            },
            run=_open_client,
            hint="«открой карточку клиента ...», «покажи клиента ...», «перейди к клиенту» — open_client.",
        )
    )
    registry.register(
        Tool(
            name="list_clients",
            description=(
                "Показать список клиентов: всех, чьих-то или по типу. Тип (client_type) указывай ТОЛЬКО если "
                "пользователь назвал его: «люди», «частные лица», «B2C/Б2С» — person; «компании-клиенты», "
                "«юрлица», «B2B/Б2Б» — company. «Все клиенты компании» (то есть всей организации) — без типа"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "mine": {"type": "boolean", "description": "true — только клиенты пользователя («мои клиенты»)"},
                    "client_type": {"type": "string", "enum": ["company", "person"], "description": "Тип клиента"},
                    "owner": {"type": "string", "description": "Клиенты этого сотрудника, имя в начальной форме"},
                    "search": {"type": "string", "description": "Часть названия, телефона или email"},
                },
                "required": [],
            },
            run=_list_clients,
            hint="«покажи всех клиентов», «мои клиенты», «клиенты-люди/компании» — list_clients.",
        )
    )
    registry.register(
        Tool(
            name="list_clients_without_contact",
            description="Показать клиентов, с которыми давно не было контакта (звонков, встреч, заметок)",
            parameters={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Сколько дней без контакта: месяц — 30, неделя — 7"},
                    "all_owners": {
                        "type": "boolean",
                        "description": "Клиенты всех ответственных: «у всех», «по компании» (только admin/manager)",
                    },
                },
                "required": [],
            },
            run=_clients_without_contact,
            hint="«клиенты без контакта больше месяца» — list_clients_without_contact(days=30).",
        )
    )
    registry.register(
        Tool(
            name="create_client",
            description="Создать нового клиента (только admin и manager)",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Название компании или ФИО частного лица"},
                    "client_type": {
                        "type": "string",
                        "enum": ["company", "person"],
                        "description": "company — компания",
                    },
                    "phone": {"type": "string"},
                    "email": {"type": "string"},
                    "notes": {"type": "string", "description": "Заметки о клиенте"},
                },
                "required": ["name"],
            },
            run=_create_client_run,
            commit=_create_client_commit,
            allowed=can_create_clients,
            hint="«создай клиента ...», «добавь клиента ...» — create_client.",
        )
    )
    registry.register(
        Tool(
            name="create_deal",
            description="Создать сделку для клиента (в первой открытой стадии воронки)",
            parameters={
                "type": "object",
                "properties": {
                    "client": {"type": "string", "description": "Название клиента"},
                    "title": {
                        "type": "string",
                        "description": "Название сделки; не названа — подставится автоматически",
                    },
                    "amount": {"type": "number", "description": "Сумма числом: «150 тысяч» → 150000"},
                    "currency": {
                        "type": "string",
                        "enum": ["UAH", "USD", "EUR"],
                        "description": "Валюта; не названа — UAH",
                    },
                    "expected_close_date": {"type": "string", "description": "Ожидаемая дата закрытия YYYY-MM-DD"},
                },
                "required": ["client"],
            },
            run=_create_deal_run,
            commit=_create_deal_commit,
            hint="«создай сделку для ...», «новая сделка ...» — create_deal.",
        )
    )
    registry.register(
        Tool(
            name="move_deal_stage",
            description="Перевести сделку на другую стадию воронки",
            parameters={
                "type": "object",
                "properties": {
                    "client": {"type": "string", "description": "Клиент, чья сделка"},
                    "deal": {"type": "string", "description": "Слова из названия сделки, если у клиента несколько"},
                    "stage": {"type": "string", "description": "Название целевой стадии"},
                    "lost_reason": {"type": "string", "description": "Причина, если сделка проиграна"},
                },
                "required": ["stage"],
            },
            run=_move_deal_run,
            commit=_move_deal_commit,
            hint="«переведи сделку ... в ...», «сделка ... выиграна/проиграна» — move_deal_stage.",
        )
    )
    registry.register(
        Tool(
            name="list_deals",
            description="Показать сделки: свои, по стадии воронки или по клиенту",
            parameters={
                "type": "object",
                "properties": {
                    "stage": {"type": "string", "description": "Название стадии воронки"},
                    "client": {"type": "string", "description": "Показать сделки этого клиента"},
                    "owner": {"type": "string", "description": "Сделки этого сотрудника, имя в начальной форме"},
                    "all_owners": {
                        "type": "boolean",
                        "description": "Сделки всех ответственных (только admin/manager)",
                    },
                },
                "required": [],
            },
            run=_list_deals,
            hint="«покажи сделки», «сделки на стадии ...» — list_deals.",
        )
    )
    registry.register(
        Tool(
            name="pipeline_summary",
            description="Сводка по воронке продаж: сколько сделок и на какую сумму на каждой стадии, итоги закрытых",
            parameters={
                "type": "object",
                "properties": {
                    "mine": {"type": "boolean", "description": "true — только сделки пользователя («мои воронки»)"},
                    "owner": {"type": "string", "description": "Воронка этого сотрудника, имя в начальной форме"},
                },
                "required": [],
            },
            run=_pipeline_summary,
            hint="«покажи воронку», «мои воронки», «сколько сделок на каждой стадии» — pipeline_summary.",
        )
    )
    registry.register(
        Tool(
            name="add_note",
            description="Добавить заметку или запись о контакте в историю клиента",
            parameters={
                "type": "object",
                "properties": {
                    "client": {"type": "string", "description": "Название клиента"},
                    "text": {"type": "string", "description": "Текст заметки"},
                    "type": {
                        "type": "string",
                        "enum": [t.value for t in InteractionType],
                        "description": "note — заметка (по умолчанию), call — звонок, meeting — встреча",
                    },
                },
                "required": ["client", "text"],
            },
            run=_add_note_run,
            commit=_add_note_commit,
            hint="«запиши по клиенту ...», «добавь заметку ...», «звонил клиенту ...» — add_note.",
        )
    )
