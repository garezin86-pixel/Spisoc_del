# src/routers/client_router.py
import json
from dataclasses import asdict

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel, UserRole
from src.repositories.client_repository import ClientRepository
from src.repositories.deal_repository import DealRepository
from src.repositories.interaction_repository import InteractionRepository
from src.repositories.users_repository import UserRepository
from src.schemas.client import (
    ClientCreate,
    ClientDetailSchema,
    ClientImportColumns,
    ClientImportReport,
    ClientListSchema,
    ClientSchema,
    ClientStatus,
    ClientStatusCounts,
    ClientType,
    ClientUpdate,
    ContactCreate,
    ContactSchema,
    ContactUpdate,
)
from src.schemas.pagination import PaginatedResponse, PaginationParams
from src.services.client_import_service import ClientImportError, ClientImportService, describe_columns
from src.services.client_service import ClientService
from src.services.crm_export_service import CrmExportService, csv_response

router = APIRouter(prefix="/clients", tags=["Clients"])


def get_client_service(session: SessionDep) -> ClientService:
    return ClientService(ClientRepository(session), UserRepository(session))


def get_import_service(session: SessionDep) -> ClientImportService:
    return ClientImportService(ClientRepository(session), UserRepository(session))


def _parse_mapping(raw: str) -> dict[str, int]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Сопоставление колонок должно быть JSON-объектом {поле: номер колонки}") from exc
    if not isinstance(data, dict) or any(not isinstance(v, int) or isinstance(v, bool) for v in data.values()):
        raise HTTPException(422, "Сопоставление колонок должно быть JSON-объектом {поле: номер колонки}")
    return data


@router.get(
    "/export",
    summary="Экспорт клиентов в CSV",
    description="Выгружает клиентов в CSV (UTF-8 с BOM, разделитель «;» — открывается в Excel). Те же фильтры, что у "
    "списка клиентов. Файл можно загрузить обратно через импорт. **Требует роль admin или manager.**",
    responses={403: {"description": "Требуется роль admin или manager"}},
)
async def export_clients(
    session: SessionDep,
    search: str | None = Query(None, max_length=100),
    contact_due: bool = Query(False),
    owner_id: int | None = Query(None),
    client_type: ClientType | None = Query(None, description="company — B2B, person — B2C"),
    status: ClientStatus | None = Query(None, description="active / inactive / blacklisted"),
    current_user: UserModel = Depends(get_current_user),
):
    service = CrmExportService(ClientRepository(session), DealRepository(session), UserRepository(session))
    content = await service.clients_csv(
        current_user, search=search, owner_id=owner_id, client_type=client_type, contact_due=contact_due, status=status
    )
    return csv_response(content, "clients_export")


@router.post(
    "/import/columns",
    response_model=ClientImportColumns,
    summary="Импорт клиентов: колонки файла",
    description="Читает .csv/.xlsx и возвращает колонки с примерами значений и подсказкой, какое поле клиента "
    "к какой колонке подходит. Ничего не создаёт. **Требует роль admin или manager.**",
    responses={422: {"description": "Файл не удалось прочитать"}},
)
async def import_clients_columns(
    file: UploadFile = File(...),
    current_user: UserModel = Depends(get_current_user),
):
    if current_user.role not in (UserRole.admin, UserRole.manager):
        raise HTTPException(403, "Импортировать клиентов могут admin и manager")
    try:
        return describe_columns(file.filename or "", await file.read())
    except ClientImportError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post(
    "/import",
    response_model=ClientImportReport,
    summary="Импорт клиентов из CSV/Excel",
    description="Создаёт клиентов из файла по сопоставлению `mapping` (JSON `{поле: номер колонки}`, колонки с 0, "
    "обязательно поле `name`). С `dry_run=true` ничего не создаёт и возвращает тот же отчёт — предпросмотр. "
    "`default_type` — тип, если в файле его нет: company, person или auto (угадать по названию: «ООО …» "
    "и кавычки — компания, «Иванов Иван» — человек). "
    "Дубликаты (тот же телефон, email или, без них, то же название и тип) по умолчанию пропускаются. "
    "Все строки создаются одной транзакцией. Ответственный — из колонки `owner`, иначе тот, кто импортирует. "
    "**Требует роль admin или manager.**",
    responses={422: {"description": "Файл или сопоставление не подходят"}},
)
async def import_clients(
    session: SessionDep,
    file: UploadFile = File(...),
    mapping: str = Form(...),
    default_type: str = Form("company"),
    skip_duplicates: bool = Form(True),
    dry_run: bool = Form(False),
    current_user: UserModel = Depends(get_current_user),
):
    parsed = _parse_mapping(mapping)
    try:
        report = await get_import_service(session).import_clients(
            filename=file.filename or "",
            content=await file.read(),
            mapping=parsed,
            current_user=current_user,
            default_type=default_type,
            skip_duplicates=skip_duplicates,
            dry_run=dry_run,
        )
    except ClientImportError as exc:
        raise HTTPException(422, str(exc)) from exc
    return asdict(report)


