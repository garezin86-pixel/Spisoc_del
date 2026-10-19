# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_ai_tools.py
"""AI-инструменты CRM (Этап 5): чтение сразу, запись — Confirm → commit, выбор из нескольких, права инструмента.

Инструменты вызываются через реестр с настоящей БД (сессия привязана к компании, как в боте) и сервисами CRM.
LLM здесь не участвует: проверяется то, что происходит после выбора инструмента.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.ai import AIContext, Choose, Confirm, Done, Refuse, ToolCall, default_registry
from src.ai.context import LOCAL_TZ
from src.db.unit_of_work import UnitOfWork
from src.models.client import ClientModel
from src.models.deal import DealModel
from src.models.interaction import InteractionModel
from src.models.task import SpisokModel
from src.models.user import UserModel
from src.schemas.deal import DealCreate
from tests.test_clients import world  # noqa: F401  (world — фикстура)


@asynccontextmanager
async def ai_ctx(maker, ids, who, now=None):
    async with UnitOfWork(maker, workspace_id=ids["a"]) as uow:
        user = await uow.users.get_by_id(ids[who])
        yield AIContext(user=user, session=uow.session, _now=now)


async def call(ctx, tool, /, **args):
    return await default_registry().run(ctx, ToolCall(tool, args))


async def commit(ctx, confirm: Confirm) -> str:
    return await default_registry().commit(ctx, confirm.tool, confirm.args)


async def add_clients(maker, ids, *specs):
    """specs: (name, owner_key, days_old) → id клиента."""
    out = {}
    async with maker() as s:
        for name, owner, days_old in specs:
            c = ClientModel(
                name=name,
                workspace_id=ids["a"],
                owner_id=ids[owner],
                created_at=datetime.now(timezone.utc) - timedelta(days=days_old),
            )
            s.add(c)
            await s.commit()
            out[name] = c.id
    return out


async def add_user(maker, ids, username, role="user"):
    async with maker() as s:
        u = UserModel(
            username=username, login=f"{username}_{uuid.uuid4().hex[:6]}", password_hash="x", role=role,
            workspace_id=ids["a"],
        )  # fmt: skip
        s.add(u)
        await s.commit()
        return u.id


def tomorrow_at(hour: int, minute: int = 0) -> tuple[str, str]:
    day = (datetime.now(LOCAL_TZ) + timedelta(days=1)).date()
    return day.isoformat(), f"{hour:02d}:{minute:02d}"


# ── реестр и права ───────────────────────────────────────────────────────────
async def test_plain_user_is_not_offered_create_client(world):
    maker, ids, _ = world
    registry = default_registry()
    async with ai_ctx(maker, ids, "owner") as plain, ai_ctx(maker, ids, "a_manager") as manager:
        assert "create_client" not in {t["function"]["name"] for t in registry.definitions(plain.user)}
        assert "create_client" in {t["function"]["name"] for t in registry.definitions(manager.user)}
        # LLM «придумала» недоступный инструмент — отказ на уровне инструмента, ничего не создаётся
        out = await call(plain, "create_client", name="Хакер")
        assert isinstance(out, Refuse) and "нет прав" in out.text


async def test_every_tool_declares_a_valid_schema():
    registry = default_registry()
    names = registry.names()
    assert len(names) == len(set(names)) and len(names) >= 8
    for tool in registry.available(type("U", (), {"role": "admin"})()):
        params = tool.parameters
        assert params["type"] == "object"
        assert set(params.get("required", [])) <= set(params["properties"]), tool.name
        assert tool.description


# ── find_client ──────────────────────────────────────────────────────────────
async def test_find_client_tolerates_legal_form_case_and_hides_other_company(world):
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "owner") as ctx:
        for query in ("Ромашка", "ооо ромашка", "РОМАШКА"):
            out = await call(ctx, "find_client", query=query)
            assert isinstance(out, Done) and "Ромашка" in out.text, query
        assert "не найден" in (await call(ctx, "find_client", query="Лютик")).text  # клиент другой компании
        assert isinstance(await call(ctx, "find_client", query=""), Refuse)


# ── list_clients_without_contact ─────────────────────────────────────────────
async def test_clients_without_contact_month(world):
    maker, ids, _ = world
    made = await add_clients(maker, ids, ("Старый", "owner", 40), ("Свежий", "owner", 40), ("Чужой", "other", 50))
    async with maker() as s:
        s.add(
            InteractionModel(
                client_id=made["Свежий"], type="call", workspace_id=ids["a"],
                occurred_at=datetime.now(timezone.utc) - timedelta(days=2),
            )
        )  # fmt: skip
        await s.commit()

    async with ai_ctx(maker, ids, "owner") as ctx:
        out = await call(ctx, "list_clients_without_contact", days=30)
        assert isinstance(out, Done)
        assert "Старый" in out.text and "контактов ещё не было" in out.text
        assert "Свежий" not in out.text and "Ромашка" not in out.text and "Чужой" not in out.text
        assert "дольше 30 дн.: 1" in out.text
        # обычный сотрудник не видит чужих, даже если попросил «всех»
        note = await call(ctx, "list_clients_without_contact", days=30, all_owners=True)
        assert "Чужой" not in note.text and "смотреть чужих могут" in note.text
    async with ai_ctx(maker, ids, "a_manager") as ctx:
        out = await call(ctx, "list_clients_without_contact", days=30, all_owners=True)
        assert "Чужой" in out.text and "Старый" in out.text and "всех ответственных" in out.text


async def test_clients_without_contact_validation_and_empty(world):
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "owner") as ctx:
        assert isinstance(await call(ctx, "list_clients_without_contact", days=0), Refuse)
        assert isinstance(await call(ctx, "list_clients_without_contact", days="много"), Refuse)
        assert "Нет ваших клиентов" in (await call(ctx, "list_clients_without_contact", days=30)).text


# ── create_client ────────────────────────────────────────────────────────────
async def test_create_client_needs_confirmation_and_warns_about_duplicate(world):
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "a_manager") as ctx:
        out = await call(ctx, "create_client", name="Ромашка", phone="+380501112233")
        assert isinstance(out, Confirm) and "уже есть" in out.text  # предупреждение, но не запрет
        async with maker() as s:  # до «да» ничего не записано
            assert (
                await s.execute(select(ClientModel).where(ClientModel.name == "Ромашка"))
            ).scalars().all().__len__() == 1

        result = await commit(ctx, out)
        assert result.startswith("✅")
        out2 = await call(ctx, "create_client", name="Новый клиент")
        assert isinstance(out2, Confirm) and "уже есть" not in out2.text
        await commit(ctx, out2)
    async with maker() as s:
        names = (await s.execute(select(ClientModel.name, ClientModel.owner_id))).all()
    assert ("Новый клиент", ids["a_manager"]) in names


async def test_create_client_validation(world):
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "a_manager") as ctx:
        assert isinstance(await call(ctx, "create_client", name="   "), Refuse)
        assert isinstance(await call(ctx, "create_client", name="X", client_type="alien"), Refuse)


# ── create_deal ──────────────────────────────────────────────────────────────
async def test_create_deal_confirm_text_and_commit(world):
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "owner") as ctx:
        out = await call(ctx, "create_deal", client="ООО Ромашка", amount="150 000")
        assert isinstance(out, Confirm)
        assert "«Ромашка»" in out.text and "150 000 UAH" in out.text and "«Новая»" in out.text
        assert out.args["client_id"] == ids["ca"]
        async with maker() as s:
            assert (await s.execute(select(DealModel))).scalars().all() == []
        assert (await commit(ctx, out)).startswith("✅ Сделка")
    async with maker() as s:
        deal = (await s.execute(select(DealModel))).scalars().one()
    assert (deal.client_id, deal.amount, deal.currency, deal.owner_id) == (
        ids["ca"],
        Decimal("150000"),
        "UAH",
        ids["owner"],
    )


async def test_create_deal_other_currency_and_default_title(world):
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "a_manager") as ctx:
        out = await call(ctx, "create_deal", client="Ромашка", amount=2500, currency="usd")
        assert "2 500 USD" in out.text and "Сделка — Ромашка" in out.text
        assert isinstance(await call(ctx, "create_deal", client="Ромашка", amount="много"), Refuse)
        assert isinstance(await call(ctx, "create_deal", client="Ромашка", amount="-5"), Refuse)
        assert isinstance(await call(ctx, "create_deal", client="Ромашка", currency="RUB"), Refuse)


async def test_create_deal_forbidden_for_non_owner(world):
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "other") as ctx:
        out = await call(ctx, "create_deal", client="Ромашка")
        assert isinstance(out, Refuse) and "ответственный" in out.text


async def test_create_deal_asks_when_several_clients_match_and_not_found(world):
    maker, ids, _ = world
    made = await add_clients(maker, ids, ("Лилия Север", "owner", 0), ("Лилия Юг", "owner", 0))
    async with ai_ctx(maker, ids, "owner") as ctx:
        out = await call(ctx, "create_deal", client="Лилия", amount=10)
        assert isinstance(out, Choose) and out.param == "_client_id"
        assert {i for i, _ in out.options} == {made["Лилия Север"], made["Лилия Юг"]}
        # после выбора инструмент запускается заново с id — и теперь готов к подтверждению
        again = await call(ctx, "create_deal", **{**out.args, out.param: made["Лилия Юг"]})
        assert isinstance(again, Confirm) and "Лилия Юг" in again.text and "10 UAH" in again.text
        assert "не найден" in (await call(ctx, "create_deal", client="Несуществующий")).text


# ── move_deal_stage / list_deals ─────────────────────────────────────────────
async def make_deal(maker, ids, who="owner", title="Поставка", amount=1000):
    async with ai_ctx(maker, ids, who) as ctx:
        deal = await ctx.deals.create_deal(
            ids["ca"], DealCreate(title=title, amount=None if amount is None else Decimal(amount)), ctx.user
        )
        return deal.id


async def test_move_deal_stage_confirm_and_commit(world):
    maker, ids, _ = world
    deal_id = await make_deal(maker, ids)
    async with ai_ctx(maker, ids, "owner") as ctx:
        out = await call(ctx, "move_deal_stage", client="Ромашка", stage="переговоры")
        assert isinstance(out, Confirm)
        assert "«Поставка»" in out.text and "«Новая»" in out.text and "«Переговоры»" in out.text
        assert (await commit(ctx, out)).startswith("✅")
    async with maker() as s:
        deal = (await s.execute(select(DealModel).where(DealModel.id == deal_id))).scalar_one()
        assert deal.stage_id == out.args["stage_id"]


async def test_move_deal_rules(world):
    maker, ids, _ = world
    await make_deal(maker, ids)
    async with ai_ctx(maker, ids, "owner") as ctx:
        assert "уже на стадии" in (await call(ctx, "move_deal_stage", client="Ромашка", stage="Новая")).text
        lost = await call(ctx, "move_deal_stage", client="Ромашка", stage="Отказ")
        assert isinstance(lost, Refuse) and "причина" in lost.text
        reason = await call(ctx, "move_deal_stage", client="Ромашка", stage="Отказ", lost_reason="выбрали конкурента")
        assert isinstance(reason, Confirm) and "выбрали конкурента" in reason.text
        assert isinstance(await call(ctx, "move_deal_stage", client="Ромашка", stage="Космос"), Refuse)
        assert isinstance(await call(ctx, "move_deal_stage", client="Ромашка"), Refuse)  # нет стадии
    async with ai_ctx(maker, ids, "other") as ctx:
        denied = await call(ctx, "move_deal_stage", client="Ромашка", stage="Переговоры")
        assert isinstance(denied, Refuse) and "ответственный" in denied.text


async def test_move_deal_won_requires_amount_and_several_deals_need_choice(world):
    maker, ids, _ = world
    await make_deal(maker, ids, title="Без суммы", amount=None)
    async with ai_ctx(maker, ids, "owner") as ctx:
        won = await call(ctx, "move_deal_stage", client="Ромашка", stage="Успех")
        assert isinstance(won, Refuse) and "сумма" in won.text
    await make_deal(maker, ids, title="Вторая", amount=500)
    async with ai_ctx(maker, ids, "owner") as ctx:
        out = await call(ctx, "move_deal_stage", client="Ромашка", stage="Переговоры")
        assert isinstance(out, Choose) and out.param == "_deal_id" and len(out.options) == 2
        picked = await call(ctx, "move_deal_stage", **{**out.args, out.param: out.options[0][0]})
        assert isinstance(picked, Confirm)
        by_keyword = await call(ctx, "move_deal_stage", client="Ромашка", deal="вторая", stage="Переговоры")
        assert isinstance(by_keyword, Confirm) and "«Вторая»" in by_keyword.text


async def test_list_deals_by_stage_and_client(world):
    maker, ids, _ = world
    await make_deal(maker, ids, title="Первая", amount=1000)
    async with ai_ctx(maker, ids, "owner") as ctx:
        out = await call(ctx, "list_deals")
        assert isinstance(out, Done) and "Первая" in out.text and "Ромашка" in out.text and "1 000 UAH" in out.text
        assert "на стадии «Новая»" in (await call(ctx, "list_deals", stage="новая")).text
        assert "нет" in (await call(ctx, "list_deals", stage="Переговоры")).text
        assert "Первая" in (await call(ctx, "list_deals", client="Ромашка")).text
        assert isinstance(await call(ctx, "list_deals", stage="Космос"), Refuse)
    async with ai_ctx(maker, ids, "other") as ctx:
        assert "нет" in (await call(ctx, "list_deals")).text  # «мои» — не чужие
        assert "Первая" in (await call(ctx, "list_deals", client="Ромашка")).text  # по клиенту видно всем


# ── add_note ─────────────────────────────────────────────────────────────────
async def test_add_note_confirm_commit_and_rights(world):
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "owner") as ctx:
        out = await call(ctx, "add_note", client="Ромашка", text="Просили скидку 5%", type="call")
        assert isinstance(out, Confirm) and "запись о звонке" in out.text and "Просили скидку" in out.text
        assert (await commit(ctx, out)).startswith("✅")
        assert isinstance(await call(ctx, "add_note", client="Ромашка", text="  "), Refuse)
    async with maker() as s:
        item = (await s.execute(select(InteractionModel))).scalars().one()
    assert (item.client_id, item.type, item.summary, item.author_id) == (
        ids["ca"],
        "call",
        "Просили скидку 5%",
        ids["owner"],
    )
    async with ai_ctx(maker, ids, "other") as ctx:
        denied = await call(ctx, "add_note", client="Ромашка", text="чужая заметка")
        assert isinstance(denied, Refuse) and "ответственный" in denied.text


# ── create_task ──────────────────────────────────────────────────────────────
async def test_create_task_for_colleague_tomorrow_at_ten(world):
    maker, ids, _ = world
    petr = await add_user(maker, ids, "Петр")
    day, at = tomorrow_at(10)
    async with ai_ctx(maker, ids, "a_manager") as ctx:
        out = await call(
            ctx, "create_task", title="Позвонить клиенту", assignee_username="Петру", deadline=day, deadline_time=at
        )
        assert isinstance(out, Confirm) and "@Петр" in out.text and "10:00" in out.text
        assert (await commit(ctx, out)).startswith("✅ Создана")
    async with maker() as s:
        task = (await s.execute(select(SpisokModel))).scalars().one()
    assert (task.title, task.user_id, task.author_id) == ("Позвонить клиенту", petr, ids["a_manager"])
    # Postgres хранит момент времени (UTC) — переводим в Киев; SQLite в тестах хранит «настенное» время как есть
    local = task.deadline if task.deadline.tzinfo is None else task.deadline.astimezone(LOCAL_TZ)
    assert local.strftime("%Y-%m-%d %H:%M") == f"{day} {at}"


async def test_create_task_assignee_matching_and_choice(world):
    maker, ids, _ = world
    await add_user(maker, ids, "Пётр")
    await add_user(maker, ids, "Ольга")
    async with ai_ctx(maker, ids, "a_manager") as ctx:
        assert "@Пётр" in (await call(ctx, "create_task", title="X", assignee_username="Петру")).text  # ё/е, падеж
        assert "@Ольга" in (await call(ctx, "create_task", title="X", assignee_username="Ольге")).text
        assert "для вас" in (await call(ctx, "create_task", title="X")).text  # исполнитель не назван — сам
        missing = await call(ctx, "create_task", title="X", assignee_username="Несуществующий")
        assert isinstance(missing, Refuse) and "не найден" in missing.text
    await add_user(maker, ids, "Петров")
    async with ai_ctx(maker, ids, "a_manager") as ctx:
        out = await call(ctx, "create_task", title="X", assignee_username="Пет")
        assert isinstance(out, Choose) and out.param == "_assignee_id" and len(out.options) == 2


async def test_create_task_with_client_and_past_deadline(world):
    maker, ids, _ = world
    day, at = tomorrow_at(15, 30)
    async with ai_ctx(maker, ids, "owner") as ctx:
        out = await call(ctx, "create_task", title="Позвонить", client="Ромашка", deadline=day, deadline_time=at)
        assert isinstance(out, Confirm) and "клиент «Ромашка»" in out.text and "«Позвонить»" in out.text
        await commit(ctx, out)
        past = await call(ctx, "create_task", title="Вчера", deadline="2020-01-01")
        assert isinstance(past, Refuse) and "прошёл" in past.text
        assert isinstance(await call(ctx, "create_task", title="X", deadline="завтра"), Refuse)
        assert isinstance(await call(ctx, "create_task", title="  "), Refuse)
    async with maker() as s:
        task = (await s.execute(select(SpisokModel))).scalars().one()
    # настоящая связь вместо пометки в названии и описании
    assert task.title == "Позвонить" and task.description is None and task.client_id == ids["ca"]


# ── прежние команды по задачам идут через сервис и с подтверждением ──────────
async def test_task_status_change_goes_through_service_with_confirmation(world):
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "owner") as ctx:
        created = await call(ctx, "create_task", title="Купить молоко")
        await commit(ctx, created)
        found = await call(ctx, "get_tasks", search="молоко")
        assert isinstance(found, Done) and "Купить молоко" in found.text
        out = await call(ctx, "update_task_status", search="молоко", status="done")
        assert isinstance(out, Confirm) and "Выполнена" in out.text
        async with maker() as s:  # до «да» статус прежний
            assert (await s.execute(select(SpisokModel.status))).scalar_one().value == "todo"
        assert (await commit(ctx, out)).startswith("✅")
        assert isinstance(await call(ctx, "update_task_status", search="молоко", status="летит"), Refuse)
        assert "не найдена" in (await call(ctx, "update_task_status", search="несуществующая", status="done")).text
    async with maker() as s:
        assert (await s.execute(select(SpisokModel.status))).scalar_one().value == "done"


async def test_task_tools_respect_task_access(world):
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "owner") as ctx:
        await commit(ctx, await call(ctx, "create_task", title="Личная задача owner"))
    async with ai_ctx(maker, ids, "other") as ctx:
        # чужая задача для «other» не находится: поиск ограничен своими (исполнитель или автор)
        assert "не найдена" in (await call(ctx, "update_task_priority", search="Личная", priority="high")).text
        assert "не найдены" in (await call(ctx, "get_tasks", search="Личная")).text


@pytest.mark.parametrize("name", ["update_task_priority", "update_task_description", "assign_task"])
async def test_task_edit_tools_confirm_before_changing(world, name):
    maker, ids, _ = world
    await add_user(maker, ids, "Борис")
    args = {
        "update_task_priority": {"priority": "critical"},
        "update_task_description": {"description": "Новое описание"},
        "assign_task": {"assignee_username": "Борису"},
    }[name]
    async with ai_ctx(maker, ids, "a_manager") as ctx:
        await commit(ctx, await call(ctx, "create_task", title="Отчёт"))
        out = await call(ctx, name, search="Отчёт", **args)
        assert isinstance(out, Confirm), out
        assert (await commit(ctx, out)).startswith(("✅", "📝"))


# ── list_clients (по живой переписке: «мои клиенты», «покажи всех клиентов», «люди Б2С») ──────────
async def test_list_clients_all_mine_and_by_type(world):
    maker, ids, _ = world
    async with maker() as s:
        s.add(ClientModel(name="Алекс Алексеев", client_type="person", workspace_id=ids["a"], owner_id=ids["other"]))
        await s.commit()
    await add_clients(maker, ids, ("Лютик", "owner", 0))

    async with ai_ctx(maker, ids, "owner") as ctx:
        everyone = await call(ctx, "list_clients")
        assert isinstance(everyone, Done) and "Клиенты: 3" in everyone.text
        assert "Ромашка" in everyone.text and "Алекс Алексеев" in everyone.text and "Лютик" in everyone.text
        assert "компания" in everyone.text and "частное лицо" in everyone.text
        assert "Клиентов Б" not in everyone.text and "Б-фирма" not in everyone.text  # клиент другой компании не виден

        mine = await call(ctx, "list_clients", mine=True)
        assert "Клиенты (ваши): 2" in mine.text and "Алекс Алексеев" not in mine.text

        people = await call(ctx, "list_clients", client_type="person")
        assert "частные лица): 1" in people.text and "Алекс Алексеев" in people.text and "Ромашка" not in people.text

        found = await call(ctx, "list_clients", search="Лютик")
        assert "Лютик" in found.text and "Ромашка" not in found.text
        assert "никого не найдено" in (await call(ctx, "list_clients", search="Несуществующий")).text
        # неизвестный тип игнорируется (модель могла придумать «b2c») — это «все клиенты», а не ошибка
        assert "Клиенты: 3" in (await call(ctx, "list_clients", client_type="b2c")).text


async def test_list_clients_reports_total_when_truncated(world):
    maker, ids, _ = world
    await add_clients(maker, ids, *[(f"Клиент {i:02d}", "owner", 0) for i in range(20)])
    async with ai_ctx(maker, ids, "owner") as ctx:
        out = await call(ctx, "list_clients")
    assert "Клиенты: 21" in out.text and "…и ещё 6" in out.text and out.text.count("•") == 15


async def test_list_clients_is_offered_to_everyone(world):
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "owner") as ctx:
        assert "list_clients" in {t["function"]["name"] for t in default_registry().definitions(ctx.user)}
        assert "list_clients" in default_registry().hints(ctx.user)


# ── поиск задач по номеру и коротким словам (раньше «найди задачу 50» возвращало первые 10 любых) ──────
async def _make_tasks(maker, ids, who, titles):
    async with ai_ctx(maker, ids, who) as ctx:
        made = {}
        for title in titles:
            await commit(ctx, await call(ctx, "create_task", title=title))
        async with maker() as s:
            for task in (await s.execute(select(SpisokModel))).scalars().all():
                made[task.title] = task.id
        return made


async def test_get_tasks_by_number_and_short_words(world):
    maker, ids, _ = world
    made = await _make_tasks(maker, ids, "owner", ["Купить молоко", "ТО авто", "Отчёт 50 клиентов"])
    async with ai_ctx(maker, ids, "owner") as ctx:
        by_id = await call(ctx, "get_tasks", search=str(made["Купить молоко"]))
        assert f"[#{made['Купить молоко']}]" in by_id.text and "ТО авто" not in by_id.text.replace("Отчёт", "")
        hashed = await call(ctx, "get_tasks", search=f"#{made['ТО авто']}")
        assert f"[#{made['ТО авто']}]" in hashed.text
        short = await call(ctx, "get_tasks", search="ТО")  # слово из двух букв раньше отбрасывалось
        assert "ТО авто" in short.text and "Купить молоко" not in short.text
        number_in_title = await call(ctx, "get_tasks", search="50")
        assert "Отчёт 50 клиентов" in number_in_title.text
        assert "не найдены" in (await call(ctx, "get_tasks", search="99999")).text  # не «показать всё»


async def test_get_tasks_reports_total_when_truncated_and_edit_by_number(world):
    maker, ids, _ = world
    made = await _make_tasks(maker, ids, "owner", [f"Задача {i:02d}" for i in range(12)])
    async with ai_ctx(maker, ids, "owner") as ctx:
        listing = await call(ctx, "get_tasks")
        assert "Найдено: 12 (показаны первые 10)" in listing.text
        out = await call(ctx, "update_task_status", search=f"#{made['Задача 03']}", status="done")
        assert isinstance(out, Confirm) and "Задача 03" in out.text


# ── по живой переписке: «покажи мои воронки», «сделки пользователя …», «все клиенты компании» ──────────
async def _username(maker, ids, who) -> str:
    async with maker() as s:
        return (await s.execute(select(UserModel.username).where(UserModel.id == ids[who]))).scalar_one()


async def test_pipeline_summary_all_mine_and_by_owner(world):
    maker, ids, _ = world
    await make_deal(maker, ids, who="owner", title="Первая", amount=1000)
    await make_deal(maker, ids, who="a_manager", title="Вторая", amount=500)
    async with ai_ctx(maker, ids, "owner") as ctx:
        everyone = await call(ctx, "pipeline_summary")
        assert isinstance(everyone, Done) and "вся компания" in everyone.text
        assert "Новая: 2 · 1 500 UAH" in everyone.text and "Переговоры: 0" in everyone.text

        mine = await call(ctx, "pipeline_summary", mine=True)
        assert "ваша" in mine.text and "Новая: 1 · 1 000 UAH" in mine.text

        manager = await _username(maker, ids, "a_manager")
        theirs = await call(ctx, "pipeline_summary", owner=manager)
        assert f"@{manager}" in theirs.text and "Новая: 1 · 500 UAH" in theirs.text
        assert "не найден" in (await call(ctx, "pipeline_summary", owner="Несуществующий")).text
    async with ai_ctx(maker, ids, "other") as ctx:
        assert "Сделок пока нет" in (await call(ctx, "pipeline_summary", mine=True)).text


async def test_list_deals_and_clients_by_owner(world):
    maker, ids, _ = world
    await make_deal(maker, ids, who="owner", title="Сделка owner")
    owner_name = await _username(maker, ids, "owner")
    async with ai_ctx(maker, ids, "a_manager") as ctx:
        deals = await call(ctx, "list_deals", owner=owner_name)
        assert f"@{owner_name}" in deals.text and "Сделка owner" in deals.text
        assert "нет" in (await call(ctx, "list_deals")).text  # свои у менеджера пусты
        clients = await call(ctx, "list_clients", owner=owner_name)
        assert "Ромашка" in clients.text and f"@{owner_name}" in clients.text.splitlines()[0]
        assert "Сотрудник «Никто» не найден" in (await call(ctx, "list_deals", owner="Никто")).text


async def test_ambiguous_owner_asks_which_employee(world):
    maker, ids, _ = world
    await add_user(maker, ids, "Борис")
    await add_user(maker, ids, "Борислав")
    async with ai_ctx(maker, ids, "owner") as ctx:
        out = await call(ctx, "list_deals", owner="Борис")
        assert isinstance(out, Choose) and out.param == "_owner_id" and len(out.options) == 2
        picked = await call(ctx, "list_deals", **{**out.args, out.param: out.options[0][0]})
        assert isinstance(picked, Done)


def test_list_clients_tool_tells_the_model_not_to_guess_the_type():
    """«Все клиенты компании» — вся организация, а не тип «компания» (так модель ошиблась в живой переписке)."""
    tool = default_registry().get("list_clients")
    assert "ТОЛЬКО если" in tool.description and "без типа" in tool.description
    assert "pipeline_summary" in default_registry().names()


async def test_get_tasks_not_found_says_where_it_looked(world):
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "owner") as ctx:
        out = await call(ctx, "get_tasks", search="99999")
    assert "исполнитель или автор" in out.text


async def test_managers_are_told_the_list_is_only_their_own(world):
    """Живая проверка: админ спросил «клиентов без контакта» и получил «нет», хотя у других ответственных они есть."""
    maker, ids, _ = world
    await add_clients(maker, ids, ("Чужой давний", "other", 60))
    async with ai_ctx(maker, ids, "a_manager") as ctx:
        own = await call(ctx, "list_clients_without_contact", days=30)
        assert "Нет ваших клиентов" in own.text and "только ваши клиенты" in own.text and "у всех" in own.text
        everyone = await call(ctx, "list_clients_without_contact", days=30, all_owners=True)
        assert "Чужой давний" in everyone.text and "только ваши клиенты" not in everyone.text
    async with ai_ctx(
        maker, ids, "owner"
    ) as ctx:  # обычному сотруднику «у всех» всё равно недоступно — не подсказываем
        assert "только ваши клиенты" not in (await call(ctx, "list_clients_without_contact", days=30)).text


async def test_get_tasks_by_client_shows_everyones_tasks_of_that_client(world):
    maker, ids, _ = world
    async with ai_ctx(maker, ids, "owner") as ctx:
        await commit(ctx, await call(ctx, "create_task", title="Позвонить", client="Ромашка"))
        await commit(ctx, await call(ctx, "create_task", title="Личное без клиента"))
    async with ai_ctx(maker, ids, "other") as ctx:  # посторонний: «мои» задачи пусты, а задачи клиента видны команде
        assert "не найдены" in (await call(ctx, "get_tasks", search="Позвонить")).text
        by_client = await call(ctx, "get_tasks", client="Ромашка")
        assert "Позвонить" in by_client.text and "👤 Ромашка" in by_client.text
        assert "Личное без клиента" not in by_client.text
        assert (
            "Ищу все задачи клиента «Ромашка»" in (await call(ctx, "get_tasks", client="Ромашка", status="done")).text
        )
