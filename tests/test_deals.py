# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_deals.py
"""Этап 3 lite-CRM: воронка и сделки.

Правила: стадии меняет только admin; процессные поля сделки (сумма, ответственный, срок) и удаление —
admin/manager; ответственный по сделке двигает её по стадиям и правит название/заметки;
lost требует причину, won — сумму; вернуть закрытую сделку может только admin/manager; изоляция компаний.
"""

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
        ("Переговоры", "open"),
        ("Предложение", "open"),
        ("Выиграна", "won"),
        ("Проиграна", "lost"),
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
    assert created.status_code == 201 and created.json()["position"] == 5  # в конец
    renamed = await client.patch(
        f"/api/pipeline/stages/{created.json()['id']}", json={"name": "Договор подписан", "position": 1}, headers=ha
    )
    assert renamed.status_code == 200 and renamed.json()["position"] == 1
    names = [s["name"] for s in (await client.get("/api/pipeline", headers=ha)).json()["stages"]]
    assert names == ["Новая", "Договор подписан", "Переговоры", "Предложение", "Выиграна", "Проиграна"]
    positions = [s["position"] for s in (await client.get("/api/pipeline", headers=ha)).json()["stages"]]
    assert positions == list(range(6))  # без дублей и пропусков
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
    assert (await client.delete(f"/api/pipeline/stages/{stages['Выиграна']['id']}", headers=ha)).status_code == 409
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
    assert (await _deal(client, ho, ids["ca"], stage_id=stages["Выиграна"]["id"])).status_code == 422
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
    assert (await client.post(f"/api/deals/{deal_id}/move", json={"stage_id": stage_a}, headers=hb)).status_code == 404
    assert (await client.delete(f"/api/deals/{deal_id}", headers=hb)).status_code == 404
    assert (await client.get("/api/deals", headers=hb)).json()["total"] == 0

    # и свою сделку нельзя перевести на стадию чужой компании
    own_deal = (await _deal(client, hb, ids["cb"])).json()["id"]
    assert (await client.post(f"/api/deals/{own_deal}/move", json={"stage_id": stage_a}, headers=hb)).status_code == 404
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
    assert (await client.post(f"/api/deals/{deal['id']}/move", json={"stage_id": stage}, headers=h)).status_code == 403
    assert (await client.get(f"/api/deals/{deal['id']}", headers=h)).status_code == 200  # читать можно


# ── перевод по стадиям ───────────────────────────────────────────────────────
async def test_move_between_open_stages_and_noop(client, world):
    _, ids, logins = world
    ho = await _headers(client, logins, "owner")
    stages = await _stages(client, ho)
    deal = (await _deal(client, ho, ids["ca"])).json()
    url = f"/api/deals/{deal['id']}/move"
    resp = await client.post(url, json={"stage_id": stages["Предложение"]["id"]}, headers=ho)
    assert resp.status_code == 200 and resp.json()["stage_id"] == stages["Предложение"]["id"]
    assert resp.json()["closed_at"] is None
    same = await client.post(url, json={"stage_id": stages["Предложение"]["id"]}, headers=ho)
    assert same.status_code == 200 and same.json()["stage_id"] == stages["Предложение"]["id"]


async def test_lost_needs_reason_and_won_needs_amount(client, world):
    _, ids, logins = world
    ho = await _headers(client, logins, "owner")
    stages = await _stages(client, ho)
    deal = (await _deal(client, ho, ids["ca"])).json()  # без суммы
    url = f"/api/deals/{deal['id']}/move"

    assert (await client.post(url, json={"stage_id": stages["Проиграна"]["id"]}, headers=ho)).status_code == 422
    assert (
        await client.post(url, json={"stage_id": stages["Проиграна"]["id"], "lost_reason": "  "}, headers=ho)
    ).status_code == 422
    assert (await client.post(url, json={"stage_id": stages["Выиграна"]["id"]}, headers=ho)).status_code == 422

    lost = await client.post(url, json={"stage_id": stages["Проиграна"]["id"], "lost_reason": "Дорого"}, headers=ho)
    assert lost.status_code == 200
    assert lost.json()["lost_reason"] == "Дорого" and lost.json()["closed_at"] is not None


async def test_won_sets_closed_at_and_reopen_only_by_manager(client, world):
    _, ids, logins = world
    ho = await _headers(client, logins, "owner")
    hm = await _headers(client, logins, "a_manager")
    stages = await _stages(client, ho)
    deal = (await _deal(client, hm, ids["ca"], amount=1000, owner_id=ids["owner"])).json()
    url = f"/api/deals/{deal['id']}/move"

    won = await client.post(url, json={"stage_id": stages["Выиграна"]["id"]}, headers=ho)
    assert won.status_code == 200 and won.json()["closed_at"] is not None
    # ответственный закрытую сделку не возвращает и не переводит
    assert (await client.post(url, json={"stage_id": stages["Новая"]["id"]}, headers=ho)).status_code == 403
    assert (
        await client.post(url, json={"stage_id": stages["Проиграна"]["id"], "lost_reason": "x"}, headers=ho)
    ).status_code == 403
    # у выигранной сделки сумму очистить нельзя
    assert (await client.patch(f"/api/deals/{deal['id']}", json={"amount": None}, headers=hm)).status_code == 422

    reopened = await client.post(url, json={"stage_id": stages["Переговоры"]["id"]}, headers=hm)
    assert reopened.status_code == 200
    assert reopened.json()["closed_at"] is None and reopened.json()["lost_reason"] is None


async def test_reopen_clears_lost_reason(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    stages = await _stages(client, hm)
    deal = (await _deal(client, hm, ids["ca"])).json()
    url = f"/api/deals/{deal['id']}/move"
    await client.post(url, json={"stage_id": stages["Проиграна"]["id"], "lost_reason": "Ушли к конкуренту"}, headers=hm)
    back = (await client.post(url, json={"stage_id": stages["Новая"]["id"]}, headers=hm)).json()
    assert back["lost_reason"] is None and back["closed_at"] is None


async def test_move_is_audited_with_workspace_and_user(client, world):
    maker, ids, logins = world
    ho = await _headers(client, logins, "owner")
    stages = await _stages(client, ho)
    deal = (await _deal(client, ho, ids["ca"])).json()
    await client.post(f"/api/deals/{deal['id']}/move", json={"stage_id": stages["Переговоры"]["id"]}, headers=ho)

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