@router.post(
    "",
    response_model=ClientSchema,
    status_code=201,
    summary="Создать клиента",
    description="Создаёт клиента. Ответственным становится создатель (или `owner_id`). "
    "**Требует роль admin или manager.**",
    responses={201: {"description": "Клиент создан"}, 403: {"description": "Требуется роль admin или manager"}},
)
async def create_client(
    data: ClientCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).create_client(data, current_user)


@router.get(
    "/status-counts",
    response_model=ClientStatusCounts,
    summary="Сколько клиентов в каждом статусе",
    description="Счётчики для вкладок списка: всего, active, inactive, blacklisted. Учитывают те же `search`, "
    "`contact_due`, `owner_id` и `client_type`, что и список, но не фильтр по статусу. Читать могут все.",
)
async def get_client_status_counts(
    session: SessionDep,
    search: str | None = Query(None, max_length=100),
    contact_due: bool = Query(False),
    owner_id: int | None = Query(None),
    client_type: ClientType | None = Query(None),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).get_status_counts(search, contact_due, owner_id, client_type)


@router.get(
    "",
    response_model=PaginatedResponse[ClientListSchema],
    summary="Список клиентов",
    description="Клиенты компании (юрлица B2B и частные лица B2C). Читать могут все. "
    "Поиск `search` — по названию, телефону и email (без учёта регистра). Фильтр `status` — active, inactive или "
    "blacklisted. В каждой строке — последняя активность (`last_interaction_at`, `last_interaction_type`).",
)
async def get_clients(
    session: SessionDep,
    search: str | None = Query(None, max_length=100, description="Поиск по названию, телефону, email"),
    contact_due: bool = Query(
        False, description="Только те, с кем пора связаться (дата следующего контакта наступила)"
    ),
    owner_id: int | None = Query(None, description="Только клиенты этого ответственного"),
    client_type: ClientType | None = Query(None, description="company — компании (B2B), person — частные лица (B2C)"),
    status: ClientStatus | None = Query(
        None, description="active — работаем, inactive — неактивные, blacklisted — чёрный список"
    ),
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
):
    clients, total = await get_client_service(session).get_clients(
        search,
        offset=pagination.offset,
        limit=pagination.size,
        contact_due=contact_due,
        owner_id=owner_id,
        client_type=client_type,
        status=status,
    )
    activity = await InteractionRepository(session).last_activity_many([c.id for c in clients])
    items = []
    for c in clients:
        item = ClientListSchema.model_validate(c)
        item.last_interaction_at, item.last_interaction_type = activity.get(c.id, (None, None))
        items.append(item)
    return PaginatedResponse.create(items=items, total=total, page=pagination.page, size=pagination.size)


@router.get(
    "/{client_id}",
    response_model=ClientDetailSchema,
    summary="Получить клиента",
    responses={404: {"description": "Клиент не найден"}},
)
async def get_client(
    client_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    client = await get_client_service(session).get_client(client_id)
    detail = ClientDetailSchema.model_validate(client)
    detail.last_interaction_at = await InteractionRepository(session).last_occurred_at(client_id)
    return detail


@router.patch(
    "/{client_id}",
    response_model=ClientSchema,
    summary="Обновить клиента",
    description="Меняются только переданные поля. **Требует роль admin/manager или быть ответственным за клиента.** "
    "Менять `owner_id` могут только admin и manager.",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Клиент не найден"}},
)
async def update_client(
    client_id: int,
    data: ClientUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).update_client(client_id, data, current_user)


@router.delete(
    "/{client_id}",
    response_model=dict,
    summary="Удалить клиента",
    description="Мягкое удаление клиента вместе с его контактами. **Требует роль admin или manager.**",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Клиент не найден"}},
)
async def delete_client(
    client_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).delete_client(client_id, current_user)


@router.get(
    "/{client_id}/contacts",
    response_model=list[ContactSchema],
    summary="Контакты клиента",
    responses={404: {"description": "Клиент не найден"}},
)
async def get_contacts(
    client_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).get_contacts(client_id)


@router.post(
    "/{client_id}/contacts",
    response_model=ContactSchema,
    status_code=201,
    summary="Добавить контакт клиенту",
    description="**Требует роль admin/manager или быть ответственным за клиента.**",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Клиент не найден"}},
)
async def create_contact(
    client_id: int,
    data: ContactCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).create_contact(client_id, data, current_user)


@router.patch(
    "/{client_id}/contacts/{contact_id}",
    response_model=ContactSchema,
    summary="Обновить контакт",
    description="**Требует роль admin/manager или быть ответственным за клиента.**",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Клиент или контакт не найден"}},
)
async def update_contact(
    client_id: int,
    contact_id: int,
    data: ContactUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).update_contact(client_id, contact_id, data, current_user)


@router.delete(
    "/{client_id}/contacts/{contact_id}",
    response_model=dict,
    summary="Удалить контакт",
    description="Мягкое удаление. **Требует роль admin/manager или быть ответственным за клиента.**",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Клиент или контакт не найден"}},
)
async def delete_contact(
    client_id: int,
    contact_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_client_service(session).delete_contact(client_id, contact_id, current_user)
