# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_ai_bot.py
"""Telegram-адаптер AI-агента (Этап 5): текст и голос → агент → подтверждение/выбор кнопками.

Настоящие: БД, сервисы CRM, реестр инструментов, FSM (MemoryStorage). Подменены: LLM (сценарий), распознавание речи,
Redis-память диалога, Telegram (моки). Rate limiter — тот же, что у голоса, проверяется, что он стоит ДО вызова LLM.
"""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from sqlalchemy import select

from src.ai import AIAgent, default_registry
from src.bot.handlers import ai_assistant as ai_bot
from src.bot.handlers import voice as voice_bot
from src.db.tenant_scope import workspace_context
from src.models.client import ClientModel
from src.models.deal import DealModel
from src.models.task import SpisokModel
from src.models.user import UserModel
from tests.test_ai_agent import FakeLLM, call
from tests.test_ai_tools import add_clients, add_user, tomorrow_at
from tests.test_clients import world  # noqa: F401  (world — фикстура)

TG = {"owner": 700001, "a_manager": 700002, "other": 700003}


@pytest.fixture
async def bot_env(world):
    """Telegram-id у сотрудников, привязка сессий к компании A, подмена БД/Redis/лимитера; LLM задаётся тестом."""
    maker, ids, _ = world
    async with maker() as s:
        for who, tg in TG.items():
            user = (await s.execute(select(UserModel).where(UserModel.id == ids[who]))).scalar_one()
            user.telegram_id = tg
        await s.commit()

    env = SimpleNamespace(maker=maker, ids=ids, llm=None, limiter=AsyncMock(return_value=(True, 0)), memory=AsyncMock())

    def use_llm(*plans):
        env.llm = FakeLLM(*plans)
        env.agent = AIAgent(default_registry(), env.llm)

    env.use_llm = use_llm
    env.use_llm()
    patches = [
        patch.object(ai_bot, "get_session_maker", lambda: maker),
        patch.object(voice_bot, "get_session_maker", lambda: maker),
        patch.object(ai_bot, "get_agent", lambda: env.agent),
        patch.object(ai_bot, "check_voice_rate_limit", env.limiter),
        patch.object(voice_bot, "check_voice_rate_limit", env.limiter),
        patch.object(ai_bot, "get_history", AsyncMock(return_value=[])),
        patch.object(voice_bot, "get_history", AsyncMock(return_value=[])),
        patch.object(ai_bot, "add_message", env.memory),
        patch.object(voice_bot, "add_message", env.memory),
    ]
    for p in patches:
        p.start()
    with workspace_context(ids["a"]):  # как middleware бота: все сессии внутри — в компании A
        yield env
    for p in patches:
        p.stop()


def fsm(tg_id: int) -> FSMContext:
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=tg_id, user_id=tg_id))


def text_message(tg_id: int, text: str):
    status = MagicMock()
    status.edit_text = AsyncMock()
    message = MagicMock()
    message.from_user = SimpleNamespace(id=tg_id)
    message.text = text
    message.answer = AsyncMock(return_value=status)
    return message, status


def callback(tg_id: int, data: str):
    cb = MagicMock()
    cb.data = data
    cb.from_user = SimpleNamespace(id=tg_id)
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    return cb


def shown(mock) -> str:
    """Текст последнего edit_text/answer."""
    return mock.await_args.args[0]


