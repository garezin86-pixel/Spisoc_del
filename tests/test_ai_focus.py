# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_ai_focus.py
"""«Открой карточку клиента …», «рабочий клиент» диалога и честность ответов (по живой переписке в веб-панели).

Было: ассистент отвечал «Открываю карточку клиента X», хотя такого инструмента не было, а следующая команда
«создай задачу позвонить завтра в 10» создавала задачу без клиента. Теперь: инструмент open_client (сводка + команда
интерфейсу) и клиент, о котором только что говорили, подставляется в следующие команды (подсказка модели; открытая
карточка — ещё и жёстко).
"""

import json
from unittest.mock import AsyncMock, patch

from fakeredis import FakeAsyncRedis
from sqlalchemy import select

from src.ai import AIAgent, default_registry
from src.ai.focus_store import TTL_SECONDS, focus_store
from src.ai.llm import build_hints
from src.models.client import ClientModel
from src.models.interaction import InteractionModel
from src.models.task import SpisokModel
from tests.test_ai_agent import FakeLLM, call
from tests.test_ai_tools import add_clients, ai_ctx, commit, make_deal, tomorrow_at
from tests.test_ai_tools import call as run_tool
from tests.test_clients import world  # noqa: F401  (world — фикстура)


# ── open_client ──────────────────────────────────────────────────────────────
async def test_open_client_summary_and_ui_action(world):
    maker, ids, _ = world
    await make_deal(maker, ids)
    async with ai_ctx(maker, ids, "owner") as ctx:
        await commit(ctx, await run_tool(ctx, "create_task", title="Позвонить", client="Ромашка"))
        async with maker() as s:
            s.add(InteractionModel(client_id=ids["ca"], type="call", workspace_id=ids["a"], occurred_at=ctx.now()))
            await s.commit()
        out = await run_tool(ctx, "open_client", client="ооо ромашка")
    assert out.actions == [{"type": "open_client", "client_id": ids["ca"]}]
    assert out.text.startswith("📇 Ромашка — компания") and "Ответственный: @" in out.text
    assert "Сделок: 1 · открытых задач: 1 · последний контакт: " in out.text and "контактов ещё не было" not in out.text


async def test_open_client_without_history_unknown_and_ambiguous(world):
    maker, ids, _ = world
    await add_clients(maker, ids, ("Лилия Север", "owner", 0), ("Лилия Юг", "owner", 0))
    async with ai_ctx(maker, ids, "other") as ctx:  # читать карточки могут все сотрудники
        quiet = await run_tool(ctx, "open_client", client="Ромашка")
        assert "Сделок: 0 · открытых задач: 0 · последний контакт: контактов ещё не было" in quiet.text
        assert "не найден" in (await run_tool(ctx, "open_client", client="Несуществующий")).text
        choose = await run_tool(ctx, "open_client", client="Лилия")
        assert choose.param == "_client_id" and len(choose.options) == 2
        picked = await run_tool(ctx, "open_client", **{**choose.args, choose.param: choose.options[1][0]})
        assert picked.actions[0]["client_id"] == choose.options[1][0]


async def test_actions_travel_through_the_agent(world):
    maker, ids, _ = world
    agent = AIAgent(default_registry(), FakeLLM([call("open_client", client="Ромашка")]))
    async with ai_ctx(maker, ids, "owner") as ctx:
        turn = await agent.handle_text(ctx, "Открой карточку клиента Ромашка", [])
    assert turn.pending is None and turn.actions == [{"type": "open_client", "client_id": ids["ca"]}]
    assert "📇 Ромашка" in turn.messages[0]


def test_the_model_is_told_not_to_claim_actions_it_did_not_perform():
    text = build_hints(default_registry().hints(type("U", (), {"role": "user"})()))
    assert "Не пиши «открываю»" in text and "open_client" in text


# ── рабочий клиент ───────────────────────────────────────────────────────────
async def test_found_or_opened_client_becomes_the_working_client(world):
    maker, ids, _ = world
    await add_clients(maker, ids, ("Лилия Север", "owner", 0), ("Лилия Юг", "owner", 0))
    async with ai_ctx(maker, ids, "owner") as ctx:
        await run_tool(ctx, "find_client", query="Лилия")  # два результата — рабочего клиента нет
        assert await focus_store.recall(ids["a"], ids["owner"]) is None
        await run_tool(ctx, "find_client", query="Ромашка")
        assert await focus_store.recall(ids["a"], ids["owner"]) == ids["ca"]
    async with ai_ctx(maker, ids, "owner") as fresh:  # новое сообщение — новый контекст
        assert fresh.focus_client_id is None
        await fresh.load_recent_focus()
        assert (fresh.focus_client_id, fresh.focus_client_name, fresh.focus_source) == (ids["ca"], "Ромашка", "recent")
        hint = fresh.focus_hint()
        assert "Недавно в разговоре шла речь о клиенте «Ромашка»" in hint and "Контекст экрана" not in hint
    async with ai_ctx(maker, ids, "other") as someone:  # у другого сотрудника свой разговор
        await someone.load_recent_focus()
        assert someone.focus_client_id is None and someone.focus_hint() == ""


