# src/services/pat_service.py
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import not_found
from src.models.personal_access_token import PersonalAccessTokenModel
from src.models.user import UserModel
from src.repositories.pat_repository import PatRepository
from src.schemas.personal_access_token import PersonalAccessTokenCreate, PersonalAccessTokenCreatedResponse

TOKEN_PREFIX = "pat_"


def _hash_token(raw_token: str) -> str:
    """
    SHA-256, не bcrypt — см. docstring PersonalAccessTokenModel: токен уже
    высокоэнтропийный (32 случайных байта), в отличие от человеческого
    пароля не нуждается в медленном хэше, а PAT проверяется на каждый
    API-запрос (bcrypt на каждый запрос заметно нагрузил бы CPU).
    """
    return hashlib.sha256(raw_token.encode()).hexdigest()


class PatService:
    def __init__(self, pat_repo: PatRepository):
        self.pat_repo = pat_repo

    async def create_token(
        self, user: UserModel, data: PersonalAccessTokenCreate
    ) -> PersonalAccessTokenCreatedResponse:
        raw_token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        token_hash = _hash_token(raw_token)
        token_prefix = raw_token[: len(TOKEN_PREFIX) + 8]  # "pat_" + первые 8 символов случайной части

        expires_at = None
        if data.expires_in_days is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=data.expires_in_days)

        pat = await self.pat_repo.create(
            user_id=user.id,
            name=data.name,
            token_hash=token_hash,
            token_prefix=token_prefix,
            expires_at=expires_at,
        )

        return PersonalAccessTokenCreatedResponse(
            id=pat.id,
            name=pat.name,
            token_prefix=pat.token_prefix,
            created_at=pat.created_at,
            expires_at=pat.expires_at,
            last_used_at=pat.last_used_at,
            token=raw_token,
        )

    async def list_tokens(self, user: UserModel) -> list[PersonalAccessTokenModel]:
        return await self.pat_repo.list_for_user(user.id)

    async def revoke_token(self, user: UserModel, pat_id: int) -> dict:
        pat = await self.pat_repo.get_by_id(pat_id)
        # 404, а не 403, если токен принадлежит другому пользователю —
        # чтобы не подтверждать существование чужого id токена перебором.
        if not pat or pat.user_id != user.id:
            not_found("Токен не найден")
        await self.pat_repo.delete(pat)
        return {"message": f"Token {pat_id} revoked"}


async def authenticate_by_pat(session: AsyncSession, raw_token: str) -> UserModel | None:
    """
    Проверяет PAT и возвращает связанного пользователя, либо None если токен
    невалиден/просрочен/не существует. Не вызывает исключений — вызывающий
    код (get_current_user) сам решает, что делать при None (упасть в JWT-ветку
    или отклонить запрос).
    """
    if not raw_token.startswith(TOKEN_PREFIX):
        return None

    pat_repo = PatRepository(session)
    token_hash = _hash_token(raw_token)
    pat = await pat_repo.get_by_hash(token_hash)
    if not pat:
        return None

    if pat.expires_at is not None:
        expires_at = pat.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return None

    user = await session.get(UserModel, pat.user_id)
    if not user or not user.is_active:
        return None

    await pat_repo.touch_last_used(pat)
    return user