def buttons(mock) -> list[str]:
    markup = mock.await_args.kwargs.get("reply_markup")
    return [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []


# ── текстовые команды ────────────────────────────────────────────────────────
async def test_text_read_scenario_clients_without_contact(bot_env):
    await add_clients(bot_env.maker, bot_env.ids, ("Давний клиент", "owner", 45))
    bot_env.use_llm([call("list_clients_without_contact", days=30)])
    state = fsm(TG["owner"])
    message, status = text_message(TG["owner"], "покажи клиентов без контакта больше месяца")

    await ai_bot.handle_text(message, state)

    assert "Давний клиент" in shown(status.edit_text) and "дольше 30 дн." in shown(status.edit_text)
    assert buttons(status.edit_text) == [] and await state.get_state() is None
    assert bot_env.llm.seen[0]["text"] == "покажи клиентов без контакта больше месяца"


async def test_text_write_scenario_task_for_colleague_with_buttons(bot_env):
    petr = await add_user(bot_env.maker, bot_env.ids, "Петр")
    day, at = tomorrow_at(10)
    bot_env.use_llm(
        [call("create_task", title="Позвонить клиенту", assignee_username="Петру", deadline=day, deadline_time=at)]
    )
    state = fsm(TG["a_manager"])
    message, status = text_message(TG["a_manager"], "создай задачу Петру позвонить клиенту завтра в 10")

    await ai_bot.handle_text(message, state)

    question = shown(status.edit_text)
    assert "Создать задачу «Позвонить клиенту» для @Петр" in question and "10:00" in question
    assert buttons(status.edit_text) == ["ai:ok", "ai:no"]
    assert await state.get_state() == ai_bot.AIFlow.confirm.state
    async with bot_env.maker() as s:  # без «да» задачи нет
        assert (await s.execute(select(SpisokModel))).scalars().all() == []

    cb = callback(TG["a_manager"], "ai:ok")
    await ai_bot.confirm_callback(cb, state)

    assert shown(cb.message.edit_text).startswith("✅ Создана")
    assert await state.get_state() is None
    async with bot_env.maker() as s:
        assert (await s.execute(select(SpisokModel.user_id))).scalar_one() == petr


async def test_typed_yes_confirms_and_no_cancels(bot_env):
    bot_env.use_llm(
        [call("create_deal", client="Ромашка", amount=100)], [call("create_deal", client="Ромашка", amount=200)]
    )
    for answer, expect_deal in (("Да!", True), ("нет", False)):
        async with bot_env.maker() as s:
            for deal in (await s.execute(select(DealModel))).scalars().all():
                await s.delete(deal)
            await s.commit()
        state = fsm(TG["owner"])
        message, _ = text_message(TG["owner"], "сделка для Ромашки")
        await ai_bot.handle_text(message, state)
        assert await state.get_state() == ai_bot.AIFlow.confirm.state

        reply, _ = text_message(TG["owner"], answer)
        await ai_bot.reply_to_confirmation(reply, state)
        assert await state.get_state() is None
        async with bot_env.maker() as s:
            assert bool((await s.execute(select(DealModel))).scalars().all()) is expect_deal
        assert reply.answer.await_args.args[0].startswith("✅" if expect_deal else "❌ Отменено")


async def test_other_text_while_confirming_replaces_the_pending_action(bot_env):
    bot_env.use_llm([call("create_deal", client="Ромашка", amount=100)], [call("find_client", query="Ромашка")])
    state = fsm(TG["owner"])
    first, _ = text_message(TG["owner"], "сделка для Ромашки")
    await ai_bot.handle_text(first, state)

    second, status = text_message(TG["owner"], "найди клиента Ромашка")
    await ai_bot.reply_to_confirmation(second, state)

    assert "Предыдущее действие отменено" in shown(status.edit_text) and "Ромашка" in shown(status.edit_text)
    assert await state.get_state() is None
    async with bot_env.maker() as s:
        assert (await s.execute(select(DealModel))).scalars().all() == []


async def test_several_matches_show_choice_buttons(bot_env):
    made = await add_clients(bot_env.maker, bot_env.ids, ("Лилия Север", "owner", 0), ("Лилия Юг", "owner", 0))
    bot_env.use_llm([call("create_deal", client="Лилия", amount=50)])
    state = fsm(TG["owner"])
    message, status = text_message(TG["owner"], "сделка для Лилии на 50")

    await ai_bot.handle_text(message, state)

    assert "Найдено несколько клиентов" in shown(status.edit_text)
    assert buttons(status.edit_text) == ["ai:pick:0", "ai:pick:1", "ai:no"]
    assert await state.get_state() == ai_bot.AIFlow.choose.state

    cb = callback(TG["owner"], "ai:pick:1")
    await ai_bot.pick_callback(cb, state)
    assert "Создать сделку" in shown(cb.message.edit_text) and buttons(cb.message.edit_text) == ["ai:ok", "ai:no"]
    assert await state.get_state() == ai_bot.AIFlow.confirm.state

    done = callback(TG["owner"], "ai:ok")
    await ai_bot.confirm_callback(done, state)
    async with bot_env.maker() as s:
        client_id = (await s.execute(select(DealModel.client_id))).scalar_one()
    assert client_id in made.values()


async def test_bad_choice_index_and_cancel_button(bot_env):
    await add_clients(bot_env.maker, bot_env.ids, ("Лилия Север", "owner", 0), ("Лилия Юг", "owner", 0))
    bot_env.use_llm([call("create_deal", client="Лилия")])
    state = fsm(TG["owner"])
    message, _ = text_message(TG["owner"], "сделка для Лилии")
    await ai_bot.handle_text(message, state)

    bad = callback(TG["owner"], "ai:pick:9")
    await ai_bot.pick_callback(bad, state)
    assert (
        bad.answer.await_args.kwargs.get("show_alert") is True and await state.get_state() == ai_bot.AIFlow.choose.state
    )

    cancel = callback(TG["owner"], "ai:no")
    await ai_bot.cancel_callback(cancel, state)
    assert shown(cancel.message.edit_text) == "❌ Отменено." and await state.get_state() is None


# ── безопасность и лимиты ────────────────────────────────────────────────────
async def test_someone_elses_button_press_is_rejected(bot_env):
    bot_env.use_llm([call("create_deal", client="Ромашка", amount=100)])
    state = fsm(TG["owner"])
    message, _ = text_message(TG["owner"], "сделка для Ромашки")
    await ai_bot.handle_text(message, state)

    stranger = callback(TG["other"], "ai:ok")  # чужое нажатие на то же состояние
    await ai_bot.confirm_callback(stranger, state)

    assert stranger.answer.await_args.kwargs.get("show_alert") is True
    stranger.message.edit_text.assert_not_awaited()
    async with bot_env.maker() as s:
        assert (await s.execute(select(DealModel))).scalars().all() == []


async def test_rate_limit_is_checked_before_the_llm(bot_env):
    bot_env.limiter.return_value = (False, 180)
    bot_env.use_llm([call("find_client", query="Ромашка")])
    message, _ = text_message(TG["owner"], "найди Ромашку")

    await ai_bot.handle_text(message, fsm(TG["owner"]))

    assert "Слишком много команд" in message.answer.await_args.args[0] and "3 мин" in message.answer.await_args.args[0]
    assert bot_env.llm.seen == []  # ни одного обращения к LLM
    bot_env.limiter.assert_awaited_once_with(bot_env.ids["owner"])


async def test_unknown_user_and_too_long_text_do_not_reach_the_llm(bot_env):
    bot_env.use_llm([call("find_client", query="X")])
    stranger, _ = text_message(999999, "найди Ромашку")
    await ai_bot.handle_text(stranger, fsm(999999))
    assert "нет доступа" in stranger.answer.await_args.args[0]

    long_text, _ = text_message(TG["owner"], "а" * (ai_bot.MAX_TEXT_LENGTH + 1))
    await ai_bot.handle_text(long_text, fsm(TG["owner"]))
    assert "Слишком длинное" in long_text.answer.await_args.args[0]
    assert bot_env.llm.seen == [] and bot_env.limiter.await_count == 0


async def test_llm_failure_is_reported_and_state_stays_clean(bot_env):
    class BrokenLLM:
        async def plan(self, *args, **kwargs):
            raise RuntimeError("groq down")

    bot_env.agent = AIAgent(default_registry(), BrokenLLM())
    state = fsm(TG["owner"])
    message, status = text_message(TG["owner"], "найди Ромашку")

    await ai_bot.handle_text(message, state)

    assert "Не удалось обработать" in shown(status.edit_text) and await state.get_state() is None


async def test_names_from_the_database_are_html_escaped(bot_env):
    await add_clients(bot_env.maker, bot_env.ids, ("<b>Хак</b> & Ко", "owner", 0))
    bot_env.use_llm([call("find_client", query="Хак")])
    message, status = text_message(TG["owner"], "найди Хак")

    await ai_bot.handle_text(message, fsm(TG["owner"]))

    assert "&lt;b&gt;Хак&lt;/b&gt; &amp; Ко" in shown(status.edit_text) and "<b>Хак</b>" not in shown(status.edit_text)


async def test_free_text_for_a_plain_user_cannot_create_clients(bot_env):
    bot_env.use_llm([call("create_client", name="Подделка")])
    message, status = text_message(TG["owner"], "создай клиента Подделка")
    await ai_bot.handle_text(message, fsm(TG["owner"]))
    assert "нет прав" in shown(status.edit_text)
    assert "create_client" not in bot_env.llm.seen[0]["tools"]
    async with bot_env.maker() as s:
        assert (await s.execute(select(ClientModel).where(ClientModel.name == "Подделка"))).first() is None


# ── голос ────────────────────────────────────────────────────────────────────
def voice_message(tg_id: int):
    message, status = text_message(tg_id, "")
    message.voice = SimpleNamespace(file_id="f1")
    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=SimpleNamespace(file_path="voice.ogg"))
    bot.download_file = AsyncMock()
    return message, status, bot


