# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_ai_api.py
"""AI-ассистент в вебе (/api/ai/*): тот же реестр, права и подтверждения, что у бота; ожидание — на сервере.

Настоящие: БД, сервисы CRM, реестр, авторизация. Подменены: LLM (сценарий), Redis (fakeredis), лимитер и память
диалога. Проверяется протокол: команда → pending → confirm/choose → результат; чужие и устаревшие id не работают.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy import select

from src.ai import AIAgent, default_registry
from src.ai.pending_store import TTL_SECONDS, pending_store
from src.models.client import ClientModel
from src.models.deal import DealModel
from src.models.interaction import InteractionModel
from src.models.task import SpisokModel
from tests.test_ai_agent import FakeLLM, call
from tests.test_ai_tools import add_clients, add_user, tomorrow_at
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)


@pytest.fixture
async def ai(world):
    """Окружение: fakeredis вместо Redis, подменённые LLM/лимитер/память; план LLM задаёт тест."""
    maker, ids, logins = world
    fake = FakeAsyncRedis()
    env = type("Env", (), {})()
    env.maker, env.ids, env.logins, env.redis = maker, ids, logins, fake
    env.limiter = AsyncMock(return_value=(True, 0))
    env.memory = AsyncMock()
    env.llm = FakeLLM()
    env.agent = AIAgent(default_registry(), env.llm)

    def use_llm(*plans):
        env.llm = FakeLLM(*plans)
        env.agent = AIAgent(default_registry(), env.llm)

    env.use_llm = use_llm
    pending_store._memory.clear()
    patches = [
        patch("src.ai.pending_store.redis", fake),
        patch("src.routers.ai_router.get_agent", lambda: env.agent),
        patch("src.routers.ai_router.check_voice_rate_limit", env.limiter),
        patch("src.routers.ai_router.get_history", AsyncMock(return_value=[])),
        patch("src.routers.ai_router.add_message", env.memory),
    ]
    for p in patches:
        p.start()
    yield env
    for p in patches:
        p.stop()
    await fake.aclose()


async def say(client, ai, who, text, **extra):
    return await client.post(
        "/api/ai/message", json={"text": text, **extra}, headers=await _headers(client, ai.logins, who)
    )


async def answer(client, ai, who, path, **body):
    return await client.post(f"/api/ai/{path}", json=body, headers=await _headers(client, ai.logins, who))


# ── чтение ───────────────────────────────────────────────────────────────────
async def test_read_command_answers_immediately(client, ai):
    await add_clients(ai.maker, ai.ids, ("Давний клиент", "owner", 45))
    ai.use_llm([call("list_clients_without_contact", days=30)])
    resp = await say(client, ai, "owner", "покажи клиентов без контакта больше месяца")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pending"] is None and body["changed"] is False
    assert "Давний клиент" in body["messages"][0] and "дольше 30 дн." in body["messages"][0]
    assert ai.llm.seen[0]["text"] == "покажи клиентов без контакта больше месяца"


async def test_requires_auth_and_valid_text(client, ai):
    assert (await client.post("/api/ai/message", json={"text": "привет"})).status_code in (401, 403)
    for bad in ({"text": ""}, {"text": "   "}, {"text": "а" * 1001}, {}):
        resp = await client.post("/api/ai/message", json=bad, headers=await _headers(client, ai.logins, "owner"))
        assert resp.status_code == 422, bad


# ── запись: pending → confirm ────────────────────────────────────────────────
async def test_write_waits_for_confirmation_then_executes_once(client, ai):
    petr = await add_user(ai.maker, ai.ids, "Петр")
    day, at = tomorrow_at(10)
    ai.use_llm(
        [call("create_task", title="Позвонить клиенту", assignee_username="Петру", deadline=day, deadline_time=at)]
    )

    first = await say(client, ai, "a_manager", "создай задачу Петру позвонить клиенту завтра в 10")
    body = first.json()
    assert first.status_code == 200 and body["pending"]["kind"] == "confirm"
    assert "@Петр" in body["pending"]["text"] and "10:00" in body["pending"]["text"] and body["changed"] is False
    async with ai.maker() as s:  # без «да» задачи нет
        assert (await s.execute(select(SpisokModel))).scalars().all() == []

    pid = body["pending"]["id"]
    done = await answer(client, ai, "a_manager", "confirm", pending_id=pid, confirm=True)
    assert (
        done.status_code == 200
        and done.json()["messages"][0].startswith("✅ Создана")
        and done.json()["changed"] is True
    )
    async with ai.maker() as s:
        assert (await s.execute(select(SpisokModel.user_id))).scalar_one() == petr

    again = await answer(client, ai, "a_manager", "confirm", pending_id=pid, confirm=True)  # двойной клик
    assert again.status_code == 409
    async with ai.maker() as s:
        assert len((await s.execute(select(SpisokModel))).scalars().all()) == 1


async def test_no_cancels_and_changes_nothing(client, ai):
    ai.use_llm([call("create_deal", client="Ромашка", amount=100)])
    pid = (await say(client, ai, "owner", "сделка для Ромашки")).json()["pending"]["id"]
    resp = await answer(client, ai, "owner", "confirm", pending_id=pid, confirm=False)
    assert resp.status_code == 200 and resp.json()["messages"] == ["❌ Отменено."] and resp.json()["changed"] is False
    assert (await answer(client, ai, "owner", "confirm", pending_id=pid, confirm=True)).status_code == 409
    async with ai.maker() as s:
        assert (await s.execute(select(DealModel))).scalars().all() == []


async def test_failed_commit_is_reported_and_not_marked_changed(client, ai):
    ai.use_llm([call("create_deal", client="Ромашка", amount=100)])
    pid = (await say(client, ai, "owner", "сделка для Ромашки")).json()["pending"]["id"]
    async with ai.maker() as s:  # между вопросом и «да» клиента удалили
        row = (await s.execute(select(ClientModel).where(ClientModel.id == ai.ids["ca"]))).scalar_one()
        row.deleted_at = row.created_at
        await s.commit()
    resp = await answer(client, ai, "owner", "confirm", pending_id=pid, confirm=True)
    assert resp.status_code == 200 and resp.json()["messages"][0].startswith("❌") and resp.json()["changed"] is False


# ── выбор из нескольких ──────────────────────────────────────────────────────
async def test_choice_flow(client, ai):
    made = await add_clients(ai.maker, ai.ids, ("Лилия Север", "owner", 0), ("Лилия Юг", "owner", 0))
    ai.use_llm([call("create_deal", client="Лилия", amount=50)])
    first = (await say(client, ai, "owner", "сделка для Лилии на 50")).json()
    pending = first["pending"]
    assert pending["kind"] == "choose" and {o["id"] for o in pending["options"]} == set(made.values())

    wrong = await answer(client, ai, "owner", "choose", pending_id=pending["id"], option_id=999999)
    assert wrong.status_code == 422  # ожидание не потеряно
    picked = await answer(client, ai, "owner", "choose", pending_id=pending["id"], option_id=made["Лилия Юг"])
    assert picked.status_code == 200 and picked.json()["pending"]["kind"] == "confirm"
    assert "Лилия Юг" in picked.json()["pending"]["text"]

    done = await answer(client, ai, "owner", "confirm", pending_id=picked.json()["pending"]["id"], confirm=True)
    assert done.json()["changed"] is True
    async with ai.maker() as s:
        assert (await s.execute(select(DealModel.client_id))).scalar_one() == made["Лилия Юг"]


async def test_confirm_and_choose_are_not_interchangeable(client, ai):
    await add_clients(ai.maker, ai.ids, ("Лилия Север", "owner", 0), ("Лилия Юг", "owner", 0))
    ai.use_llm([call("create_deal", client="Лилия")])
    pid = (await say(client, ai, "owner", "сделка для Лилии")).json()["pending"]["id"]
    assert (await answer(client, ai, "owner", "confirm", pending_id=pid, confirm=True)).status_code == 409


# ── ожидание: замена, изоляция, срок жизни ───────────────────────────────────
async def test_new_command_replaces_the_pending_action(client, ai):
    ai.use_llm([call("create_deal", client="Ромашка", amount=100)], [call("find_client", query="Ромашка")])
    old = (await say(client, ai, "owner", "сделка для Ромашки")).json()["pending"]["id"]
    second = await say(client, ai, "owner", "найди Ромашку")
    assert second.json()["messages"][0] == "Предыдущее действие отменено."
    assert (await answer(client, ai, "owner", "confirm", pending_id=old, confirm=True)).status_code == 409
    async with ai.maker() as s:
        assert (await s.execute(select(DealModel))).scalars().all() == []


async def test_someone_elses_pending_id_does_not_work_and_does_not_destroy_it(client, ai):
    ai.use_llm([call("create_deal", client="Ромашка", amount=100)])
    pid = (await say(client, ai, "owner", "сделка для Ромашки")).json()["pending"]["id"]
    assert (await answer(client, ai, "other", "confirm", pending_id=pid, confirm=True)).status_code == 409
    assert (
        await answer(client, ai, "owner", "confirm", pending_id="чужой-или-старый", confirm=True)
    ).status_code == 409
    ok = await answer(client, ai, "owner", "confirm", pending_id=pid, confirm=True)  # настоящее ожидание уцелело
    assert ok.status_code == 200 and ok.json()["changed"] is True


async def test_pending_lives_in_redis_with_a_ttl_and_per_user_key(client, ai):
    ai.use_llm([call("create_deal", client="Ромашка", amount=100)])
    await say(client, ai, "owner", "сделка для Ромашки")
    keys = [k.decode() async for k in ai.redis.scan_iter(match="ai:pending:*")]
    assert keys == [f"ai:pending:{ai.ids['a']}:{ai.ids['owner']}"]
    assert 0 < await ai.redis.ttl(keys[0]) <= TTL_SECONDS
    payload = json.loads(await ai.redis.get(keys[0]))
    assert payload["pending"]["tool"] == "create_deal" and payload["pending"]["kind"] == "confirm"


async def test_works_without_redis_using_process_memory(client, ai):
    class BrokenRedis:
        async def set(self, *a, **k):
            raise ConnectionError("down")

        get = getdel = set

    ai.use_llm([call("create_deal", client="Ромашка", amount=100)])
    with patch("src.ai.pending_store.redis", BrokenRedis()):
        pid = (await say(client, ai, "owner", "сделка для Ромашки")).json()["pending"]["id"]
        done = await answer(client, ai, "owner", "confirm", pending_id=pid, confirm=True)
    assert done.status_code == 200 and done.json()["changed"] is True


# ── права, лимит, сбои ───────────────────────────────────────────────────────
async def test_roles_are_enforced_like_in_the_bot(client, ai):
    ai.use_llm([call("create_client", name="Подделка")], [call("create_client", name="Легально")])
    denied = await say(client, ai, "owner", "создай клиента Подделка")
    assert "нет прав" in denied.json()["messages"][0] and denied.json()["pending"] is None
    assert "create_client" not in ai.llm.seen[0]["tools"]
    allowed = await say(client, ai, "a_manager", "создай клиента Легально")
    assert allowed.json()["pending"]["kind"] == "confirm" and "create_client" in ai.llm.seen[1]["tools"]
    async with ai.maker() as s:
        assert (await s.execute(select(ClientModel).where(ClientModel.name == "Подделка"))).first() is None


async def test_rate_limit_is_shared_and_checked_before_the_llm(client, ai):
    ai.limiter.return_value = (False, 180)
    ai.use_llm([call("find_client", query="Ромашка")])
    resp = await say(client, ai, "owner", "найди Ромашку")
    assert resp.status_code == 429 and resp.headers["retry-after"] == "180" and "3 мин" in resp.json()["detail"]
    assert ai.llm.seen == []
    ai.limiter.assert_awaited_once_with(ai.ids["owner"])


async def test_llm_failure_is_a_502_without_side_effects(client, ai):
    class BrokenLLM:
        async def plan(self, *args, **kwargs):
            raise RuntimeError("groq down")

    ai.agent = AIAgent(default_registry(), BrokenLLM())
    resp = await say(client, ai, "owner", "найди Ромашку")
    assert resp.status_code == 502 and "Не удалось обработать" in resp.json()["detail"]


async def test_conversation_memory_is_shared_with_the_bot(client, ai):
    ai.use_llm([call("find_client", query="Ромашка")])
    await say(client, ai, "owner", "найди Ромашку")
    roles = [c.args[1] for c in ai.memory.await_args_list]
    assert roles == ["user", "assistant"]


# ── контекст экрана: открытая карточка клиента ───────────────────────────────
async def test_open_client_card_gives_context_to_the_model_and_the_tools(client, ai):
    # Модель не назвала клиента («создай заметку: просили скидку») — берётся клиент с экрана
    ai.use_llm([call("add_note", text="Просили скидку 5%")])
    resp = await say(client, ai, "owner", "запиши: просили скидку 5%", context={"client_id": ai.ids["ca"]})
    body = resp.json()
    assert resp.status_code == 200 and body["pending"]["kind"] == "confirm" and "«Ромашка»" in body["pending"]["text"]
    assert "Контекст экрана" in ai.llm.seen[0]["hints"] and "«Ромашка»" in ai.llm.seen[0]["hints"]

    done = await answer(client, ai, "owner", "confirm", pending_id=body["pending"]["id"], confirm=True)
    assert done.json()["changed"] is True
    async with ai.maker() as s:
        assert (await s.execute(select(InteractionModel.client_id))).scalar_one() == ai.ids["ca"]


async def test_no_context_means_no_hint_and_the_tool_asks_for_a_client(client, ai):
    ai.use_llm([call("add_note", text="Без клиента")])
    resp = await say(client, ai, "owner", "запиши заметку")
    assert "Контекст экрана" not in ai.llm.seen[0]["hints"]
    assert "о каком клиенте" in resp.json()["messages"][0]


async def test_foreign_or_missing_client_in_context_is_rejected(client, ai):
    for bad in (999999, ai.ids["cb"]):  # cb — клиент другой компании
        resp = await say(client, ai, "owner", "привет", context={"client_id": bad})
        assert resp.status_code == 404, bad
    assert ai.llm.seen == [] and ai.limiter.await_count == 0


# ── «Открой карточку клиента …» и рабочий клиент (по живой переписке в панели) ─────────────────────
async def test_open_client_returns_a_ui_action_with_the_summary(client, ai):
    ai.use_llm([call("open_client", client="Ромашка")])
    body = (await say(client, ai, "owner", "Открой карточку клиента Ромашка")).json()
    assert body["actions"] == [{"type": "open_client", "client_id": ai.ids["ca"]}]
    assert body["messages"][0].startswith("📇 Ромашка — компания") and body["pending"] is None


async def test_the_client_just_discussed_carries_over_to_the_next_message(client, ai):
    ai.use_llm([call("find_client", query="Ромашка")], [call("add_note", text="Просили скидку")])
    await say(client, ai, "owner", "найди клиента Ромашка")
    second = await say(client, ai, "owner", "запиши: просили скидку")
    assert "Недавно в разговоре шла речь о клиенте «Ромашка»" in ai.llm.seen[1]["hints"]
    assert "Контекст экрана" not in ai.llm.seen[1]["hints"]
    assert second.json()["pending"]["kind"] == "confirm" and "«Ромашка»" in second.json()["pending"]["text"]


async def test_open_card_beats_the_recent_client_and_other_users_have_their_own_thread(client, ai):
    made = await add_clients(ai.maker, ai.ids, ("Лютик", "owner", 0))
    ai.use_llm(
        [call("find_client", query="Ромашка")], [call("text_response", text="ок")], [call("text_response", text="ок")]
    )
    await say(client, ai, "owner", "найди клиента Ромашка")
    await say(client, ai, "owner", "что тут?", context={"client_id": made["Лютик"]})
    assert "Контекст экрана" in ai.llm.seen[1]["hints"] and "«Лютик»" in ai.llm.seen[1]["hints"]
    await say(client, ai, "other", "привет")  # у другого сотрудника «рабочего клиента» нет
    assert "Недавно" not in ai.llm.seen[2]["hints"] and "Контекст экрана" not in ai.llm.seen[2]["hints"]


async def test_live_chat_scenario_open_card_then_create_task_over_http(client, ai):
    day, at = tomorrow_at(10)
    ai.use_llm(
        [call("open_client", client="Ромашка")],
        [call("create_task", title="Позвонить", client="Ромашка", deadline=day, deadline_time=at)],
    )
    opened = (await say(client, ai, "owner", "Открой карточку клиента Ромашка")).json()
    assert opened["actions"][0]["client_id"] == ai.ids["ca"]
    ask = (
        await say(client, ai, "owner", "создай задачу позвонить завтра в 10", context={"client_id": ai.ids["ca"]})
    ).json()
    assert "клиент «Ромашка»" in ask["pending"]["text"]
    done = (await answer(client, ai, "owner", "confirm", pending_id=ask["pending"]["id"], confirm=True)).json()
    assert done["changed"] is True and "👤 Ромашка" in done["messages"][0]
    async with ai.maker() as s:
        assert (await s.execute(select(SpisokModel.client_id))).scalar_one() == ai.ids["ca"]
