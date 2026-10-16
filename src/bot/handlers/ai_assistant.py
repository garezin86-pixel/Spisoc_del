"""
src/bot/handlers/ai_assistant.py

Telegram-адаптер AI-агента (src/ai): текстовые команды, подтверждение «да/нет» и выбор из нескольких вариантов.
Сама логика инструментов и прав живёт в src/ai и от aiogram не зависит — здесь только ввод-вывод бота.

Голосовые сообщения (voice.py) после распознавания речи идут через тот же агент и ту же цепочку подтверждений.
Роутер регистрируется ПОСЛЕДНИМ: обычный текст попадает сюда, только если его не забрали меню, мастера (FSM) и команды.
"""

import html
import logging
from collections.abc import Awaitable, Callable

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.ai import AIAgent, AIContext, Pending, Turn, default_registry
from src.ai.llm import GroqLLM
from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.services.chat_memory import add_message, get_history
from src.services.voice_rate_limit import check_voice_rate_limit

logger = logging.getLogger(__name__)
router = Router()

MAX_TEXT_LENGTH = 1000  # длиннее не отправляем в LLM: защита от лишних расходов
TELEGRAM_LIMIT = 4000

YES_WORDS = {"да", "ага", "угу", "ок", "окей", "ok", "okay", "yes", "y", "+", "👍", "подтверждаю", "давай", "выполняй"}
NO_WORDS = {"нет", "не надо", "не нужно", "отмена", "отмени", "стоп", "no", "n", "-", "👎", "cancel"}


class AIFlow(StatesGroup):
    confirm = State()  # ждём «да/нет» на пишущее действие
    choose = State()  # ждём выбор из нескольких найденных вариантов


Send = Callable[[str, InlineKeyboardMarkup | None], Awaitable[object]]

_agent: AIAgent | None = None


def get_agent() -> AIAgent:
    """Один агент на процесс: реестр без состояния, LLM — Groq."""
    global _agent
    if _agent is None:
        _agent = AIAgent(default_registry(), GroqLLM())
    return _agent


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def classify_reply(text: str) -> str | None:
    """«да» → 'yes', «нет/отмена» → 'no', остальное → None (это новая команда)."""
    word = " ".join(text.casefold().replace("!", " ").replace(".", " ").split())
    if word in YES_WORDS:
        return "yes"
    if word in NO_WORDS:
        return "no"
    return None


def keyboard_for(pending: Pending) -> InlineKeyboardMarkup:
    if pending.kind == "confirm":
        rows = [
            [
                InlineKeyboardButton(text="✅ Да", callback_data="ai:ok"),
                InlineKeyboardButton(text="❌ Нет", callback_data="ai:no"),
            ]
        ]
    else:
        rows = [
            [InlineKeyboardButton(text=name[:60], callback_data=f"ai:pick:{index}")]
            for index, (_, name) in enumerate(pending.options)
        ]
        rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="ai:no")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def render(turn: Turn, prefix: str | None = None) -> str:
    parts = [prefix] if prefix else []
    parts.extend(_esc(m) for m in turn.messages)
    if turn.pending is not None:
        question = _esc(turn.pending.text)
        parts.append(
            f"❓ <b>{question}</b>" + ("\n<i>Ответьте «да» или «нет».</i>" if turn.pending.kind == "confirm" else "")
        )
    text = "\n\n".join(p for p in parts if p) or "Готово."
    return text if len(text) <= TELEGRAM_LIMIT else text[: TELEGRAM_LIMIT - 1] + "…"


def _plain(turn: Turn) -> str:
    lines = list(turn.messages)
    if turn.pending is not None:
        lines.append(turn.pending.text)
    return "\n".join(lines)


async def deliver(turn: Turn, *, state: FSMContext, user_id: int, send: Send, prefix: str | None = None) -> None:
    """Показать результат шага; если нужно решение пользователя — запомнить ожидание в FSM и показать кнопки."""
    if turn.pending is None:
        await state.clear()
        await send(render(turn, prefix), None)
    else:
        await state.set_state(AIFlow.confirm if turn.pending.kind == "confirm" else AIFlow.choose)
        await state.update_data(pending=turn.pending.to_dict(), user_id=user_id)
        await send(render(turn, prefix), keyboard_for(turn.pending))
    await add_message(user_id, "assistant", _plain(turn))


async def run_turn(user_id: int, step: Callable[[AIAgent, AIContext], Awaitable[Turn]]) -> Turn:
    """Выполнить шаг агента в сессии, привязанной к компании (workspace_context ставит middleware бота)."""
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_id(user_id)
        if user is None or not user.is_active:
            return Turn(["⛔ Аккаунт недоступен. Обратитесь к администратору."])
        turn = await step(get_agent(), AIContext(user=user, session=uow.session))
        await uow.commit()
        return turn


async def _lookup_user(telegram_id: int):
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(telegram_id)
        return user