async def test_voice_read_scenario_uses_role_filtered_tools(bot_env):
    await add_clients(bot_env.maker, bot_env.ids, ("Давний клиент", "owner", 45))
    message, status, bot = voice_message(TG["owner"])
    stt = AsyncMock(
        return_value=("покажи клиентов без контакта больше месяца", [call("list_clients_without_contact", days=30)])
    )
    with patch.object(voice_bot, "process_voice_message", stt):
        await voice_bot.handle_voice(message, fsm(TG["owner"]), bot)

    result = shown(status.edit_text)
    assert "🎤" in result and "Давний клиент" in result
    tools = {t["function"]["name"] for t in stt.await_args.kwargs["tools"]}
    assert "list_clients_without_contact" in tools and "create_client" not in tools  # обычный сотрудник
    assert "больше месяца" in stt.await_args.kwargs["extra_hints"]


async def test_voice_write_scenario_asks_confirmation(bot_env):
    await add_user(bot_env.maker, bot_env.ids, "Петр")
    day, at = tomorrow_at(10)
    message, status, bot = voice_message(TG["a_manager"])
    calls = [call("create_task", title="Позвонить клиенту", assignee_username="Петр", deadline=day, deadline_time=at)]
    state = fsm(TG["a_manager"])
    with patch.object(
        voice_bot,
        "process_voice_message",
        AsyncMock(return_value=("создай задачу Петру позвонить клиенту завтра в 10", calls)),
    ):
        await voice_bot.handle_voice(message, state, bot)

    assert "создай задачу Петру" in shown(status.edit_text) and "Создать задачу" in shown(status.edit_text)
    assert buttons(status.edit_text) == ["ai:ok", "ai:no"] and await state.get_state() == ai_bot.AIFlow.confirm.state

    cb = callback(TG["a_manager"], "ai:ok")
    await ai_bot.confirm_callback(cb, state)
    assert shown(cb.message.edit_text).startswith("✅ Создана")


