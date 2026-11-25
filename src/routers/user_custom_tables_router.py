# src/routers/user_custom_tables_router.py
"""Самостоятельные таблицы пользователей (Smart Tables, этап 4.1): таблицы и колонки."""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import TypeAdapter, ValidationError

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.client_repository import ClientRepository
from src.repositories.deal_repository import DealRepository
from src.repositories.user_custom_table_repository import UserCustomTableRepository
from src.repositories.user_custom_table_row_repository import UserCustomTableRowRepository
from src.repositories.users_repository import UserRepository
from src.schemas.user_custom_table import (
    UserTableColumnCreate,
    UserTableColumnSchema,
    UserTableColumnUpdate,
    UserTableCreate,
    UserTableListItem,
    UserTableMemberSchema,
    UserTableMembersUpdate,
    UserTableRowCreate,
    UserTableRowSchema,
    UserTableRowsPage,
    UserTableRowUpdate,
    UserTableSchema,
    UserTableUpdate,
)
from src.schemas.user_table_import import ImportFileColumns, TableImportColumnSpec, TableImportReport
from src.services.user_custom_table_row_service import UserCustomTableRowService
from src.services.user_custom_table_service import UserCustomTableService
from src.services.user_table_import_service import UserTableImportService, describe_file

router = APIRouter(prefix="/user-custom-tables", tags=["User custom tables"])


def get_user_table_service(session: SessionDep) -> UserCustomTableService:
    return UserCustomTableService(UserCustomTableRepository(session), UserRepository(session))


def get_user_table_row_service(session: SessionDep) -> UserCustomTableRowService:
    return UserCustomTableRowService(
        UserCustomTableRowRepository(session),
        get_user_table_service(session),
        ClientRepository(session),
        DealRepository(session),
        UserRepository(session),
    )


def get_user_table_import_service(session: SessionDep) -> UserTableImportService:
    return UserTableImportService(get_user_table_service(session), UserCustomTableRowRepository(session))


_SPECS = TypeAdapter(list[TableImportColumnSpec])


