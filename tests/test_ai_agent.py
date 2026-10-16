# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_ai_agent.py
"""Агент AI (Этап 5): фраза → вызовы инструментов → подтверждение / выбор. LLM подменена сценарием (без сети и Groq).

Здесь же оба сценария «Готово, когда» из плана и проверка архитектуры: пакет src/ai не знает про aiogram и бота.
"""

import ast
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from src.ai import AIAgent, Pending, ToolCall, default_registry
from src.models.client import ClientModel
from src.models.deal import DealModel
from src.models.task import SpisokModel
from tests.test_ai_tools import add_clients, add_user, ai_ctx, tomorrow_at
from tests.test_clients import world  # noqa: F401  (world — фикстура)


class FakeLLM:
    """Выдаёт заранее заданные ответы и запоминает, что получила от агента."""

    def __init__(self, *plans):
        self.plans = list(plans)
        self.seen = []

    async def plan(self, text, history, *, tools, hints):
        self.seen.append({"text": text, "tools": [t["function"]["name"] for t in tools], "hints": hints})
        return self.plans.pop(0)


def call(tool, /, **arguments):
    return {"name": tool, "arguments": arguments}


def agent_with(*plans):
    llm = FakeLLM(*plans)
    return AIAgent(default_registry(), llm), llm


# ── сценарии из плана ────────────────────────────────────────────────────────
async def test_scenario_clients_without_contact_for_a_month(world):
    maker, ids, _ = world
    await add_clients(maker, ids, ("Давний клиент", "owner", 45))
    agent, llm = agent_with([call("list_clients_without_contact", days=30)])
    async with ai_ctx(maker, ids, "owner") as ctx:
        turn = await agent.handle_text(ctx, "покажи клиентов без контакта больше месяца", [])
    assert turn.pending is None  # чтение — без подтверждения
    assert "Давний клиент" in turn.messages[0] and "дольше 30 дн." in turn.messages[0]
    assert llm.seen[0]["text"] == "покажи клиентов без контакта больше месяца"


async def test_scenario_task_for_colleague_tomorrow_at_ten(world):
    maker, ids, _ = world
    petr = await add_user(maker, ids, "Петр")
    day, at = tomorrow_at(10)
    agent, _ = agent_with(
        [call("create_task", title="Позвонить клиенту", assignee_username="Петр", deadline=day, deadline_time=at)]
    )
    async with ai_ctx(maker, ids, "a_manager") as ctx:
        turn = await agent.handle_text(ctx, "создай задачу Петру позвонить клиенту завтра в 10", [])
        assert turn.pending is not None and turn.pending.kind == "confirm"
        assert "@Петр" in turn.pending.text and "10:00" in turn.pending.text
        async with maker() as s:  # без «да» ничего не создано
            assert (await s.execute(select(SpisokModel))).scalars().all() == []

        done = await agent.confirm(ctx, turn.pending)
    assert done.pending is None and done.messages[0].startswith("✅ Создана")
    async with maker() as s:
        task = (await s.execute(select(SpisokModel))).scalars().one()
    assert (task.title, task.user_id) == ("Позвонить клиенту", petr)


# ── подтверждение, отмена, очередь ───────────────────────────────────────────
async def test_cancel_leaves_database_untouched(world):
    maker, ids, _ = world
    agent, _ = agent_with([call("create_deal", client="Ромашка", amount=100)])
    async with ai_ctx(maker, ids, "owner") as ctx:
        turn = await agent.handle_text(ctx, "сделка для Ромашки на 100", [])
        assert turn.pending is not None
    assert AIAgent.cancel().messages == ["❌ Отменено."]
    async with maker() as s:
        assert (await s.execute(select(DealModel))).scalars().all() == []


