# src/services/audit_names.py
"""Имена вместо номеров в журнале аудита.

В audit_log поля-ссылки (исполнитель, группа, проект, клиент) хранятся числами — в истории изменений
это выглядело как «#5». Здесь по набору записей одним запросом на таблицу собираются имена; мягко
удалённые записи тоже находятся (в истории важно, кто был исполнителем, даже если его уже убрали).
Чужие компании недоступны: запросы идут через сессию с изоляцией по workspace.
"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.client import ClientModel
from src.models.group import GroupModel
from src.models.project import ProjectModel
from src.models.user import UserModel

# поле журнала → таблица, из которой берём имя
_FIELD_TABLE = {
    "user_id": "users",
    "owner_id": "users",
    "group_id": "groups",
    "project_id": "projects",
    "client_id": "clients",
}
_TABLES = {
    "users": (UserModel.id, UserModel.username),
    "groups": (GroupModel.id, GroupModel.name),
    "projects": (ProjectModel.id, ProjectModel.name),
    "clients": (ClientModel.id, ClientModel.name),
}


def _as_id(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


async def resolve_entity_names(
    session: AsyncSession, entries: Iterable, fields: Iterable[str] | None = None
) -> dict[str, dict[int, str]]:
    """{поле: {id: имя}} для всех id, встречающихся в old_values/new_values записей аудита.

    fields — какие поля разбирать (по умолчанию все известные). Поля без найденных id в результат не попадают.
    """
    wanted = [f for f in (fields or _FIELD_TABLE) if f in _FIELD_TABLE]
    ids_by_field: dict[str, set[int]] = {f: set() for f in wanted}
    for entry in entries:
        for values in (entry.old_values, entry.new_values):
            if not values:
                continue
            for field in wanted:
                found = _as_id(values.get(field))
                if found is not None:
                    ids_by_field[field].add(found)

    names_by_table: dict[str, dict[int, str]] = {}
    result: dict[str, dict[int, str]] = {}
    for field, ids in ids_by_field.items():
        if not ids:
            continue
        table = _FIELD_TABLE[field]
        if table not in names_by_table:
            names_by_table[table] = {}
        missing = ids - names_by_table[table].keys()
        if missing:
            id_col, name_col = _TABLES[table]
            rows = await session.execute(select(id_col, name_col).where(id_col.in_(missing)))
            names_by_table[table].update({row[0]: row[1] for row in rows.all()})
        result[field] = {i: names_by_table[table][i] for i in ids if i in names_by_table[table]}
    return result
