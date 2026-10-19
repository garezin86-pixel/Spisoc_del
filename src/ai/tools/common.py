# src/ai/tools/common.py
"""Общие помощники инструментов: выбор клиента, суммы, даты, подписи."""

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from typing_extensions import TypeIs

from src.ai.context import AIContext
from src.ai.resolve import (
    MAX_OPTIONS,
    find_clients,
    name_score,
    options_of,
    pick_unique,
)
from src.ai.types import Choose, Confirm, Done, Outcome, Refuse
from src.models.client import ClientModel

OUTCOMES = (Done, Refuse, Confirm, Choose)


def is_outcome(value: object) -> TypeIs[Outcome]:
    return isinstance(value, OUTCOMES)


def clean_args(args: dict[str, Any]) -> dict[str, Any]:
    """Аргументы без служебных ключей (_client_id и т.п.) — для повторного запуска после выбора."""
    return {k: v for k, v in args.items() if not k.startswith("_")}


def client_label(client: ClientModel) -> str:
    extra = client.phone or client.email
    return f"{client.name} · {extra}" if extra else client.name


async def resolve_client(ctx: AIContext, tool: str, args: dict[str, Any], key: str = "client") -> ClientModel | Outcome:
    """Клиент по аргументам: либо ClientModel, либо Outcome (Refuse — не найден, Choose — выберите)."""
    chosen = args.get("_client_id")
    if chosen:
        return await ctx.clients.get_client(int(chosen))
    query = str(args.get(key) or "").strip()
    if not query:
        return Refuse("Уточните, о каком клиенте речь.")
    found = await find_clients(ctx, query)
    if not found:
        return Refuse(f"🔍 Клиент «{query}» не найден.")
    unique = pick_unique(query, found) or (found[0] if len(found) == 1 else None)
    if unique is not None:
        return unique
    more = " Показаны первые, уточните название, если нужного нет." if len(found) > MAX_OPTIONS else ""
    return Choose(
        prompt=f"Найдено несколько клиентов по запросу «{query}». Выберите:{more}",
        tool=tool,
        param="_client_id",
        options=options_of(found, client_label),
        args=clean_args(args),
    )


async def resolve_owner(ctx: AIContext, tool: str, args: dict[str, Any], key: str = "owner") -> Any | Outcome:
    """Сотрудник по аргументам: либо UserModel, либо Outcome (Refuse — не найден, Choose — выберите)."""
    chosen = args.get("_owner_id")
    if chosen:
        users = await ctx.users.get_all()
        return next((u for u in users if u.id == int(chosen)), None)

    query = str(args.get(key) or "").strip()
    if not query:
        return None

    users = await ctx.users.get_all()
    scored = []
    for u in users:
        score = name_score(query, u.username)
        full_name = getattr(u, "full_name", "") or ""
        if full_name:
            score = max(score, name_score(query, full_name))
        if score > 0:
            scored.append((score, u))

    scored.sort(key=lambda p: -p[0])
    matches = [u for score, u in scored]

    if not matches:
        return Refuse(f"🔍 Сотрудник «{query}» не найден.")
    if len(matches) == 1:
        return matches[0]

    return Choose(
        prompt=f"Найдено несколько сотрудников по запросу «{query}». Выберите:",
        tool=tool,
        param="_owner_id",
        options=options_of(
            matches,
            lambda u: f"@{u.username}" + (f" ({u.full_name})" if getattr(u, "full_name", None) else ""),
        ),
        args=clean_args(args),
    )


def parse_amount(value: Any) -> Decimal | None:
    """«150000», «150 000», «150,5» → Decimal. Пусто → None. Некорректное → ValueError."""
    if value is None or value == "":
        return None
    text = str(value).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"Не удалось разобрать сумму: {value}")
    if amount < 0:
        raise ValueError("Сумма не может быть отрицательной")
    return amount


def format_money(amount: Decimal | str | float | None, currency: str | None = None) -> str:
    """150000 + UAH → «150 000 UAH»; дробная часть — только если она есть."""
    if amount is None:
        return "без суммы"
    value = Decimal(str(amount))
    text = f"{value:,.2f}".rstrip("0").rstrip(".") if value != value.to_integral() else f"{value:,.0f}"
    text = text.replace(",", " ")
    return f"{text} {currency}".strip() if currency else text


def parse_local_deadline(ctx: AIContext, day: Any, at: Any) -> datetime | None:
    """«2026-10-16» + «10:00» → aware-datetime по Киеву. Только дата — конец дня (23:59), как в боте. Пусто → None."""
    if not day:
        return None
    try:
        d = date.fromisoformat(str(day).strip())
    except ValueError:
        raise ValueError(f"Не удалось разобрать дату: {day}")
    t = time(23, 59)
    if at:
        try:
            hh, mm = str(at).strip().split(":")[:2]
            t = time(int(hh), int(mm))
        except (ValueError, TypeError):
            raise ValueError(f"Не удалось разобрать время: {at}")
    return datetime.combine(d, t, tzinfo=ctx.tz)


def short(text: str, limit: int = 80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