# ── новая текстовая команда ──────────────────────────────────────────────────
async def process_text(message: Message, state: FSMContext, text: str, *, prefix: str | None = None) -> None:
    assert message.from_user is not None
    user = await _lookup_user(message.from_user.id)
    if user is None or not user.is_active:
        await message.answer("❌ У вас нет доступа. Обратитесь к администратору.")
        return
    user_id = user.id

    if len(text) > MAX_TEXT_LENGTH:
        await message.answer(f"✂️ Слишком длинное сообщение (больше {MAX_TEXT_LENGTH} символов). Сформулируйте короче.")
        return

    # До вызова LLM: иначе лимит не защищает от расходов (общий счётчик с голосовыми — оба тратят токены Groq)
    allowed, retry_after = await check_voice_rate_limit(user_id)
    if not allowed:
        minutes = max(1, retry_after // 60)
        await message.answer(f"⏳ Слишком много команд ассистенту подряд. Попробуйте снова через ~{minutes} мин.")
        return

    status = await message.answer("🧠 Обрабатываю…")
    history = await get_history(user_id)
    await add_message(user_id, "user", text)
    try:
        turn = await run_turn(user_id, lambda agent, ctx: agent.handle_text(ctx, text, history))
    except Exception:
        logger.exception("AI text command failed")
        await status.edit_text("❌ Не удалось обработать команду. Попробуйте ещё раз.")
        return

    async def send(body: str, markup: InlineKeyboardMarkup | None) -> object:
        return await status.edit_text(body, reply_markup=markup, parse_mode="HTML")

    await deliver(turn, state=state, user_id=user_id, send=send, prefix=prefix)


@router.message(AIFlow.confirm, F.text)
async def reply_to_confirmation(message: Message, state: FSMContext) -> None:
    """Пока ждём «да/нет», текстовый ответ тоже понимается; всё остальное — новая команда (старая отменяется)."""
    assert message.text is not None
    reply = classify_reply(message.text)
    data = await state.get_data()
    if reply == "yes":
        await _confirm(message.from_user.id if message.from_user else 0, data, state, message.answer)
    elif reply == "no":
        await state.clear()
        await message.answer("❌ Отменено.")
    else:
        await state.clear()
        await process_text(message, state, message.text, prefix="<i>Предыдущее действие отменено.</i>")


@router.message(AIFlow.choose, F.text)
async def reply_while_choosing(message: Message, state: FSMContext) -> None:
    assert message.text is not None
    if classify_reply(message.text) == "no":
        await state.clear()
        await message.answer("❌ Отменено.")
        return
    await state.clear()
    await process_text(message, state, message.text, prefix="<i>Выбор отменён, обрабатываю новую команду.</i>")


@router.message(StateFilter(None), F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def handle_text(message: Message, state: FSMContext) -> None:
    assert message.text is not None
    await process_text(message, state, message.text.strip())


# ── кнопки ───────────────────────────────────────────────────────────────────
async def _owner_ok(callback: CallbackQuery, data: dict) -> bool:
    """Нажимать кнопки может только тот, кто задал команду (и аккаунт ещё действует)."""
    user = await _lookup_user(callback.from_user.id)
    if user is None or not user.is_active or user.id != data.get("user_id"):
        await callback.answer("Это действие вам недоступно.", show_alert=True)
        return False
    return True


async def _confirm(telegram_id: int, data: dict, state: FSMContext, send_plain) -> None:
    pending = Pending.from_dict(data["pending"])
    user_id = int(data["user_id"])
    turn = await run_turn(user_id, lambda agent, ctx: agent.confirm(ctx, pending))

    async def send(body: str, markup: InlineKeyboardMarkup | None) -> object:
        return await send_plain(body, reply_markup=markup, parse_mode="HTML")

    await deliver(turn, state=state, user_id=user_id, send=send)


@router.callback_query(AIFlow.confirm, F.data == "ai:ok")
async def confirm_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not isinstance(callback.message, Message) or not await _owner_ok(callback, data):
        return
    await callback.answer()
    await _confirm(callback.from_user.id, data, state, callback.message.edit_text)


@router.callback_query(AIFlow.choose, F.data.startswith("ai:pick:"))
async def pick_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not isinstance(callback.message, Message) or not await _owner_ok(callback, data):
        return
    pending = Pending.from_dict(data["pending"])
    try:
        index = int((callback.data or "").rsplit(":", 1)[1])
        option_id = pending.options[index][0]
    except (ValueError, IndexError):
        await callback.answer("Такого варианта нет.", show_alert=True)
        return
    await callback.answer()
    user_id = int(data["user_id"])
    turn = await run_turn(user_id, lambda agent, ctx: agent.choose(ctx, pending, option_id))

    async def send(body: str, markup: InlineKeyboardMarkup | None) -> object:
        return await callback.message.edit_text(body, reply_markup=markup, parse_mode="HTML")  # type: ignore[union-attr]

    await deliver(turn, state=state, user_id=user_id, send=send)


@router.callback_query(StateFilter(AIFlow.confirm, AIFlow.choose), F.data == "ai:no")
async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    await state.clear()
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()
