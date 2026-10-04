"""Порядок пунктов шаблона: нумерация по умолчанию и детерминированный порядок при равных order_index."""

import pytest

from src.repositories.template_repository import TemplateRepository
from src.schemas.template import TemplateCreate, TemplateItemCreate
from tests.conftest import make_user

pytestmark = pytest.mark.asyncio


async def test_omitted_order_index_defaults_to_none():
    assert TemplateItemCreate(title="x").order_index is None
    assert TemplateItemCreate(title="x", order_index=0).order_index == 0  # явный 0 — валидная позиция


async def test_items_without_order_index_are_numbered_by_position(session):
    owner = await make_user(session)
    data = TemplateCreate(title="T", items=[TemplateItemCreate(title=t) for t in ("A", "B", "C")])
    template = await TemplateRepository(session).create(owner.id, data)
    assert [(i.title, i.order_index) for i in template.items] == [("A", 0), ("B", 1), ("C", 2)]


async def test_explicit_order_index_is_respected(session):
    owner = await make_user(session)
    data = TemplateCreate(
        title="T",
        items=[TemplateItemCreate(title="late", order_index=5), TemplateItemCreate(title="first", order_index=0)],
    )
    template = await TemplateRepository(session).create(owner.id, data)
    assert [i.title for i in template.items] == ["first", "late"]


async def test_items_relationship_breaks_ties_by_id():
    """У старых шаблонов у всех пунктов order_index=0. Порядок равных ключей СУБД не гарантирует
    (SQLite случайно отдаёт по rowid, PostgreSQL — нет), поэтому tiebreak по id закреплён в самой сортировке."""
    from src.models.template import TaskTemplateModel

    order = [str(c) for c in TaskTemplateModel.items.property.order_by]
    assert order == ["task_template_items.order_index", "task_template_items.id"]