async def test_voice_text_only_answer_and_rate_limit(bot_env):
    message, status, bot = voice_message(TG["owner"])
    with patch.object(
        voice_bot,
        "process_voice_message",
        AsyncMock(return_value=("привет", [call("text_response", text="Здравствуйте!")])),
    ):
        await voice_bot.handle_voice(message, fsm(TG["owner"]), bot)
    assert "Здравствуйте!" in shown(status.edit_text)

    bot_env.limiter.return_value = (False, 60)
    blocked, _, bot2 = voice_message(TG["owner"])
    stt = AsyncMock()
    with patch.object(voice_bot, "process_voice_message", stt):
        await voice_bot.handle_voice(blocked, fsm(TG["owner"]), bot2)
    stt.assert_not_awaited()
    bot2.get_file.assert_not_awaited()


# ── мелочи ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("text", "expected"),
    [("да", "yes"), ("Да!", "yes"), (" ОК ", "yes"), ("👍", "yes"), ("нет", "no"), ("Отмена.", "no"), ("не надо", "no"),
     ("найди клиента Ромашка", None), ("давай позже", None), ("", None)],
)  # fmt: skip
def test_classify_reply(text, expected):
    assert ai_bot.classify_reply(text) == expected


def test_ai_router_is_registered_last():
    """Свободный текст отдаём AI только после меню, мастеров (FSM) и команд."""
    tree = ast.parse(Path("src/bot/handlers/__init__.py").read_text(encoding="utf8"))
    registered = [
        n.value.args[0].id
        for n in ast.walk(tree)
        if isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Call)
        and getattr(n.value.func, "attr", "") == "include_router"
    ]
    assert registered[-1] == "ai_assistant_router" and registered.index("voice_router") < registered.index(
        "commands_router"
    )


