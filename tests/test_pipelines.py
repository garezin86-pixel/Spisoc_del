# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_pipelines.py
"""Несколько воронок и цвета стадий.

Воронки создаёт, переименовывает и удаляет только admin; у каждой свои стадии; сделка живёт в своей воронке
и не переводится в стадию другой; сводка считается по выбранной воронке; у стадии свой цвет (#rrggbb).
"""

from sqlalchemy import select

from src.models.deal import PipelineModel, StageModel
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)


async def _list(client, headers):
    resp = await client.get("/api/pipelines", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _create(client, headers, **body):
    return await client.post("/api/pipelines", json=body, headers=headers)


def _names(pipeline):
    return [s["name"] for s in pipeline["stages"]]


async def _deal(client, headers, client_id, **payload):
    payload.setdefault("title", "Сделка")
    return await client.post(f"/api/clients/{client_id}/deals", json=payload, headers=headers)


# ── список и создание ────────────────────────────────────────────────────────
async def test_list_creates_default_pipeline_and_counts_deals(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "other")  # читать может любой
    pipelines = await _list(client, h)
    assert len(pipelines) == 1 and pipelines[0]["name"] == "Продажи"
    assert _names(pipelines[0])[:2] == ["Новая", "Связались"] and pipelines[0]["deals_count"] == 0

    hm = await _headers(client, logins, "a_manager")
    await _deal(client, hm, ids["ca"])
    assert (await _list(client, h))[0]["deals_count"] == 1
    assert len(await _list(client, h)) == 1  # повторно не создаётся


async def test_admin_creates_minimal_and_copied_pipeline(client, world):
    _, _, logins = world
    ha = await _headers(client, logins, "a_admin")
    base = (await _list(client, ha))[0]

    minimal = await _create(client, ha, name="  Партнёры  ")
    assert minimal.status_code == 201, minimal.text
    body = minimal.json()
    assert body["name"] == "Партнёры"
    assert [(s["name"], s["kind"]) for s in body["stages"]] == [("Новая", "open"), ("Успех", "won"), ("Отказ", "lost")]
    assert body["id"] != base["id"] and body["deals_count"] == 0

    # копия: стадии, порядок, виды и цвета переносятся, id у стадий новые
    await client.patch(f"/api/pipeline/stages/{base['stages'][0]['id']}", json={"color": "#FF8800"}, headers=ha)
    copy = (await _create(client, ha, name="Копия", copy_from_id=base["id"])).json()
    assert _names(copy) == _names(base)
    assert copy["stages"][0]["color"] == "#ff8800"
    assert {s["id"] for s in copy["stages"]}.isdisjoint({s["id"] for s in base["stages"]})
    assert [p["name"] for p in await _list(client, ha)] == ["Продажи", "Партнёры", "Копия"]


async def test_create_pipeline_permissions_and_validation(client, world):
    _, _, logins = world
    hm = await _headers(client, logins, "a_manager")
    assert (await _create(client, hm, name="X")).status_code == 403  # manager не управляет воронками
    ha = await _headers(client, logins, "a_admin")
    assert (await _create(client, ha, name="   ")).status_code == 422
    assert (await _create(client, ha, name="")).status_code == 422
    assert (await _create(client, ha, name="X", copy_from_id=999999)).status_code == 404


# ── переименование и удаление ────────────────────────────────────────────────
async def test_rename_and_delete_pipeline_guards(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    only = (await _list(client, ha))[0]
    assert (await client.delete(f"/api/pipelines/{only['id']}", headers=ha)).status_code == 409  # единственная

    second = (await _create(client, ha, name="Вторая")).json()
    renamed = await client.patch(f"/api/pipelines/{second['id']}", json={"name": "Переименована"}, headers=ha)
    assert renamed.status_code == 200 and renamed.json()["name"] == "Переименована"
    hm = await _headers(client, logins, "a_manager")
    assert (await client.patch(f"/api/pipelines/{second['id']}", json={"name": "X"}, headers=hm)).status_code == 403
    assert (await client.delete(f"/api/pipelines/{second['id']}", headers=hm)).status_code == 403

    # со сделкой удалить нельзя
    stage = second["stages"][0]["id"]
    deal = await _deal(client, ha, ids["ca"], pipeline_id=second["id"], stage_id=stage)
    assert deal.status_code == 201, deal.text
    assert (await client.delete(f"/api/pipelines/{second['id']}", headers=ha)).status_code == 409

    await client.delete(f"/api/deals/{deal.json()['id']}", headers=ha)  # сделка удалена — воронку можно
    assert (await client.delete(f"/api/pipelines/{second['id']}", headers=ha)).status_code == 200
    assert [p["name"] for p in await _list(client, ha)] == ["Продажи"]
    assert (await client.get(f"/api/pipeline?pipeline_id={second['id']}", headers=ha)).status_code == 404


async def test_delete_pipeline_soft_deletes_stages(client, world):
    maker, _, logins = world
    ha = await _headers(client, logins, "a_admin")
    await _list(client, ha)
    second = (await _create(client, ha, name="Временная")).json()
    await client.delete(f"/api/pipelines/{second['id']}", headers=ha)
    async with maker() as s:
        pipeline = (await s.execute(select(PipelineModel).where(PipelineModel.id == second["id"]))).scalar_one()
        stages = (await s.execute(select(StageModel).where(StageModel.pipeline_id == second["id"]))).scalars().all()
    assert pipeline.deleted_at is not None and len(stages) == 3 and all(st.deleted_at for st in stages)


# ── изоляция компаний ────────────────────────────────────────────────────────
async def test_pipelines_are_per_company(client, world):
    _, _, logins = world
    ha = await _headers(client, logins, "a_admin")
    created = (await _create(client, ha, name="Секретная")).json()
    hb = await _headers(client, logins, "b_admin")
    assert [p["name"] for p in await _list(client, hb)] == ["Продажи"]  # у B своя, чужой нет
    assert (await client.get(f"/api/pipeline?pipeline_id={created['id']}", headers=hb)).status_code == 404
    assert (
        await client.patch(f"/api/pipelines/{created['id']}", json={"name": "взлом"}, headers=hb)
    ).status_code == 404
    assert (await client.delete(f"/api/pipelines/{created['id']}", headers=hb)).status_code == 404
    assert (await _create(client, hb, name="Копия чужой", copy_from_id=created["id"])).status_code == 404
    assert (await client.get(f"/api/pipeline/summary?pipeline_id={created['id']}", headers=hb)).status_code == 404


# ── стадии конкретной воронки ────────────────────────────────────────────────
async def test_stages_belong_to_their_pipeline(client, world):
    _, _, logins = world
    ha = await _headers(client, logins, "a_admin")
    base = (await _list(client, ha))[0]
    second = (await _create(client, ha, name="Вторая")).json()

    added = await client.post("/api/pipeline/stages", json={"name": "Договор", "pipeline_id": second["id"]}, headers=ha)
    assert added.status_code == 201 and added.json()["position"] == 3  # в конец второй воронки
    # без pipeline_id — в воронку по умолчанию (как раньше)
    default = await client.post("/api/pipeline/stages", json={"name": "Доп"}, headers=ha)
    assert default.status_code == 201 and default.json()["position"] == len(base["stages"])

    after = {p["id"]: p for p in await _list(client, ha)}
    assert _names(after[second["id"]]) == ["Новая", "Успех", "Отказ", "Договор"]
    assert _names(after[base["id"]])[-1] == "Доп" and "Договор" not in _names(after[base["id"]])

    # порядок меняется внутри своей воронки, другую не трогает
    await client.patch(f"/api/pipeline/stages/{added.json()['id']}", json={"position": 0}, headers=ha)
    after = {p["id"]: p for p in await _list(client, ha)}
    assert _names(after[second["id"]])[0] == "Договор"
    assert _names(after[base["id"]]) == _names(base) + ["Доп"]
    assert (
        await client.post("/api/pipeline/stages", json={"name": "X", "pipeline_id": 999999}, headers=ha)
    ).status_code == 404


async def test_last_stage_of_kind_rule_is_per_pipeline(client, world):
    _, _, logins = world
    ha = await _headers(client, logins, "a_admin")
    base = (await _list(client, ha))[0]
    second = (await _create(client, ha, name="Вторая")).json()
    won_second = next(s for s in second["stages"] if s["kind"] == "won")
    won_base = next(s for s in base["stages"] if s["kind"] == "won")
    assert (
        await client.delete(f"/api/pipeline/stages/{won_second['id']}", headers=ha)
    ).status_code == 409  # там она единственная
    await client.post(
        "/api/pipeline/stages", json={"name": "Успех 2", "kind": "won", "pipeline_id": second["id"]}, headers=ha
    )
    assert (await client.delete(f"/api/pipeline/stages/{won_second['id']}", headers=ha)).status_code == 200
    assert won_base["id"]  # стадии первой воронки не затронуты


# ── сделки в своей воронке ───────────────────────────────────────────────────
async def test_deal_created_in_chosen_pipeline(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    base = (await _list(client, ha))[0]
    second = (await _create(client, ha, name="Вторая")).json()

    in_second = (await _deal(client, ha, ids["ca"], pipeline_id=second["id"])).json()
    assert in_second["stage_id"] == second["stages"][0]["id"]  # первая открытая стадия выбранной воронки
    in_default = (await _deal(client, ha, ids["ca"])).json()
    assert in_default["stage_id"] == base["stages"][0]["id"]

    # стадия чужой воронки при указанном pipeline_id — ошибка
    bad = await _deal(client, ha, ids["ca"], pipeline_id=second["id"], stage_id=base["stages"][0]["id"])
    assert bad.status_code == 422
    assert (await _deal(client, ha, ids["ca"], pipeline_id=999999)).status_code == 404
    counts = {p["id"]: p["deals_count"] for p in await _list(client, ha)}
    assert counts == {base["id"]: 1, second["id"]: 1}


async def test_deal_cannot_move_to_other_pipeline_stage(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    base = (await _list(client, ha))[0]
    second = (await _create(client, ha, name="Вторая")).json()
    deal = (await _deal(client, ha, ids["ca"])).json()
    foreign_stage = second["stages"][0]["id"]
    resp = await client.patch(f"/api/deals/{deal['id']}/stage", json={"stage_id": foreign_stage}, headers=ha)
    assert resp.status_code == 422
    same = await client.patch(f"/api/deals/{deal['id']}/stage", json={"stage_id": base["stages"][1]["id"]}, headers=ha)
    assert same.status_code == 200  # внутри своей воронки — можно


async def test_summary_is_per_pipeline(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    base = (await _list(client, ha))[0]
    second = (await _create(client, ha, name="Партнёры")).json()
    await _deal(client, ha, ids["ca"], amount=100)
    await _deal(client, ha, ids["ca"], amount=500, currency="USD", pipeline_id=second["id"])

    def get(pid=None):
        return client.get("/api/pipeline/summary", params={"pipeline_id": pid} if pid else {}, headers=ha)

    default = (await get()).json()  # без параметра — воронка по умолчанию
    assert default["pipeline_id"] == base["id"] and default["by_kind"]["open"]["count"] == 1
    other = (await get(second["id"])).json()
    assert other["pipeline_id"] == second["id"] and other["pipeline_name"] == "Партнёры"
    assert other["by_kind"]["open"]["count"] == 1
    assert [t["currency"] for t in other["by_kind"]["open"]["totals"]] == ["USD"]
    assert [s["name"] for s in other["stages"]] == ["Новая", "Успех", "Отказ"]


# ── цвета стадий ─────────────────────────────────────────────────────────────
async def test_stage_color_set_normalized_and_reset(client, world):
    _, _, logins = world
    ha = await _headers(client, logins, "a_admin")
    base = (await _list(client, ha))[0]
    assert all(s["color"] is None for s in base["stages"])  # по умолчанию — цвет по виду стадии

    created = await client.post("/api/pipeline/stages", json={"name": "Цветная", "color": "#AbCdEf"}, headers=ha)
    assert created.status_code == 201 and created.json()["color"] == "#abcdef"  # нормализуется в нижний регистр

    sid = base["stages"][0]["id"]
    set_color = await client.patch(f"/api/pipeline/stages/{sid}", json={"color": "#FF0000"}, headers=ha)
    assert set_color.status_code == 200 and set_color.json()["color"] == "#ff0000"
    other_field = await client.patch(f"/api/pipeline/stages/{sid}", json={"name": "Переименована"}, headers=ha)
    assert other_field.json()["color"] == "#ff0000"  # цвет не теряется при правке другого поля
    reset = await client.patch(f"/api/pipeline/stages/{sid}", json={"color": None}, headers=ha)
    assert reset.status_code == 200 and reset.json()["color"] is None
    blank = await client.patch(f"/api/pipeline/stages/{sid}", json={"color": ""}, headers=ha)
    assert blank.json()["color"] is None


async def test_stage_color_validation_and_permissions(client, world):
    _, _, logins = world
    ha = await _headers(client, logins, "a_admin")
    sid = (await _list(client, ha))[0]["stages"][0]["id"]
    for bad in ("red", "#fff", "#12345g", "ff0000", "#ff00000", "rgb(1,2,3)"):
        assert (
            await client.patch(f"/api/pipeline/stages/{sid}", json={"color": bad}, headers=ha)
        ).status_code == 422, bad
        assert (
            await client.post("/api/pipeline/stages", json={"name": "X", "color": bad}, headers=ha)
        ).status_code == 422, bad
    hm = await _headers(client, logins, "a_manager")
    assert (await client.patch(f"/api/pipeline/stages/{sid}", json={"color": "#00ff00"}, headers=hm)).status_code == 403


async def test_color_in_pipeline_get_and_summary(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    sid = (await _list(client, ha))[0]["stages"][0]["id"]
    await client.patch(f"/api/pipeline/stages/{sid}", json={"color": "#123abc"}, headers=ha)

    pipeline = (await client.get("/api/pipeline", headers=ha)).json()
    assert pipeline["stages"][0]["color"] == "#123abc"
    summary = (await client.get("/api/pipeline/summary", headers=ha)).json()
    assert summary["stages"][0]["color"] == "#123abc" and summary["stages"][1]["color"] is None