def _parse_mapping(raw: str) -> dict[str, int]:
    """`{"c12": 0, "c13": 2}` — колонка таблицы → номер колонки файла (с 0)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict) or any(not isinstance(v, int) or isinstance(v, bool) for v in data.values()):
        raise HTTPException(422, "Сопоставление должно быть JSON-объектом {ключ колонки таблицы: номер колонки файла}")
    return data


def _parse_specs(raw: str | None) -> list[TableImportColumnSpec] | None:
    if raw is None or not raw.strip():
        return None
    try:
        return _SPECS.validate_python(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(
            422, 'Колонки должны быть JSON-списком [{"index": 0, "name": "...", "data_type": "text"}]'
        ) from exc


@router.get(
    "",
    response_model=list[UserTableListItem],
    summary="Самостоятельные таблицы",
    description="Таблицы, которые видит пользователь: общие и свои личные (admin и manager видят все).",
)
async def list_tables(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_service(session).list_tables(current_user)


@router.post(
    "",
    response_model=UserTableSchema,
    status_code=201,
    summary="Создать таблицу",
    description="Таблица со своими колонками (можно сразу передать `columns`, до 50). Типы колонок: text, number, "
    "date, boolean, select. `visibility`: private — владелец, admin и manager; shared — вся компания. "
    "Создать может любой пользователь, владелец — создатель. До 100 таблиц на компанию.",
    responses={409: {"description": "Достигнут лимит таблиц"}},
)
async def create_table(
    data: UserTableCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_service(session).create_table(data, current_user)


# Маршруты импорта стоят до `/{table_id}`: иначе «from-file» принимался бы за номер таблицы.
@router.post(
    "/from-file/columns",
    response_model=ImportFileColumns,
    summary="Создание таблицы из файла: колонки файла",
    description="Читает .csv/.xlsx и возвращает колонки с примерами значений и подсказанным типом (text, number, "
    "date, boolean). Числа с ведущим нулём и длинные цифровые значения (телефон, ЛС) остаются текстом. "
    "Ничего не создаёт. Доступно любому пользователю.",
    responses={422: {"description": "Файл не удалось прочитать"}},
)
async def from_file_columns(
    file: UploadFile = File(...),
    current_user: UserModel = Depends(get_current_user),
):
    return describe_file(file.filename or "", await file.read())


@router.post(
    "/from-file",
    response_model=TableImportReport,
    summary="Создать таблицу из CSV/Excel",
    description="Создаёт таблицу `name` из файла: колонки и их типы берутся из заголовков и значений. "
    '`columns` (необязательно) — JSON `[{"index": 0, "name": "Название", "data_type": "text"}]`: какие колонки '
    "файла брать и каким типом (text, number, date, boolean, select с `options`); без него берутся все колонки "
    "(до 50) с подсказанными типами. Неверное значение ячейки остаётся пустым, в отчёте есть предупреждение с номером "
    "строки. `dry_run=true` ничего не создаёт и возвращает тот же отчёт — предпросмотр. Таблица и строки создаются "
    "одной транзакцией; владелец — тот, кто импортирует. До 5000 строк и 5 МБ за раз. Доступно любому пользователю.",
    responses={
        409: {"description": "Достигнут лимит таблиц или строк"},
        422: {"description": "Файл, название или колонки не подходят"},
    },
)
async def create_table_from_file(
    session: SessionDep,
    file: UploadFile = File(...),
    name: str = Form(..., max_length=200),
    visibility: str = Form("shared"),
    columns: str | None = Form(None),
    dry_run: bool = Form(False),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_import_service(session).create_from_file(
        filename=file.filename or "",
        content=await file.read(),
        name=name,
        visibility=visibility,
        specs=_parse_specs(columns),
        user=current_user,
        dry_run=dry_run,
    )


@router.post(
    "/{table_id}/import/columns",
    response_model=ImportFileColumns,
    summary="Импорт в таблицу: колонки файла",
    description="Колонки файла с примерами значений и подсказкой, какая колонка таблицы к какой колонке файла "
    "подходит (по совпадению названий без учёта регистра). Колонки-связи (client, deal, user) помечены "
    "`importable: false`. Ничего не создаёт. Доступно тем, кто может менять строки таблицы.",
    responses={
        403: {"description": "В этой таблице только чтение"},
        404: {"description": "Таблица не найдена"},
        422: {"description": "Файл не удалось прочитать"},
    },
)
async def import_columns(
    table_id: int,
    session: SessionDep,
    file: UploadFile = File(...),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_import_service(session).describe_for_table(
        table_id, file.filename or "", await file.read(), current_user
    )


@router.post(
    "/{table_id}/import",
    response_model=TableImportReport,
    summary="Импорт строк из CSV/Excel в таблицу",
    description="Добавляет строки из файла по сопоставлению `mapping` (JSON `{ключ колонки таблицы: номер колонки "
    "файла}`, номера с 0). Значения приводятся к типам колонок: числа с запятой и пробелами («1 234,50»), даты "
    "«ДД.ММ.ГГГГ», да/нет, значения списка без учёта регистра. Неверное значение остаётся пустым, в отчёте есть "
    "предупреждение с номером строки; строка без единого значения пропускается. `dry_run=true` ничего не пишет и "
    "возвращает тот же отчёт — предпросмотр. Все строки добавляются одной транзакцией. Колонки-связи из файла не "
    "заполняются. До 5000 строк и 5 МБ за раз, в таблице не больше 50 000 строк. Доступно тем, кто может менять "
    "строки таблицы (участник только для чтения — 403).",
    responses={
        403: {"description": "В этой таблице только чтение"},
        404: {"description": "Таблица не найдена"},
        409: {"description": "Достигнут лимит строк"},
        422: {"description": "Файл или сопоставление не подходят"},
    },
)
async def import_rows(
    table_id: int,
    session: SessionDep,
    file: UploadFile = File(...),
    mapping: str = Form(...),
    dry_run: bool = Form(False),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_import_service(session).import_rows(
        table_id,
        filename=file.filename or "",
        content=await file.read(),
        mapping=_parse_mapping(mapping),
        user=current_user,
        dry_run=dry_run,
    )


@router.get(
    "/{table_id}",
    response_model=UserTableSchema,
    summary="Таблица и её колонки",
    responses={404: {"description": "Таблица не найдена (или чужая личная)"}},
)
async def get_table(
    table_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_service(session).get_table(table_id, current_user)


@router.patch(
    "/{table_id}",
    response_model=UserTableSchema,
    summary="Изменить настройки таблицы",
    description="Название, описание, иконка, видимость (private, shared, restricted) — владелец, admin, manager. "
    "`owner_id` (передать другого владельца) — только admin и manager.",
    responses={
        403: {"description": "Нет прав на изменение таблицы"},
        404: {"description": "Таблица или пользователь не найдены"},
    },
)
async def update_table(
    table_id: int,
    data: UserTableUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_service(session).update_table(table_id, data, current_user)


@router.delete(
    "/{table_id}",
    summary="Удалить таблицу",
    description="Мягкое удаление: таблица исчезает, данные остаются в базе. Владелец, admin, manager.",
    responses={403: {"description": "Нет прав на удаление"}, 404: {"description": "Таблица не найдена"}},
)
async def delete_table(
    table_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_service(session).delete_table(table_id, current_user)


@router.post(
    "/{table_id}/columns",
    response_model=UserTableColumnSchema,
    status_code=201,
    summary="Добавить колонку",
    description="Тип после создания не меняется. Типы: text, number, date, boolean, select и связи client, deal, user "
    "(одна связь на ячейку; значение — id записи, существование проверяется при записи). Название уникально в "
    "таблице (без учёта регистра). До 50 колонок. Ключ колонки `c<id>` не меняется при переименовании. "
    "Владелец, admin, manager.",
    responses={
        403: {"description": "Нет прав на изменение таблицы"},
        404: {"description": "Таблица не найдена"},
        409: {"description": "Колонка с таким названием уже есть или достигнут лимит"},
    },
)
async def add_column(
    table_id: int,
    data: UserTableColumnCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_service(session).add_column(table_id, data, current_user)


@router.patch(
    "/{table_id}/columns/{column_id}",
    response_model=UserTableColumnSchema,
    summary="Изменить колонку",
    description="Название, значения списка (только select), порядок (`position`). Тип и ключ не меняются.",
    responses={
        403: {"description": "Нет прав на изменение таблицы"},
        404: {"description": "Таблица или колонка не найдены"},
        409: {"description": "Колонка с таким названием уже есть"},
    },
)
async def update_column(
    table_id: int,
    column_id: int,
    data: UserTableColumnUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_service(session).update_column(table_id, column_id, data, current_user)


@router.delete(
    "/{table_id}/columns/{column_id}",
    summary="Удалить колонку",
    description="Мягкое удаление: колонка исчезает, введённые значения остаются в базе.",
    responses={
        403: {"description": "Нет прав на изменение таблицы"},
        404: {"description": "Таблица или колонка не найдены"},
    },
)
async def delete_column(
    table_id: int,
    column_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_service(session).delete_column(table_id, column_id, current_user)


@router.get(
    "/{table_id}/members",
    response_model=list[UserTableMemberSchema],
    summary="Участники таблицы",
    description="Пользователи, которым дан доступ к таблице с видимостью `restricted`, и право менять строки. "
    "Видят только владелец, admin и manager.",
    responses={403: {"description": "Нет прав на управление таблицей"}, 404: {"description": "Таблица не найдена"}},
)
async def list_members(
    table_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_service(session).list_members(table_id, current_user)


@router.put(
    "/{table_id}/members",
    response_model=list[UserTableMemberSchema],
    summary="Задать участников таблицы",
    description="Заменяет список целиком: кого нет в списке, теряет доступ. `can_edit: false` — участник только "
    "читает. Доступ участники получают при видимости `restricted` (список можно подготовить заранее). "
    "До 100 участников, каждый — пользователь этой компании. Владелец, admin и manager видят таблицу всегда. "
    "Менять список могут только владелец, admin и manager.",
    responses={
        403: {"description": "Нет прав на управление таблицей"},
        404: {"description": "Таблица не найдена"},
        422: {"description": "Пользователь не найден"},
    },
)
async def set_members(
    table_id: int,
    data: UserTableMembersUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_service(session).set_members(table_id, data, current_user)


@router.get(
    "/{table_id}/rows",
    response_model=UserTableRowsPage,
    summary="Строки таблицы",
    description="Строки по порядку добавления. В каждой строке `values` содержит все живые колонки (ключ c<id>), "
    "пустое значение — null. Фильтры и сортировка по строкам — через общие таблицы (этап 4.3).",
    responses={404: {"description": "Таблица не найдена (или чужая личная)"}},
)
async def list_rows(
    table_id: int,
    session: SessionDep,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_row_service(session).list_rows(table_id, page, size, current_user)


@router.post(
    "/{table_id}/rows",
    response_model=UserTableRowSchema,
    status_code=201,
    summary="Добавить строку",
    description="`values` — значения по ключам колонок (`c<id>`); тип проверяется по типу колонки: text и select — "
    "строка (select — из списка), number — число (до 4 знаков после запятой), date — «ГГГГ-ММ-ДД», boolean — "
    "true/false; client, deal, user — id существующего клиента, сделки или пользователя (одна связь на ячейку). "
    "Пустая строка допустима. Добавлять может любой, кто видит таблицу (в общей — вся компания). "
    "До 50 000 строк в таблице.",
    responses={
        404: {"description": "Таблица не найдена (или чужая личная)"},
        409: {"description": "Достигнут лимит строк"},
        422: {"description": "Неизвестная колонка или значение не подходит к типу"},
    },
)
async def create_row(
    table_id: int,
    data: UserTableRowCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_row_service(session).create_row(table_id, data, current_user)


@router.patch(
    "/{table_id}/rows/{row_id}",
    response_model=UserTableRowSchema,
    summary="Изменить строку",
    description="Меняются только переданные колонки; `null` или пустая строка очищает значение. `version` — "
    "`updated_at` из последнего ответа: если строку с тех пор меняли, ответ 409 (обновите данные и повторите). "
    "Без `version` правка применяется как есть. Менять может любой, кто видит таблицу.",
    responses={
        404: {"description": "Таблица или строка не найдены"},
        409: {"description": "Строку уже изменили"},
        422: {"description": "Неизвестная колонка, неверная версия или значение не подходит к типу"},
    },
)
async def update_row(
    table_id: int,
    row_id: int,
    data: UserTableRowUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_row_service(session).update_row(table_id, row_id, data, current_user)


@router.delete(
    "/{table_id}/rows/{row_id}",
    summary="Удалить строку",
    description="Мягкое удаление (запись остаётся в аудите). Удалять может любой, кто видит таблицу.",
    responses={404: {"description": "Таблица или строка не найдены"}},
)
async def delete_row(
    table_id: int,
    row_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_user_table_row_service(session).delete_row(table_id, row_id, current_user)
