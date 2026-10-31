"""
Скрипт для выдачи пользователю доступа в SQLAdmin (is_platform_admin=True).

Использование:
    python -m src.admin.make_admin <login>
    python -m src.admin.make_admin <login> --revoke     # забрать доступ

Ищет по login (он уникален во всём сервисе), а не по username: username теперь уникален
только внутри компании, и прежний UPDATE ... WHERE username = ? мог затронуть
одноимённых пользователей из других компаний.

Важно: role="admin" означает «админ своей компании» и в SQLAdmin НЕ пускает —
для входа нужен именно флаг is_platform_admin (см. UserRepository.get_admin_by_username).
"""

import asyncio
import sys

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.models.user import UserModel
from src.repositories.users_repository import UserRepository


async def set_platform_admin(login: str, session: AsyncSession, value: bool = True) -> None:
    user = await UserRepository(session).get_by_login(login)

    if not user:
        print(f"❌ Пользователь с login '{login}' не найден в БД")
        return

    if bool(user.is_platform_admin) == value:
        state = "уже имеет" if value else "и так не имеет"
        print(f"ℹ️  Пользователь '{login}' {state} доступ в SQLAdmin")
        return

    await session.execute(update(UserModel).where(UserModel.id == user.id).values(is_platform_admin=value))
    await session.commit()
    action = "выдан" if value else "отозван"
    print(f"✅ Пользователю '{login}' (id={user.id}, компания id={user.workspace_id}) {action} доступ в SQLAdmin")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--revoke"]
    if len(args) != 1:
        print("Использование: python -m src.admin.make_admin <login> [--revoke]")
        sys.exit(1)

    login = args[0]
    grant = "--revoke" not in sys.argv

    async def run() -> None:
        async with UnitOfWork(get_session_maker()) as uow:
            await set_platform_admin(login, uow.session, grant)

    asyncio.run(run())
