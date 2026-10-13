# src/routers/pipeline_router.py
from fastapi import APIRouter, Depends, Query

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.client_repository import ClientRepository
from src.repositories.deal_repository import DealRepository
from src.repositories.users_repository import UserRepository
from src.schemas.client import ClientType
from src.schemas.deal import (
    PipelineCreate,
    PipelineListItem,
    PipelineSchema,
    PipelineSummary,
    PipelineUpdate,
    StageCreate,
    StageSchema,
    StageUpdate,
)
from src.services.deal_service import DealService

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])
pipelines_router = APIRouter(prefix="/pipelines", tags=["Pipeline"])


def get_deal_service(session: SessionDep) -> DealService:
    return DealService(DealRepository(session), ClientRepository(session), UserRepository(session))


@router.get(
    "",
    response_model=PipelineSchema,
    summary="Воронка компании со стадиями",
    description="Читать могут все. Если воронки ещё нет, создаётся стандартная: "
    "Новая, Переговоры, Предложение (open), Выиграна (won), Проиграна (lost).",
)
async def get_pipeline(
    session: SessionDep,
    pipeline_id: int | None = Query(None, description="Воронка; не передана — воронка по умолчанию (первая)"),
    current_user: UserModel = Depends(get_current_user),
):
    pipeline, stages = await get_deal_service(session).get_pipeline(current_user, pipeline_id)
    return PipelineSchema(id=pipeline.id, name=pipeline.name, stages=[StageSchema.model_validate(s) for s in stages])


@router.get(
    "/summary",
    response_model=PipelineSummary,
    summary="Сводка по воронке",
    description="Количество сделок и суммы по стадиям с разбивкой по валютам (разные валюты не складываются), "
    "итоги по видам стадий и конверсия `won / (won + lost)` среди закрытых сделок. "
    "`owner_id` — только сделки этого ответственного. Читать могут все.",
)
async def get_pipeline_summary(
    session: SessionDep,
    owner_id: int | None = Query(None, description="Только сделки этого ответственного"),
    pipeline_id: int | None = Query(None, description="Воронка; не передана — воронка по умолчанию"),
    client_type: ClientType | None = Query(
        None, description="company — только сделки компаний (B2B), person — частных лиц (B2C)"
    ),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_deal_service(session).get_summary(current_user, owner_id, pipeline_id, client_type)


@router.post(
    "/stages",
    response_model=StageSchema,
    status_code=201,
    summary="Добавить стадию",
    description="**Требует роль admin.** Вид стадии (open / won / lost) после создания не меняется.",
    responses={403: {"description": "Только admin"}},
)
async def create_stage(data: StageCreate, session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    return await get_deal_service(session).create_stage(data, current_user)


@router.patch(
    "/stages/{stage_id}",
    response_model=StageSchema,
    summary="Переименовать или переставить стадию",
    description="**Требует роль admin.**",
    responses={403: {"description": "Только admin"}, 404: {"description": "Стадия не найдена"}},
)
async def update_stage(
    stage_id: int,
    data: StageUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_deal_service(session).update_stage(stage_id, data, current_user)


@router.delete(
    "/stages/{stage_id}",
    response_model=dict,
    summary="Удалить стадию",
    description="**Требует роль admin.** Нельзя, если в стадии есть сделки или это последняя стадия своего вида.",
    responses={
        403: {"description": "Только admin"},
        404: {"description": "Стадия не найдена"},
        409: {"description": "В стадии есть сделки или она последняя своего вида"},
    },
)
async def delete_stage(stage_id: int, session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    return await get_deal_service(session).delete_stage(stage_id, current_user)


# ── Несколько воронок: список, создание, переименование, удаление (управляет только admin) ──
@pipelines_router.get(
    "",
    response_model=list[PipelineListItem],
    summary="Все воронки компании",
    description="Каждая воронка со стадиями (с цветами) и числом сделок. "
    "Первая — воронка по умолчанию. Читать могут все.",
)
async def list_pipelines(session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    return await get_deal_service(session).list_pipelines(current_user)


@pipelines_router.post(
    "",
    response_model=PipelineListItem,
    status_code=201,
    summary="Создать воронку",
    description="**Требует роль admin.** Без `copy_from_id` создаётся минимальная воронка (Новая → Успех / Отказ), "
    "с `copy_from_id` — копия стадий (названия, порядок, виды, цвета) указанной воронки, без сделок.",
    responses={403: {"description": "Только admin"}, 404: {"description": "Воронка для копирования не найдена"}},
)
async def create_pipeline(
    data: PipelineCreate, session: SessionDep, current_user: UserModel = Depends(get_current_user)
):
    return await get_deal_service(session).create_pipeline(data, current_user)


@pipelines_router.patch(
    "/{pipeline_id}",
    response_model=PipelineListItem,
    summary="Переименовать воронку",
    description="**Требует роль admin.**",
    responses={403: {"description": "Только admin"}, 404: {"description": "Воронка не найдена"}},
)
async def rename_pipeline(
    pipeline_id: int,
    data: PipelineUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_deal_service(session).rename_pipeline(pipeline_id, data, current_user)


@pipelines_router.delete(
    "/{pipeline_id}",
    response_model=dict,
    summary="Удалить воронку",
    description="**Требует роль admin.** Мягко, вместе со стадиями. "
    "Нельзя удалить единственную воронку и воронку со сделками.",
    responses={
        403: {"description": "Только admin"},
        404: {"description": "Воронка не найдена"},
        409: {"description": "Единственная воронка или в ней есть сделки"},
    },
)
async def delete_pipeline(pipeline_id: int, session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    return await get_deal_service(session).delete_pipeline(pipeline_id, current_user)