async def test_screen_context_beats_the_recent_client(world):
    maker, ids, _ = world
    await add_clients(maker, ids, ("Лютик", "owner", 0))
    async with ai_ctx(maker, ids, "owner") as ctx:
        await run_tool(ctx, "open_client", client="Лютик")
    async with ai_ctx(maker, ids, "owner") as screen:
        screen.focus_client_id, screen.focus_client_name = ids["ca"], "Ромашка"  # карточка Ромашки открыта
        await screen.load_recent_focus()
        assert screen.focus_client_name == "Ромашка" and "Контекст экрана" in screen.focus_hint()


async def test_deleted_client_is_forgotten(world):
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "owner") as ctx:
        await run_tool(ctx, "find_client", query="Ромашка")
    async with maker() as s:
        row = (await s.execute(select(ClientModel).where(ClientModel.id == ids["ca"]))).scalar_one()
        row.deleted_at = row.created_at
        await s.commit()
    async with ai_ctx(maker, ids, "owner") as ctx:
        await ctx.load_recent_focus()
        assert ctx.focus_client_id is None
    assert await focus_store.recall(ids["a"], ids["owner"]) is None


async def test_focus_store_redis_ttl_and_memory_fallback():
    fake = FakeAsyncRedis()
    with patch("src.ai.focus_store.redis", fake):
        await focus_store.remember(7, 3, 42)
        assert await focus_store.recall(7, 3) == 42
        assert 0 < await fake.ttl("ai:focus:7:3") <= TTL_SECONDS
        await focus_store.forget(7, 3)
        assert await focus_store.recall(7, 3) is None
    await fake.aclose()

    class Broken:
        async def set(self, *a, **k):
            raise ConnectionError("down")

        get = delete = set

    with patch("src.ai.focus_store.redis", Broken()):
        await focus_store.remember(7, 3, 43)
        assert await focus_store.recall(7, 3) == 43  # без Redis — в памяти процесса


# ── задача без названия клиента ──────────────────────────────────────────────
async def test_open_card_links_the_task_even_if_the_command_names_no_client(world):
    maker, ids, _ = world
    day, at = tomorrow_at(10)
    async with ai_ctx(maker, ids, "owner") as ctx:
        ctx.focus_client_id, ctx.focus_client_name = ids["ca"], "Ромашка"  # открыта карточка (экран)
        out = await run_tool(ctx, "create_task", title="Позвонить", deadline=day, deadline_time=at)
        assert "клиент «Ромашка»" in out.text
        await commit(ctx, out)
    async with maker() as s:
        assert (await s.execute(select(SpisokModel.client_id))).scalar_one() == ids["ca"]


async def test_recent_client_alone_does_not_silently_link_a_task(world):
    """Недавний разговор — подсказка модели, а не повод привязывать «купить воду» к прежнему клиенту."""
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "owner") as ctx:
        ctx.focus_client_id, ctx.focus_client_name, ctx.focus_source = ids["ca"], "Ромашка", "recent"
        out = await run_tool(ctx, "create_task", title="Купить воду")
        assert "клиент" not in out.text
        named = await run_tool(ctx, "create_task", title="Позвонить", client="Ромашка")  # а модель по подсказке назовёт
        assert "клиент «Ромашка»" in named.text


# ── сквозной сценарий из живой переписки ─────────────────────────────────────
async def test_the_live_chat_scenario_open_card_then_create_task(world):
    maker, ids, _ = world
    day, at = tomorrow_at(10)
    plans = [
        [call("open_client", client="Ромашка")],
        [call("create_task", title="Позвонить", client="Ромашка", deadline=day, deadline_time=at)],
    ]
    llm = FakeLLM(*plans)
    agent = AIAgent(default_registry(), llm)
    async with ai_ctx(maker, ids, "owner") as ctx:  # сообщение 1 (в вебе: интерфейс откроет карточку)
        first = await agent.handle_text(ctx, "Открой карточку клиента Ромашка", [])
        assert first.actions[0]["client_id"] == ids["ca"] and "Открываю" not in first.messages[0]
    async with ai_ctx(maker, ids, "owner") as ctx:  # сообщение 2: клиент подтянулся из разговора
        await ctx.load_recent_focus()
        second = await agent.handle_text(ctx, "создай задачу позвонить завтра в 10", [])
        assert "Недавно в разговоре шла речь о клиенте «Ромашка»" in llm.seen[1]["hints"]
        assert second.pending is not None and "клиент «Ромашка»" in second.pending.text
        done = await agent.confirm(ctx, second.pending)
    assert done.messages[0].startswith("✅ Создана") and "👤 Ромашка" in done.messages[0]
    async with maker() as s:
        assert (await s.execute(select(SpisokModel.client_id))).scalar_one() == ids["ca"]
    assert json.loads(json.dumps(first.actions)) == first.actions  # действия сериализуются для ответа API
    assert AsyncMock  # импорт нужен другим тестам этого файла при расширении
