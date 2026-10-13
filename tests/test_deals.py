# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_deals.py
"""Этап 3 lite-CRM: воронка и сделки.

Правила: стадии меняет только admin; процессные поля сделки (сумма, ответственный, срок) и удаление —
admin/manager; ответственный по сделке двигает её по стадиям и правит название/заметки;
lost требует причину, won — сумму; вернуть закрытую сделку может только admin/manager; изоляция компаний.
"""

from unittest.mock import AsyncMock, patch

from sqlalchemy import and_, select

from src.models.audit import AuditAction, AuditLog
from src.models.deal import DealModel
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)


async def _stages(client, headers) -> dict[str, dict]:
    resp = await client.get("/api/pipeline", headers=headers)
    assert resp.status_code == 200, resp.text
    return {s["name"]: s for s in resp.json()["stages"]}


async def _deal(client, headers, client_id, **payload):
    payload.setdefault("title", "Сделка")
    return await client.post(f"/api/clients/{client_id}/deals", json=payload, headers=headers)


# ── воронка ──────────────────────────────────────────────────────────────────
async def test_default_pipeline_created_on_first_access(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "other")  # даже обычный пользователь получает воронку
    first = (await client.get("/api/pipeline", headers=h)).json()
    assert [(s["name"], s["kind"]) for s in first["stages"]] == [
        ("Новая", "open"),
        ("Связались", "open"),
        ("Переговоры", "open"),
        ("Предложение", "open"),
        ("Согласование", "open"),
        ("Успех", "won"),
        ("Отказ", "lost"),
    ]
    again = (await client.get("/api/pipeline", headers=h)).json()
    assert again["id"] == first["id"]  # повторно не создаётся


async def test_pipelines_are_per_company(client, world):
    _, _, logins = world
    a = (await client.get("/api/pipeline", headers=await _headers(client, logins, "a_admin"))).json()
    b = (await client.get("/api/pipeline", headers=await _headers(client, logins, "b_admin"))).json()
    assert a["id"] != b["id"]
    assert {s["id"] for s in a["stages"]}.isdisjoint({s["id"] for s in b["stages"]})


async def test_only_admin_manages_stages(client, world):
    _, _, logins = world
    hm = await _headers(client, logins, "a_manager")
    stages = await _stages(client, hm)
    assert (await client.post("/api/pipeline/stages", json={"name": "X"}, headers=hm)).status_code == 403
    sid = stages["Новая"]["id"]
    assert (await client.patch(f"/api/pipeline/stages/{sid}", json={"name": "X"}, headers=hm)).status_code == 403
    assert (await client.delete(f"/api/pipeline/stages/{sid}", headers=hm)).status_code == 403

    ha = await _headers(client, logins, "a_admin")
    created = await client.post("/api/pipeline/stages", json={"name": "Договор", "kind": "open"}, headers=ha)
    assert created.status_code == 201 and created.json()["position"] == 7  # в конец
    renamed = await client.patch(
        f"/api/pipeline/stages/{created.json()['id']}", json={"name": "Договор подписан", "position": 1}, headers=ha
    )
    assert renamed.status_code == 200 and renamed.json()["position"] == 1
    names = [s["name"] for s in (await client.get("/api/pipeline", headers=ha)).json()["stages"]]
    assert names == [
        "Новая",
        "Договор подписан",
        "Связались",
        "Переговоры",
        "Предложение",
        "Согласование",
        "Успех",
        "Отказ",
    ]
    positions = [s["position"] for s in (await client.get("/api/pipeline", headers=ha)).json()["stages"]]
    assert positions == list(range(8))  # без дублей и пропусков
    # вставка сразу на позицию при создании
    first = await client.post("/api/pipeline/stages", json={"name": "Лид", "position": 0}, headers=ha)
    assert first.status_code == 201 and first.json()["position"] == 0
    names = [s["name"] for s in (await client.get("/api/pipeline", headers=ha)).json()["stages"]]
    assert names[:2] == ["Лид", "Новая"]
    assert (await client.patch(f"/api/pipeline/stages/{sid}", json={"name": None}, headers=ha)).status_code == 422


