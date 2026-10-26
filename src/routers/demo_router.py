"""Демо-данные: пример клиентов, сделок и задач для знакомства с системой. Только admin."""

from fastapi import APIRouter, Depends

from src.core.dependencies import SessionDep, get_current_user
from src.models.user import UserModel
from src.schemas.client import DemoCounts, DemoStatus
from src.services import demo_data_service

router = APIRouter(prefix="/demo", tags=["Demo"])


@router.get(
    "",
    response_model=DemoStatus,
    summary="Загружены ли демо-данные",
    description="Есть ли в компании демо-клиенты (созданные кнопкой «Загрузить демо-данные»).",
)
async def get_demo_status(session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    return await demo_data_service.demo_status(session)


@router.post(
    "/load",
    response_model=DemoCounts,
    status_code=201,
    summary="Загрузить демо-данные",
    description="Создаёт 12 клиентов (7 компаний и 5 частных лиц) со сделками, взаимодействиями, задачами и встречами. "
    "Владелец — вызывающий. **Только admin.** 409, если демо уже загружено.",
    responses={403: {"description": "Только admin"}, 409: {"description": "Демо уже загружено"}},
)
async def load_demo(session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    return await demo_data_service.load_demo(session, current_user)


@router.delete(
    "",
    response_model=DemoCounts,
    summary="Удалить демо-данные",
    description="Удаляет (мягко) демо-клиентов и всё, что к ним привязано. Настоящие данные не затрагиваются. "
    "Возвращает, сколько записей убрано. **Только admin.**",
    responses={403: {"description": "Только admin"}},
)
async def remove_demo(session: SessionDep, current_user: UserModel = Depends(get_current_user)):
    return await demo_data_service.remove_demo(session, current_user)