async def test_queue_waits_for_each_confirmation(world):
    """«Создай клиента и сделку для него»: сделка готовится только после того, как клиент создан."""
    maker, ids, _ = world
    agent, _ = agent_with(
        [call("create_client", name="Новая Фирма"), call("create_deal", client="Новая Фирма", amount=100)]
    )
    async with ai_ctx(maker, ids, "a_manager") as ctx:
        first = await agent.handle_text(ctx, "создай клиента Новая Фирма и сделку на 100", [])
        assert first.pending.tool == "create_client" and len(first.pending.queue) == 1

        second = await agent.confirm(ctx, first.pending)
        assert second.messages[0].startswith("✅ Клиент")
        assert second.pending is not None and second.pending.tool == "create_deal"  # клиент уже найден

        final = await agent.confirm(ctx, second.pending)
        assert final.pending is None and final.messages[0].startswith("✅ Сделка")
    async with maker() as s:
        client = (await s.execute(select(ClientModel).where(ClientModel.name == "Новая Фирма"))).scalar_one()
        deal = (await s.execute(select(DealModel))).scalars().one()
    assert deal.client_id == client.id


async def test_refusal_stops_the_rest_of_the_phrase(world):
    maker, ids, _ = world
    agent, _ = agent_with([call("create_deal", client="Несуществующий"), call("create_client", name="Лишний")])
    async with ai_ctx(maker, ids, "a_manager") as ctx:
        turn = await agent.handle_text(ctx, "…", [])
    assert turn.pending is None and len(turn.messages) == 1 and "не найден" in turn.messages[0]
    async with maker() as s:
        assert (await s.execute(select(ClientModel).where(ClientModel.name == "Лишний"))).first() is None


async def test_failed_commit_drops_dependent_calls(world):
    maker, ids, _ = world
    agent, _ = agent_with()
    # Подтверждение, ссылающееся на клиента другой компании: сервис отвечает 404, очередь не выполняется
    pending = Pending(
        "confirm", "create_deal", {"client_id": ids["cb"], "client_name": "Лютик", "title": "Х"}, "?",
        queue=[call("create_client", name="Зависимый")],
    )  # fmt: skip
    async with ai_ctx(maker, ids, "a_manager") as ctx:
        turn = await agent.confirm(ctx, pending)
    assert turn.messages[0].startswith("❌") and len(turn.messages) == 1 and turn.pending is None
    async with maker() as s:
        assert (await s.execute(select(ClientModel).where(ClientModel.name == "Зависимый"))).first() is None


async def test_call_limit_per_phrase(world):
    maker, ids, _ = world
    agent, _ = agent_with([call("find_client", query="Ромашка")] * 8)
    async with ai_ctx(maker, ids, "owner") as ctx:
        turn = await agent.handle_text(ctx, "…", [])
    assert len(turn.messages) == 5


# ── выбор из нескольких ──────────────────────────────────────────────────────
async def test_choice_flow_and_serialization(world):
    maker, ids, _ = world
    made = await add_clients(maker, ids, ("Лилия Север", "owner", 0), ("Лилия Юг", "owner", 0))
    agent, _ = agent_with([call("create_deal", client="Лилия", amount=10)])
    async with ai_ctx(maker, ids, "owner") as ctx:
        turn = await agent.handle_text(ctx, "сделка для Лилии на 10", [])
        assert turn.pending.kind == "choose" and {i for i, _ in turn.pending.options} == set(made.values())

        # ожидание переживает хранение между сообщениями (FSM бота, Redis, ответ API)
        stored = json.loads(json.dumps(turn.pending.to_dict()))
        pending = Pending.from_dict(stored)

        wrong = await agent.choose(ctx, pending, 999999)
        assert wrong.messages == ["❌ Такого варианта нет."] and wrong.pending is pending

        picked = await agent.choose(ctx, pending, made["Лилия Юг"])
        assert picked.pending.kind == "confirm" and "Лилия Юг" in picked.pending.text
        done = await agent.confirm(ctx, Pending.from_dict(json.loads(json.dumps(picked.pending.to_dict()))))
    assert done.messages[0].startswith("✅ Сделка")
    async with maker() as s:
        assert (await s.execute(select(DealModel.client_id))).scalar_one() == made["Лилия Юг"]


