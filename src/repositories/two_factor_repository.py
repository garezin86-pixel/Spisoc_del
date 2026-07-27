# src/repositories/two_factor_repository.py
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.two_factor_recovery_code import TwoFactorRecoveryCodeModel
from src.models.user import UserModel


class TwoFactorRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def set_pending_secret(self, user: UserModel, secret: str) -> None:
        """Секрет сгенерирован, но 2FA ещё не включена — включится после confirm_setup с верным кодом."""
        user.totp_secret = secret
        user.totp_enabled = False
        self.session.add(user)
        await self.session.commit()

    async def enable(self, user: UserModel) -> None:
        user.totp_enabled = True
        self.session.add(user)
        await self.session.commit()

    async def disable(self, user: UserModel) -> None:
        user.totp_secret = None
        user.totp_enabled = False
        self.session.add(user)
        await self.session.commit()
        await self.delete_all_recovery_codes(user.id)

    async def replace_recovery_codes(self, user_id: int, code_hashes: list[str]) -> None:
        await self.delete_all_recovery_codes(user_id)
        for code_hash in code_hashes:
            self.session.add(TwoFactorRecoveryCodeModel(user_id=user_id, code_hash=code_hash))
        await self.session.commit()

    async def delete_all_recovery_codes(self, user_id: int) -> None:
        result = await self.session.execute(
            select(TwoFactorRecoveryCodeModel).where(TwoFactorRecoveryCodeModel.user_id == user_id)
        )
        for code in result.scalars().all():
            await self.session.delete(code)
        await self.session.commit()

    async def get_unused_recovery_codes(self, user_id: int) -> list[TwoFactorRecoveryCodeModel]:
        result = await self.session.execute(
            select(TwoFactorRecoveryCodeModel).where(
                TwoFactorRecoveryCodeModel.user_id == user_id,
                TwoFactorRecoveryCodeModel.used_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def mark_recovery_code_used(self, code: TwoFactorRecoveryCodeModel) -> None:
        code.used_at = datetime.now(timezone.utc)
        self.session.add(code)
        await self.session.commit()