# ── какие сообщения вообще доходят до AI (фильтры aiogram) ───────────────────
def _real_message(text: str | None, chat_type: str = "private"):
    from datetime import datetime

    from aiogram.types import Chat, User

    return Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=10, type=chat_type),
        from_user=User(id=10, is_bot=False, first_name="T"),
        text=text,
    )


async def _matches(handler_fn, message, raw_state=None) -> bool:
    handler = next(h for h in ai_bot.router.message.handlers if h.callback is handler_fn)
    matched, _ = await handler.check(message, raw_state=raw_state)
    return matched


async def test_generic_text_handler_only_takes_free_private_text_without_state():
    handle = ai_bot.handle_text
    assert await _matches(handle, _real_message("покажи клиентов без контакта больше месяца"))
    assert not await _matches(handle, _real_message("/start"))  # команды — не AI
    assert not await _matches(handle, _real_message("текст", chat_type="group"))  # группы и мост не трогаем
    assert not await _matches(handle, _real_message("текст", chat_type="supergroup"))
    assert not await _matches(handle, _real_message(None))  # не текст (фото, голос…)
    assert not await _matches(handle, _real_message("название задачи"), raw_state="CreateTask:title")  # мастер (FSM)


async def test_reply_handlers_fire_only_in_their_own_state():
    msg = _real_message("да")
    assert await _matches(ai_bot.reply_to_confirmation, msg, raw_state=ai_bot.AIFlow.confirm.state)
    assert not await _matches(ai_bot.reply_to_confirmation, msg, raw_state=None)
    assert not await _matches(ai_bot.reply_to_confirmation, msg, raw_state=ai_bot.AIFlow.choose.state)
    assert await _matches(ai_bot.reply_while_choosing, msg, raw_state=ai_bot.AIFlow.choose.state)
    assert not await _matches(ai_bot.reply_while_choosing, msg, raw_state=ai_bot.AIFlow.confirm.state)


# ── рабочий клиент в Telegram: «найди клиента X» → «создай ему задачу» ───────────────────────────
async def test_bot_remembers_the_client_found_in_the_previous_message(bot_env):
    bot_env.use_llm([call("find_client", query="Ромашка")], [call("text_response", text="ок")])
    first, _ = text_message(TG["owner"], "найди клиента Ромашка")
    await ai_bot.handle_text(first, fsm(TG["owner"]))
    assert "Недавно" not in bot_env.llm.seen[0]["hints"]

    second, _ = text_message(TG["owner"], "создай ему задачу позвонить завтра")
    await ai_bot.handle_text(second, fsm(TG["owner"]))
    assert "Недавно в разговоре шла речь о клиенте «Ромашка»" in bot_env.llm.seen[1]["hints"]


async def test_bot_open_client_shows_the_summary_and_ignores_ui_actions(bot_env):
    bot_env.use_llm([call("open_client", client="Ромашка")])
    message, status = text_message(TG["owner"], "Открой карточку клиента Ромашка")
    await ai_bot.handle_text(message, fsm(TG["owner"]))
    assert "📇 Ромашка — компания" in shown(status.edit_text) and "Ответственный" in shown(status.edit_text)
