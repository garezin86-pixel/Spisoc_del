# src/routers/interaction_router.py
from fastapi import APIRouter, Depends

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.client_repository import ClientRepository
from src.repositories.interaction_repository import InteractionRepository
from src.schemas.interaction import InteractionCreate, InteractionSchema, InteractionUpdate
from src.schemas.pagination import PaginatedResponse, PaginationParams
from src.services.interaction_service import InteractionService

router = APIRouter(prefix="/clients/{client_id}/interactions", tags=["Interactions"])


def get_interaction_service(session: SessionDep) -> InteractionService:
    return InteractionService(ClientRepository(session), InteractionRepository(session))


@router.get(
    "",
    response_model=PaginatedResponse[InteractionSchema],
    summary="История взаимодействий с клиентом",
    description="Новые сверху. Читать могут все пользователи компании.",
    responses={404: {"description": "Клиент не найден"}},
)
async def list_interactions(
    client_id: int,
    session: SessionDep,
    pagination: PaginationParams = Depends(),
    current_user: UserModel = Depends(get_current_user),
):
    items, total = await get_interaction_service(session).list_interactions(
        client_id, offset=pagination.offset, limit=pagination.size
    )
    return PaginatedResponse.create(
        items=[InteractionSchema.model_validate(i) for i in items],
        total=total,
        page=pagination.page,
        size=pagination.size,
    )


@router.post(
    "",
    response_model=InteractionSchema,
    status_code=201,
    summary="Добавить взаимодействие",
    description="Тип: call, meeting, email, message, note. Дата не в будущем (по умолчанию — сейчас). "
    "**Требует роль admin/manager или быть ответственным за клиента.**",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Клиент или контакт не найден"}},
)
async def create_interaction(
    client_id: int,
    data: InteractionCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_interaction_service(session).create(client_id, data, current_user)


@router.patch(
    "/{interaction_id}",
    response_model=InteractionSchema,
    summary="Обновить взаимодействие",
    description="Справочные поля (`summary`, `contact_id`): автор, ответственный за клиента, admin, manager. "
    "Процессные (`type`, `occurred_at`): только admin и manager.",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Не найдено"}},
)
async def update_interaction(
    client_id: int,
    interaction_id: int,
    data: InteractionUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_interaction_service(session).update(client_id, interaction_id, data, current_user)


@router.delete(
    "/{interaction_id}",
    response_model=dict,
    summary="Удалить взаимодействие",
    description="Мягкое удаление. **Требует роль admin или manager.**",
    responses={403: {"description": "Нет прав"}, 404: {"description": "Не найдено"}},
)
async def delete_interaction(
    client_id: int,
    interaction_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_interaction_service(session).delete(client_id, interaction_id, current_user)