async def test_stage_delete_guards(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    stages = await _stages(client, ha)
    # последняя стадия вида won / lost не удаляется
    assert (await client.delete(f"/api/pipeline/stages/{stages['Успех']['id']}", headers=ha)).status_code == 409
    # в стадии есть сделка
    await _deal(client, ha, ids["ca"])
    assert (await client.delete(f"/api/pipeline/stages/{stages['Новая']['id']}", headers=ha)).status_code == 409
    # пустая стадия вида open (не последняя) удаляется
    assert (await client.delete(f"/api/pipeline/stages/{stages['Переговоры']['id']}", headers=ha)).status_code == 200
    # стадия чужой компании недоступна
    hb = await _headers(client, logins, "b_admin")
    assert (await client.delete(f"/api/pipeline/stages/{stages['Предложение']['id']}", headers=hb)).status_code == 404


# ── создание ─────────────────────────────────────────────────────────────────
async def test_client_owner_creates_deal_and_owns_it(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "owner")  # ответственный за клиента ca, обычный пользователь
    resp = await _deal(client, h, ids["ca"], title="  Поставка  ", amount=1500.5)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    stages = await _stages(client, h)
    assert body["title"] == "Поставка" and body["owner_id"] == ids["owner"]
    assert body["stage_id"] == stages["Новая"]["id"] and body["closed_at"] is None
    assert body["amount"] == 1500.5 and isinstance(body["amount"], float)


async def test_create_permissions_and_validation(client, world):
    _, ids, logins = world
    assert (await _deal(client, await _headers(client, logins, "other"), ids["ca"])).status_code == 403

    ho = await _headers(client, logins, "owner")
    stages = await _stages(client, ho)
    # ответственный за клиента не назначает другого ответственного
    assert (await _deal(client, ho, ids["ca"], owner_id=ids["other"])).status_code == 403
    # создать сразу в закрытой стадии нельзя
    assert (await _deal(client, ho, ids["ca"], stage_id=stages["Успех"]["id"])).status_code == 422
    assert (await _deal(client, ho, ids["ca"], amount=-5)).status_code == 422
    assert (await _deal(client, ho, ids["ca"], title="  ")).status_code == 422

    hm = await _headers(client, logins, "a_manager")
    resp = await _deal(client, hm, ids["ca"], owner_id=ids["other"], stage_id=stages["Переговоры"]["id"])
    assert resp.status_code == 201 and resp.json()["owner_id"] == ids["other"]
    # ответственный из другой компании
    assert (await _deal(client, hm, ids["ca"], owner_id=ids["b_admin"])).status_code == 404


# ── изоляция компаний ────────────────────────────────────────────────────────
async def test_foreign_company_gets_404_everywhere(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    deal_id = (await _deal(client, ha, ids["ca"])).json()["id"]
    stage_a = (await _stages(client, ha))["Переговоры"]["id"]

    hb = await _headers(client, logins, "b_admin")
    assert (await _deal(client, hb, ids["ca"])).status_code == 404  # чужой клиент
    assert (await client.get(f"/api/clients/{ids['ca']}/deals", headers=hb)).status_code == 404
    assert (await client.get(f"/api/deals/{deal_id}", headers=hb)).status_code == 404
    assert (await client.patch(f"/api/deals/{deal_id}", json={"title": "взлом"}, headers=hb)).status_code == 404
    assert (
        await client.patch(f"/api/deals/{deal_id}/stage", json={"stage_id": stage_a}, headers=hb)
    ).status_code == 404
    assert (await client.delete(f"/api/deals/{deal_id}", headers=hb)).status_code == 404
    assert (await client.get("/api/deals", headers=hb)).json()["total"] == 0

    # и свою сделку нельзя перевести на стадию чужой компании
    own_deal = (await _deal(client, hb, ids["cb"])).json()["id"]
    assert (
        await client.patch(f"/api/deals/{own_deal}/stage", json={"stage_id": stage_a}, headers=hb)
    ).status_code == 404
    assert (await client.get(f"/api/deals/{deal_id}", headers=ha)).json()["title"] == "Сделка"


# ── правка: справочные и процессные поля ─────────────────────────────────────
async def test_owner_edits_reference_fields_not_process_fields(client, world):
    _, ids, logins = world
    ho = await _headers(client, logins, "owner")
    deal = (await _deal(client, ho, ids["ca"], amount=100)).json()
    url = f"/api/deals/{deal['id']}"

    assert (await client.patch(url, json={"title": "Новое имя", "notes": "заметка"}, headers=ho)).status_code == 200
    assert (await client.patch(url, json={"amount": 200}, headers=ho)).status_code == 403
    assert (await client.patch(url, json={"owner_id": ids["other"]}, headers=ho)).status_code == 403
    assert (await client.patch(url, json={"expected_close_date": "2026-12-01"}, headers=ho)).status_code == 403
    assert (
        await client.patch(url, json={"amount": 100, "title": "ещё"}, headers=ho)
    ).status_code == 200  # то же значение

    hm = await _headers(client, logins, "a_manager")
    resp = await client.patch(
        url, json={"amount": 250, "owner_id": ids["other"], "expected_close_date": "2026-12-01"}, headers=hm
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["amount"] == 250 and body["owner_id"] == ids["other"] and body["expected_close_date"] == "2026-12-01"
    # прежний ответственный больше не владелец
    assert (await client.patch(url, json={"title": "x"}, headers=ho)).status_code == 403


async def test_unrelated_user_cannot_edit_or_move(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    deal = (await _deal(client, hm, ids["ca"])).json()  # ответственный — менеджер
    h = await _headers(client, logins, "other")
    stage = (await _stages(client, h))["Переговоры"]["id"]
    assert (await client.patch(f"/api/deals/{deal['id']}", json={"title": "x"}, headers=h)).status_code == 403
    assert (
        await client.patch(f"/api/deals/{deal['id']}/stage", json={"stage_id": stage}, headers=h)
    ).status_code == 403
    assert (await client.get(f"/api/deals/{deal['id']}", headers=h)).status_code == 200  # читать можно


# ── перевод по стадиям ───────────────────────────────────────────────────────
async def test_move_between_open_stages_and_noop(client, world):
    _, ids, logins = world
    ho = await _headers(client, logins, "owner")
    stages = await _stages(client, ho)
    deal = (await _deal(client, ho, ids["ca"])).json()
    url = f"/api/deals/{deal['id']}/stage"
    resp = await client.patch(url, json={"stage_id": stages["Предложение"]["id"]}, headers=ho)
    assert resp.status_code == 200 and resp.json()["stage_id"] == stages["Предложение"]["id"]
    assert resp.json()["closed_at"] is None
    same = await client.patch(url, json={"stage_id": stages["Предложение"]["id"]}, headers=ho)
    assert same.status_code == 200 and same.json()["stage_id"] == stages["Предложение"]["id"]


async def test_lost_needs_reason_and_won_needs_amount(client, world):
    _, ids, logins = world
    ho = await _headers(client, logins, "owner")
    stages = await _stages(client, ho)
    deal = (await _deal(client, ho, ids["ca"])).json()  # без суммы
    url = f"/api/deals/{deal['id']}/stage"

    assert (await client.patch(url, json={"stage_id": stages["Отказ"]["id"]}, headers=ho)).status_code == 422
    assert (
        await client.patch(url, json={"stage_id": stages["Отказ"]["id"], "lost_reason": "  "}, headers=ho)
    ).status_code == 422
    assert (await client.patch(url, json={"stage_id": stages["Успех"]["id"]}, headers=ho)).status_code == 422

    lost = await client.patch(url, json={"stage_id": stages["Отказ"]["id"], "lost_reason": "Дорого"}, headers=ho)
    assert lost.status_code == 200
    assert lost.json()["lost_reason"] == "Дорого" and lost.json()["closed_at"] is not None


async def test_won_sets_closed_at_and_reopen_only_by_manager(client, world):
    _, ids, logins = world
    ho = await _headers(client, logins, "owner")
    hm = await _headers(client, logins, "a_manager")
    stages = await _stages(client, ho)
    deal = (await _deal(client, hm, ids["ca"], amount=1000, owner_id=ids["owner"])).json()
    url = f"/api/deals/{deal['id']}/stage"

    won = await client.patch(url, json={"stage_id": stages["Успех"]["id"]}, headers=ho)
    assert won.status_code == 200 and won.json()["closed_at"] is not None
    # ответственный закрытую сделку не возвращает и не переводит
    assert (await client.patch(url, json={"stage_id": stages["Новая"]["id"]}, headers=ho)).status_code == 403
    assert (
        await client.patch(url, json={"stage_id": stages["Отказ"]["id"], "lost_reason": "x"}, headers=ho)
    ).status_code == 403
    # у выигранной сделки сумму очистить нельзя
    assert (await client.patch(f"/api/deals/{deal['id']}", json={"amount": None}, headers=hm)).status_code == 422

    reopened = await client.patch(url, json={"stage_id": stages["Переговоры"]["id"]}, headers=hm)
    assert reopened.status_code == 200
    assert reopened.json()["closed_at"] is None and reopened.json()["lost_reason"] is None


async def test_reopen_clears_lost_reason(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    stages = await _stages(client, hm)
    deal = (await _deal(client, hm, ids["ca"])).json()
    url = f"/api/deals/{deal['id']}/stage"
    await client.patch(url, json={"stage_id": stages["Отказ"]["id"], "lost_reason": "Ушли к конкуренту"}, headers=hm)
    back = (await client.patch(url, json={"stage_id": stages["Новая"]["id"]}, headers=hm)).json()
    assert back["lost_reason"] is None and back["closed_at"] is None


async def test_move_is_audited_with_workspace_and_user(client, world):
    maker, ids, logins = world
    ho = await _headers(client, logins, "owner")
    stages = await _stages(client, ho)
    deal = (await _deal(client, ho, ids["ca"])).json()
    await client.patch(f"/api/deals/{deal['id']}/stage", json={"stage_id": stages["Переговоры"]["id"]}, headers=ho)

    async with maker() as s:
        rows = (
            (
                await s.execute(
                    select(AuditLog).where(
                        and_(
                            AuditLog.entity_type == "deals",
                            AuditLog.entity_id == deal["id"],
                            AuditLog.action == AuditAction.update,
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].old_values["stage_id"] == stages["Новая"]["id"]
    assert rows[0].new_values["stage_id"] == stages["Переговоры"]["id"]
    assert rows[0].workspace_id == ids["a"] and rows[0].user_id == ids["owner"]


# ── удаление, список, каскад ─────────────────────────────────────────────────
async def test_only_manager_deletes_deal(client, world):
    _, ids, logins = world
    ho = await _headers(client, logins, "owner")
    deal = (await _deal(client, ho, ids["ca"])).json()
    assert (await client.delete(f"/api/deals/{deal['id']}", headers=ho)).status_code == 403
    hm = await _headers(client, logins, "a_manager")
    assert (await client.delete(f"/api/deals/{deal['id']}", headers=hm)).status_code == 200
    assert (await client.get(f"/api/deals/{deal['id']}", headers=hm)).status_code == 404
    assert (await client.get("/api/deals", headers=hm)).json()["total"] == 0


async def test_list_filters_and_pagination(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    stages = await _stages(client, hm)
    other_client = (await client.post("/api/clients", json={"name": "Второй"}, headers=hm)).json()
    d1 = (await _deal(client, hm, ids["ca"], title="A")).json()
    await _deal(client, hm, ids["ca"], title="B", owner_id=ids["other"], stage_id=stages["Переговоры"]["id"])
    await _deal(client, hm, other_client["id"], title="C")

    def titles(resp):
        return sorted(d["title"] for d in resp.json()["items"])

    assert titles(await client.get("/api/deals", headers=hm)) == ["A", "B", "C"]
    assert titles(await client.get("/api/deals", params={"client_id": ids["ca"]}, headers=hm)) == ["A", "B"]
    assert titles(await client.get("/api/deals", params={"stage_id": stages["Переговоры"]["id"]}, headers=hm)) == ["B"]
    assert titles(await client.get("/api/deals", params={"owner_id": ids["other"]}, headers=hm)) == ["B"]
    assert titles(await client.get(f"/api/clients/{ids['ca']}/deals", headers=hm)) == ["A", "B"]
    page = (await client.get("/api/deals", params={"page": 2, "size": 2}, headers=hm)).json()
    assert page["total"] == 3 and len(page["items"]) == 1 and d1["id"] == page["items"][0]["id"]


async def test_deleting_client_soft_deletes_deals(client, world):
    maker, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    await _deal(client, hm, ids["ca"])
    await _deal(client, hm, ids["ca"], title="Вторая")
    assert (await client.delete(f"/api/clients/{ids['ca']}", headers=hm)).status_code == 200
    assert (await client.get("/api/deals", headers=hm)).json()["total"] == 0
    assert (await client.get(f"/api/clients/{ids['ca']}/deals", headers=hm)).status_code == 404
    async with maker() as s:
        rows = (await s.execute(select(DealModel).where(DealModel.client_id == ids["ca"]))).scalars().all()
        assert len(rows) == 2 and all(r.deleted_at is not None for r in rows)


# ── position: порядок карточек в колонке ─────────────────────────────────────
async def _column(client, headers, stage_id) -> list[str]:
    resp = await client.get("/api/deals", params={"stage_id": stage_id}, headers=headers)
    return [d["title"] for d in resp.json()["items"]]


async def test_new_deals_go_to_end_of_column(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    stage = (await _stages(client, hm))["Новая"]["id"]
    created = [(await _deal(client, hm, ids["ca"], title=t)).json() for t in ("A", "B", "C")]
    assert [d["position"] for d in created] == [0, 1, 2]
    assert await _column(client, hm, stage) == ["A", "B", "C"]


async def test_move_inserts_at_position_and_shifts_others(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    stages = await _stages(client, hm)
    a = (await _deal(client, hm, ids["ca"], title="A")).json()
    b = (await _deal(client, hm, ids["ca"], title="B")).json()
    c = (await _deal(client, hm, ids["ca"], title="C")).json()
    target = stages["Переговоры"]["id"]

    # в пустую колонку; без position — в конец
    await client.patch(f"/api/deals/{a['id']}/stage", json={"stage_id": target}, headers=hm)
    await client.patch(f"/api/deals/{b['id']}/stage", json={"stage_id": target}, headers=hm)
    assert await _column(client, hm, target) == ["A", "B"]
    # на позицию 0 — остальные сдвигаются
    resp = await client.patch(f"/api/deals/{c['id']}/stage", json={"stage_id": target, "position": 0}, headers=hm)
    assert resp.json()["position"] == 0
    assert await _column(client, hm, target) == ["C", "A", "B"]
    listed = (await client.get("/api/deals", params={"stage_id": target}, headers=hm)).json()["items"]
    assert [d["position"] for d in listed] == [0, 1, 2]  # без дублей
    # position больше размера колонки — в конец
    await client.patch(f"/api/deals/{c['id']}/stage", json={"stage_id": target, "position": 99}, headers=hm)
    assert await _column(client, hm, target) == ["A", "B", "C"]


async def test_reorder_within_same_stage_without_history_noise(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    stage = (await _stages(client, hm))["Новая"]["id"]
    a = (await _deal(client, hm, ids["ca"], title="A")).json()
    await _deal(client, hm, ids["ca"], title="B")
    c = (await _deal(client, hm, ids["ca"], title="C")).json()
    resp = await client.patch(f"/api/deals/{c['id']}/stage", json={"stage_id": stage, "position": 0}, headers=hm)
    assert resp.status_code == 200
    assert await _column(client, hm, stage) == ["C", "A", "B"]
    # перестановка — не смена стадии: в истории пусто
    assert (await client.get(f"/api/deals/{a['id']}/history", headers=hm)).json() == []
    assert (await client.get(f"/api/deals/{c['id']}/history", headers=hm)).json() == []


async def test_owner_can_reorder_own_deal_but_stranger_cannot(client, world):
    _, ids, logins = world
    ho = await _headers(client, logins, "owner")
    stage = (await _stages(client, ho))["Новая"]["id"]
    d1 = (await _deal(client, ho, ids["ca"], title="A")).json()
    await _deal(client, ho, ids["ca"], title="B")
    assert (
        await client.patch(f"/api/deals/{d1['id']}/stage", json={"stage_id": stage, "position": 1}, headers=ho)
    ).status_code == 200
    h = await _headers(client, logins, "other")
    assert (
        await client.patch(f"/api/deals/{d1['id']}/stage", json={"stage_id": stage, "position": 0}, headers=h)
    ).status_code == 403


# ── история смены стадий и лента активности ──────────────────────────────────
async def test_deal_history_lists_stage_changes(client, world):
    _, ids, logins = world
    ho = await _headers(client, logins, "owner")
    hm = await _headers(client, logins, "a_manager")
    stages = await _stages(client, ho)
    deal = (await _deal(client, ho, ids["ca"], amount=500)).json()
    url = f"/api/deals/{deal['id']}"
    await client.patch(f"{url}/stage", json={"stage_id": stages["Связались"]["id"]}, headers=ho)
    await client.patch(f"{url}/stage", json={"stage_id": stages["Отказ"]["id"], "lost_reason": "Дорого"}, headers=ho)
    await client.patch(f"{url}/stage", json={"stage_id": stages["Новая"]["id"]}, headers=hm)
    await client.patch(url, json={"title": "Переименована"}, headers=ho)  # не смена стадии

    history = (await client.get(f"{url}/history", headers=ho)).json()
    assert [(h["from_stage_name"], h["to_stage_name"]) for h in history] == [
        ("Новая", "Связались"),
        ("Связались", "Отказ"),
        ("Отказ", "Новая"),
    ]
    assert history[1]["lost_reason"] == "Дорого"
    assert [h["user_id"] for h in history] == [ids["owner"], ids["owner"], ids["a_manager"]]
    assert history[2]["username"] == "a_manager"


async def test_deal_history_isolation_and_404(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    deal = (await _deal(client, ha, ids["ca"])).json()
    hb = await _headers(client, logins, "b_admin")
    assert (await client.get(f"/api/deals/{deal['id']}/history", headers=hb)).status_code == 404
    assert (await client.get("/api/deals/999999/history", headers=ha)).status_code == 404


async def test_stage_change_appears_in_activity_feed(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    stages = await _stages(client, hm)
    deal = (await _deal(client, hm, ids["ca"], title="Крупная поставка")).json()
    await client.patch(f"/api/deals/{deal['id']}/stage", json={"stage_id": stages["Переговоры"]["id"]}, headers=hm)

    feed = (await client.get("/api/analytics/activity", headers=hm)).json()["items"]
    deal_items = [i for i in feed if i["entity_type"] == "deals"]
    assert {i["action"] for i in deal_items} == {"create", "update"}
    update = next(i for i in deal_items if i["action"] == "update")
    assert update["deal_id"] == deal["id"] and update["deal_title"] == "Крупная поставка"
    assert update["task_id"] is None and update["username"] == "a_manager"
    assert update["changes"] == [{"field": "stage_id", "label": "стадия", "old": "Новая", "new": "Переговоры"}]

    # лента другой компании пуста
    hb = await _headers(client, logins, "b_admin")
    assert all(
        i["entity_type"] != "deals" for i in (await client.get("/api/analytics/activity", headers=hb)).json()["items"]
    )


# ── валюты ───────────────────────────────────────────────────────────────────
async def test_currency_defaults_to_uah_and_can_be_set_on_create(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    default = (await _deal(client, h, ids["ca"], amount=15000)).json()
    assert default["currency"] == "UAH"
    usd = (await _deal(client, h, ids["ca"], amount=2500, currency="usd")).json()  # регистр не важен
    eur = (await _deal(client, h, ids["ca"], amount=1800, currency="EUR")).json()
    assert (usd["currency"], eur["currency"]) == ("USD", "EUR")
    assert usd["amount"] == 2500 and isinstance(usd["amount"], float)


async def test_unsupported_currency_rejected(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    assert (await _deal(client, h, ids["ca"], currency="XXX")).status_code == 422
    assert (await _deal(client, h, ids["ca"], currency="")).status_code == 422
    deal = (await _deal(client, h, ids["ca"])).json()
    url = f"/api/deals/{deal['id']}"
    assert (await client.patch(url, json={"currency": "GBP"}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"currency": None}, headers=h)).status_code == 422


async def test_currency_is_process_field_only_managers_change(client, world):
    maker, ids, logins = world
    ho = await _headers(client, logins, "owner")
    deal = (await _deal(client, ho, ids["ca"], amount=100, currency="USD")).json()  # при создании — можно
    url = f"/api/deals/{deal['id']}"
    assert (await client.patch(url, json={"currency": "EUR"}, headers=ho)).status_code == 403
    assert (await client.patch(url, json={"currency": "USD", "title": "то же значение"}, headers=ho)).status_code == 200

    hm = await _headers(client, logins, "a_manager")
    resp = await client.patch(url, json={"currency": "EUR"}, headers=hm)
    assert resp.status_code == 200 and resp.json()["currency"] == "EUR"

    async with maker() as s:  # смена валюты попала в аудит
        row = (
            (
                await s.execute(
                    select(AuditLog).where(
                        and_(
                            AuditLog.entity_type == "deals",
                            AuditLog.entity_id == deal["id"],
                            AuditLog.action == AuditAction.update,
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
    assert any(
        (r.new_values or {}).get("currency") == "EUR" and (r.old_values or {}).get("currency") == "USD" for r in row
    )


async def test_currency_survives_moves_and_filters(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    stages = await _stages(client, hm)
    deal = (await _deal(client, hm, ids["ca"], amount=2500, currency="USD")).json()
    won = await client.patch(f"/api/deals/{deal['id']}/stage", json={"stage_id": stages["Успех"]["id"]}, headers=hm)
    assert won.status_code == 200 and won.json()["currency"] == "USD" and won.json()["amount"] == 2500
    listed = (await client.get("/api/deals", params={"stage_id": stages["Успех"]["id"]}, headers=hm)).json()["items"]
    assert [d["currency"] for d in listed] == ["USD"]


async def test_feed_hides_closed_at_and_formats_dates(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    stages = await _stages(client, hm)
    deal = (await _deal(client, hm, ids["ca"], amount=100)).json()
    await client.patch(f"/api/deals/{deal['id']}", json={"expected_close_date": "2026-12-01"}, headers=hm)
    await client.patch(f"/api/deals/{deal['id']}/stage", json={"stage_id": stages["Успех"]["id"]}, headers=hm)

    feed = (await client.get("/api/analytics/activity", headers=hm)).json()["items"]
    updates = [i for i in feed if i["entity_type"] == "deals" and i["action"] == "update"]
    fields = {c["field"] for i in updates for c in i["changes"]}
    assert "closed_at" not in fields  # дата закрытия — шум, смена стадии уже показана
    assert "stage_id" in fields
    date_change = next(c for i in updates for c in i["changes"] if c["field"] == "expected_close_date")
    assert date_change["new"] == "01.12.2026" and date_change["old"] == "—"


async def test_feed_shows_user_names_and_hides_completed_at(client, world):
    _, ids, logins = world
    # уведомление об исполнителе уходит фоновой задачей со своей сессией БД — в тесте оно не нужно
    with (
        patch("src.services.task_service.notify_task_assigned", new_callable=AsyncMock),
        patch("src.routers.tasks_router.notify_task_assigned", new_callable=AsyncMock),
    ):
        await _feed_names_scenario(client, ids, logins)


async def _feed_names_scenario(client, ids, logins):
    hm = await _headers(client, logins, "a_manager")

    # сделка: смена ответственного — имена, а не номера
    deal = (await _deal(client, hm, ids["ca"])).json()
    await client.patch(f"/api/deals/{deal['id']}", json={"owner_id": ids["other"]}, headers=hm)

    # задача: смена исполнителя и закрытие — имена, и без служебной даты completed_at
    task = await client.post("/api/tasks", json={"title": "Позвонить", "user_id": ids["a_manager"]}, headers=hm)
    assert task.status_code in (200, 201), task.text
    task_id = task.json()["id"]
    resp = await client.patch(f"/api/tasks/{task_id}/reassign", params={"user_id": ids["other"]}, headers=hm)
    assert resp.status_code == 200, resp.text
    resp = await client.patch(f"/api/tasks/{task_id}/status", json={"status": "done"}, headers=hm)
    assert resp.status_code == 200, resp.text

    feed = (await client.get("/api/analytics/activity", headers=hm)).json()["items"]
    changes = [c for i in feed for c in i["changes"]]
    owner = next(c for c in changes if c["field"] == "owner_id")
    assert (owner["old"], owner["new"]) == ("a_manager", "other")
    assignee = [c for c in changes if c["field"] == "user_id"]
    assert assignee and all(not c["new"].isdigit() for c in assignee)
    assert any(c["new"] == "other" for c in assignee)
    assert "completed_at" not in {c["field"] for c in changes}
    assert any(c["field"] == "status" for c in changes)  # смена статуса при этом видна


# ── сводка по воронке ────────────────────────────────────────────────────────
async def _summary(client, headers, **params):
    resp = await client.get("/api/pipeline/summary", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _stage(summary, name):
    return next(s for s in summary["stages"] if s["name"] == name)


def _totals(item):
    return {t["currency"]: (t["count"], t["amount"]) for t in item["totals"]}


async def test_summary_empty_pipeline(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    summary = await _summary(client, h)
    assert [s["name"] for s in summary["stages"]][:2] == ["Новая", "Связались"]  # порядок воронки
    assert all(s["count"] == 0 and s["totals"] == [] for s in summary["stages"])
    assert summary["conversion"] == {"open": 0, "won": 0, "lost": 0, "closed": 0, "win_rate": None}


async def test_summary_counts_and_sums_per_stage_and_currency(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    stages = await _stages(client, h)
    await _deal(client, h, ids["ca"], amount=15000)  # UAH, Новая
    await _deal(client, h, ids["ca"], amount=1000)  # UAH, Новая
    await _deal(client, h, ids["ca"], amount=2500, currency="USD")  # USD, Новая
    await _deal(client, h, ids["ca"], title="Без суммы")  # UAH без суммы: в count, не в amount
    negotiating = (await _deal(client, h, ids["ca"], amount=1800, currency="EUR")).json()
    await client.patch(
        f"/api/deals/{negotiating['id']}/stage", json={"stage_id": stages["Переговоры"]["id"]}, headers=h
    )

    summary = await _summary(client, h)
    new = _stage(summary, "Новая")
    assert new["count"] == 5 - 1
    assert _totals(new) == {"UAH": (3, 16000.0), "USD": (1, 2500.0)}  # суммы разных валют отдельно
    talks = _stage(summary, "Переговоры")
    assert talks["count"] == 1 and _totals(talks) == {"EUR": (1, 1800.0)}
    assert _stage(summary, "Предложение")["totals"] == []
    assert summary["by_kind"]["open"]["count"] == 5
    assert _totals(summary["by_kind"]["open"]) == {"UAH": (3, 16000.0), "USD": (1, 2500.0), "EUR": (1, 1800.0)}


async def test_summary_conversion(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    stages = await _stages(client, h)

    async def close(deal, stage, **body):
        resp = await client.patch(
            f"/api/deals/{deal['id']}/stage", json={"stage_id": stages[stage]["id"], **body}, headers=h
        )
        assert resp.status_code == 200, resp.text

    for _ in range(3):  # 3 выиграны
        await close((await _deal(client, h, ids["ca"], amount=100)).json(), "Успех")
    await close((await _deal(client, h, ids["ca"], amount=500, currency="USD")).json(), "Отказ", lost_reason="Дорого")
    await _deal(client, h, ids["ca"])  # одна в работе

    summary = await _summary(client, h)
    assert summary["conversion"] == {"open": 1, "won": 3, "lost": 1, "closed": 4, "win_rate": 0.75}
    assert _totals(summary["by_kind"]["won"]) == {"UAH": (3, 300.0)}
    assert _totals(summary["by_kind"]["lost"]) == {"USD": (1, 500.0)}


async def test_summary_owner_filter_and_deleted_deals(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    await _deal(client, hm, ids["ca"], amount=100, owner_id=ids["other"])
    mine = (await _deal(client, hm, ids["ca"], amount=200)).json()
    gone = (await _deal(client, hm, ids["ca"], amount=400)).json()
    await client.delete(f"/api/deals/{gone['id']}", headers=hm)  # удалённая в сводку не входит

    assert _stage(await _summary(client, hm), "Новая")["count"] == 2
    only_other = await _summary(client, hm, owner_id=ids["other"])
    assert _totals(_stage(only_other, "Новая")) == {"UAH": (1, 100.0)}
    only_me = await _summary(client, hm, owner_id=ids["a_manager"])
    assert _totals(_stage(only_me, "Новая")) == {"UAH": (1, 200.0)} and mine["id"]


async def test_summary_is_per_company_and_readable_by_everyone(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    await _deal(client, ha, ids["ca"], amount=999)
    hb = await _headers(client, logins, "b_admin")
    summary_b = await _summary(client, hb)
    assert all(s["count"] == 0 for s in summary_b["stages"])  # чужих сделок не видно
    h = await _headers(client, logins, "other")  # обычный пользователь читает сводку
    assert _stage(await _summary(client, h), "Новая")["count"] == 1


# ── тип клиента в сделках и в сводке ─────────────────────────────────────────
async def _person(client, headers, name="Иванов Иван"):
    resp = await client.post("/api/clients", json={"name": name, "client_type": "person"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_deal_shows_client_name_and_type(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    person = await _person(client, h)
    company_deal = await _deal(client, h, ids["ca"], title="B2B сделка")
    person_deal = await _deal(client, h, person["id"], title="B2C сделка")
    assert company_deal.status_code == person_deal.status_code == 201
    assert (company_deal.json()["client_name"], company_deal.json()["client_type"]) == ("Ромашка", "company")
    assert (person_deal.json()["client_name"], person_deal.json()["client_type"]) == ("Иванов Иван", "person")

    # то же в получении, списке, правке и переводе по стадии
    did = person_deal.json()["id"]
    assert (await client.get(f"/api/deals/{did}", headers=h)).json()["client_type"] == "person"
    patched = await client.patch(f"/api/deals/{did}", json={"title": "Новое имя"}, headers=h)
    assert patched.json()["client_name"] == "Иванов Иван"
    stages = await _stages(client, h)
    moved = await client.patch(f"/api/deals/{did}/stage", json={"stage_id": stages["Переговоры"]["id"]}, headers=h)
    assert moved.status_code == 200 and moved.json()["client_type"] == "person"
    listed = (await client.get("/api/deals", headers=h)).json()["items"]
    assert {d["title"]: d["client_type"] for d in listed} == {"B2B сделка": "company", "Новое имя": "person"}


async def test_deals_filter_by_client_type(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    person = await _person(client, h)
    await _deal(client, h, ids["ca"], title="B2B")
    await _deal(client, h, person["id"], title="B2C-1")
    await _deal(client, h, person["id"], title="B2C-2")

    def titles(resp):
        return sorted(d["title"] for d in resp.json()["items"])

    assert titles(await client.get("/api/deals", params={"client_type": "person"}, headers=h)) == ["B2C-1", "B2C-2"]
    assert titles(await client.get("/api/deals", params={"client_type": "company"}, headers=h)) == ["B2B"]
    assert (await client.get("/api/deals", params={"client_type": "person"}, headers=h)).json()["total"] == 2
    assert (await client.get("/api/deals", params={"client_type": "bogus"}, headers=h)).status_code == 422


async def test_summary_filter_by_client_type(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    person = await _person(client, h)
    stages = await _stages(client, h)
    await _deal(client, h, ids["ca"], amount=1000)  # B2B, UAH
    won = (await _deal(client, h, person["id"], amount=200, currency="USD")).json()  # B2C, USD
    await _deal(client, h, person["id"], amount=50, currency="USD")
    await client.patch(f"/api/deals/{won['id']}/stage", json={"stage_id": stages["Успех"]["id"]}, headers=h)

    async def summary(**params):
        resp = await client.get("/api/pipeline/summary", params=params, headers=h)
        assert resp.status_code == 200, resp.text
        return resp.json()

    everything = await summary()
    assert everything["by_kind"]["open"]["count"] == 2 and everything["by_kind"]["won"]["count"] == 1
    b2c = await summary(client_type="person")
    assert b2c["by_kind"]["open"]["count"] == 1 and b2c["by_kind"]["won"]["count"] == 1
    assert [(t["currency"], t["amount"]) for t in b2c["by_kind"]["open"]["totals"]] == [("USD", 50.0)]
    assert b2c["conversion"]["win_rate"] == 1.0
    b2b = await summary(client_type="company")
    assert b2b["by_kind"]["open"]["count"] == 1 and b2b["by_kind"]["won"]["count"] == 0
    assert [(t["currency"], t["amount"]) for t in b2b["by_kind"]["open"]["totals"]] == [("UAH", 1000.0)]
    assert b2b["conversion"]["win_rate"] is None  # у B2B ещё нет закрытых сделок
    assert (await client.get("/api/pipeline/summary", params={"client_type": "x"}, headers=h)).status_code == 422