async def test_confirm_on_a_choice_does_nothing(world):
    maker, ids, _ = world
    agent, _ = agent_with()
    async with ai_ctx(maker, ids, "owner") as ctx:
        turn = await agent.confirm(ctx, Pending("choose", "create_deal", {}, "?", "_client_id", [(1, "A")]))
    assert turn.messages == ["❌ Сейчас нечего подтверждать."]


# ── права: LLM не обходит роли ───────────────────────────────────────────────
async def test_llm_sees_only_tools_allowed_for_the_user(world):
    maker, ids, _ = world
    agent, llm = agent_with([call("text_response", text="ок")], [call("text_response", text="ок")])
    async with ai_ctx(maker, ids, "owner") as plain:
        await agent.handle_text(plain, "привет", [])
    async with ai_ctx(maker, ids, "a_manager") as manager:
        await agent.handle_text(manager, "привет", [])
    plain_tools, manager_tools = llm.seen[0]["tools"], llm.seen[1]["tools"]
    assert "create_client" not in plain_tools and "create_client" in manager_tools
    assert "create_client" not in llm.seen[0]["hints"] and "create_client" in llm.seen[1]["hints"]
    assert {"find_client", "create_deal", "create_task", "list_clients_without_contact"} <= set(plain_tools)


async def test_hallucinated_forbidden_tool_is_refused_and_does_nothing(world):
    maker, ids, _ = world
    agent, _ = agent_with([call("create_client", name="Подделка")], [call("несуществующий_инструмент")])
    async with ai_ctx(maker, ids, "owner") as ctx:
        turn = await agent.handle_text(ctx, "создай клиента Подделка", [])
        assert turn.pending is None and "нет прав" in turn.messages[0]
        unknown = await agent.handle_text(ctx, "…", [])
        assert "Неизвестная команда" in unknown.messages[0]
    async with maker() as s:
        assert (await s.execute(select(ClientModel).where(ClientModel.name == "Подделка"))).first() is None


async def test_rights_are_checked_again_at_commit(world):
    """Подтверждение, полученное менеджером, не исполняется от имени обычного сотрудника."""
    maker, ids, _ = world
    agent, _ = agent_with([call("create_client", name="Через подмену")])
    async with ai_ctx(maker, ids, "a_manager") as manager:
        turn = await agent.handle_text(manager, "…", [])
    async with ai_ctx(maker, ids, "owner") as plain:
        done = await agent.confirm(plain, turn.pending)
    assert done.messages[0].startswith("⛔")
    async with maker() as s:
        assert (await s.execute(select(ClientModel).where(ClientModel.name == "Через подмену"))).first() is None


# ── прочее ───────────────────────────────────────────────────────────────────
async def test_text_response_passthrough_and_missing_llm(world):
    maker, ids, _ = world
    agent, _ = agent_with([call("text_response", text="Уточните, какого клиента?")])
    async with ai_ctx(maker, ids, "owner") as ctx:
        assert (await agent.handle_text(ctx, "…", [])).messages == ["Уточните, какого клиента?"]
        with pytest.raises(RuntimeError):
            await AIAgent(default_registry()).handle_text(ctx, "…", [])
        run = await AIAgent(default_registry()).run_calls(ctx, [ToolCall("find_client", {"query": "Ромашка"})])
        assert "Ромашка" in run.messages[0]  # голос: вызовы приходят уже готовыми


# ── архитектура ──────────────────────────────────────────────────────────────
def _imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_ai_package_does_not_depend_on_aiogram_or_the_bot():
    """Реестр инструментов — общий для бота, веба и API: в нём нет ни aiogram, ни обращений к src.bot."""
    files = list(Path("src/ai").rglob("*.py"))
    assert len(files) >= 8
    for path in files:
        bad = {m for m in _imports(path) if m.split(".")[0] == "aiogram" or m.startswith("src.bot")}
        assert not bad, f"{path} зависит от {bad}"


def test_tools_call_services_not_raw_sql_for_crm_writes():
    """Пишущие CRM-инструменты идут через сервисы: ни одного session.add/insert в src/ai."""
    for path in Path("src/ai").rglob("*.py"):
        text = path.read_text(encoding="utf8")
        assert "session.add" not in text and "insert(" not in text, path
