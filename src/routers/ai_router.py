# src/routers/ai_router.py
"""AI-ассистент в вебе: тот же реестр инструментов, права и подтверждения, что и в Telegram-боте (src/ai).

Диалог «команда → вопрос да/нет или выбор → результат» ведут три эндпоинта; ожидающее решение хранится на сервере
(src/ai/pending_store.py), клиент присылает его id. Лимит команд общий с ботом (каждая команда — платный вызов LLM).
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException

from src.ai import AIContext, Pending, Turn
from src.ai.agent import AIAgent
from src.ai.pending_store import pending_store
from src.ai.runtime import get_agent
from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.schemas.ai import AIAction, AIChooseIn, AIConfirmIn, AIMessageIn, AIOption, AIPendingOut, AIReply
from src.services.chat_memory import add_message, get_history
from src.services.voice_rate_limit import check_voice_rate_limit

logger = structlog.get_logger()
router = APIRouter(prefix="/ai", tags=["AI"])

_FAILURE_PREFIXES = ("❌", "⛔", "❓")
_STALE = "Это действие уже выполнено или устарело. Повторите команду."


def _plain(turn: Turn) -> str:
    lines = list(turn.messages)
    if turn.pending is not None:
        lines.append(turn.pending.text)
    return "\n".join(lines)


async def _reply(turn: Turn, user: UserModel, *, changed: bool = False, prefix: list[str] | None = None) -> AIReply:
    """Ответ API; ожидающее решение запоминается на сервере, клиенту уходит только его id."""
    pending_out = None
    if turn.pending is not None:
        pending_id = await pending_store.save(user.workspace_id, user.id, turn.pending)
        pending_out = AIPendingOut(
            id=pending_id,
            kind=turn.pending.kind,  # type: ignore[arg-type]
            text=turn.pending.text,
            options=[AIOption(id=i, label=name) for i, name in turn.pending.options],
        )
    await add_message(user.id, "assistant", _plain(turn))
    return AIReply(
        messages=[*(prefix or []), *turn.messages],
        actions=[AIAction(**a) for a in turn.actions],
        pending=pending_out,
        changed=changed,
    )


@router.post(
    "/message",
    response_model=AIReply,
    summary="Команда ассистенту",
    description="Свободная фраза («создай сделку для Ромашки на 150 тысяч»). Чтение выполняется сразу; запись и "
    "выбор из нескольких вариантов возвращают `pending` — ответьте на него через `/ai/confirm` или `/ai/choose`. "
    "`context.client_id` — открытая карточка клиента. Новая команда отменяет неотвеченный `pending`.",
    responses={
        404: {"description": "Клиент из контекста не найден"},
        429: {"description": "Слишком много команд (общий лимит с Telegram-ботом)"},
        502: {"description": "Не удалось обработать команду (сбой LLM)"},
    },
)
async def send_message(data: AIMessageIn, session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    ctx = AIContext(user=current_user, session=session)
    if data.context and data.context.client_id:
        client = await ctx.clients.get_client(data.context.client_id)  # 404 — чужой или удалённый
        ctx.focus_client_id, ctx.focus_client_name = client.id, client.name
    else:
        await ctx.load_recent_focus()  # открытой карточки нет — берём того, о ком недавно шла речь

    allowed, retry_after = await check_voice_rate_limit(current_user.id)
    if not allowed:
        minutes = max(1, retry_after // 60)
        raise HTTPException(
            429,
            f"Слишком много команд ассистенту подряд. Попробуйте снова через ~{minutes} мин.",
            headers={"Retry-After": str(retry_after)},
        )

    history = await get_history(current_user.id)
    await add_message(current_user.id, "user", data.text)
    replaced = await pending_store.clear(current_user.workspace_id, current_user.id)
    try:
        turn = await get_agent().handle_text(ctx, data.text, history)
    except Exception:
        logger.exception("ai_message_failed")
        raise HTTPException(502, "Не удалось обработать команду. Попробуйте ещё раз.")
    return await _reply(turn, current_user, prefix=["Предыдущее действие отменено."] if replaced else None)


@router.post(
    "/confirm",
    response_model=AIReply,
    summary="Ответ «да/нет» на вопрос ассистента",
    responses={409: {"description": "Действие уже выполнено, отменено или устарело"}},
)
async def confirm(data: AIConfirmIn, session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    pending = await pending_store.take(current_user.workspace_id, current_user.id, data.pending_id)
    if pending is None or pending.kind != "confirm":
        raise HTTPException(409, _STALE)
    if not data.confirm:
        return AIReply(messages=[AIAgent.cancel().messages[0]])
    turn = await get_agent().confirm(AIContext(user=current_user, session=session), pending)
    changed = bool(turn.messages) and not turn.messages[0].startswith(_FAILURE_PREFIXES)
    return await _reply(turn, current_user, changed=changed)


@router.post(
    "/choose",
    response_model=AIReply,
    summary="Выбор варианта (если найдено несколько клиентов, сотрудников, сделок…)",
    responses={
        409: {"description": "Выбор уже сделан или устарел"},
        422: {"description": "Такого варианта нет среди предложенных"},
    },
)
async def choose(data: AIChooseIn, session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    existing: Pending | None = await pending_store.peek(current_user.workspace_id, current_user.id, data.pending_id)
    if existing is None or existing.kind != "choose":
        raise HTTPException(409, _STALE)
    if data.option_id not in {i for i, _ in existing.options}:
        raise HTTPException(422, "Такого варианта нет среди предложенных.")
    pending = await pending_store.take(current_user.workspace_id, current_user.id, data.pending_id)
    if pending is None:  # успел выбрать другой запрос
        raise HTTPException(409, _STALE)
    turn = await get_agent().choose(AIContext(user=current_user, session=session), pending, data.option_id)
    return await _reply(turn, current_user)
