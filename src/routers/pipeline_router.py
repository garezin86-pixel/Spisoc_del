# src/routers/pipeline_router.py
from fastapi import APIRouter, Depends

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.client_repository import ClientRepository
from src.repositories.deal_repository import DealRepository
from src.repositories.users_repository import UserRepository
from src.schemas.deal import PipelineSchema, StageCreate, StageSchema, StageUpdate
from src.services.deal_service import DealService

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])


def get_deal_service(session: SessionDep) -> DealService:
    return DealService(DealRepository(session), ClientRepository(session), UserRepository(session))


@router.get(
    "",
    response_model=PipelineSchema,
    summary="Воронка компании со стадиями",
    description="Читать могут все. Если воронки ещё нет, создаётся стандартная: "
    "Новая, Переговоры, Предложение (open), Выиграна (won), Проиграна (lost).",
)
async def get_pipeline(session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    pipeline, stages = await get_deal_service(session).get_pipeline(current_user)
    return PipelineSchema(id=pipeline.id, name=pipeline.name, stages=[StageSchema.model_validate(s) for s in stages])


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
