# src/routers/two_factor_router.py
from fastapi import APIRouter, Depends

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.two_factor_repository import TwoFactorRepository
from src.schemas.two_factor import (
    TwoFactorConfirmRequest,
    TwoFactorConfirmResponse,
    TwoFactorDisableRequest,
    TwoFactorSetupResponse,
    TwoFactorStatusResponse,
)
from src.services.two_factor_service import TwoFactorService

router = APIRouter(prefix="/auth/2fa", tags=["Two-Factor Auth"])


def get_two_factor_service(session: SessionDep) -> TwoFactorService:
    return TwoFactorService(TwoFactorRepository(session))


@router.get("/status", response_model=TwoFactorStatusResponse)
async def get_status(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return get_two_factor_service(session).status(current_user)


@router.post(
    "/setup",
    response_model=TwoFactorSetupResponse,
    summary="Начать настройку 2FA",
    description=(
        "Генерирует secret и ссылку otpauth:// для QR-кода. 2FA ещё НЕ включена — "
        "включится только после POST /auth/2fa/confirm с верным кодом."
    ),
)
async def start_setup(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_two_factor_service(session).start_setup(current_user)


@router.post(
    "/confirm",
    response_model=TwoFactorConfirmResponse,
    summary="Подтвердить настройку и включить 2FA",
    description="Recovery-коды в ответе показываются один раз — сохраните их прямо сейчас.",
)
async def confirm_setup(
    data: TwoFactorConfirmRequest,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_two_factor_service(session).confirm_setup(current_user, data.code)


@router.post(
    "/disable",
    status_code=204,
    summary="Отключить 2FA",
    description=(
        "Требует пароль и текущий код (или recovery-код) — иначе угнанный access-токен позволил бы тихо снять защиту."
    ),
)
async def disable(
    data: TwoFactorDisableRequest,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    await get_two_factor_service(session).disable(current_user, data.password, data.code)
