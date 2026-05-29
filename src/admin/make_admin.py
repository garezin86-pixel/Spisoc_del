"""
Скрипт для назначения роли admin существующему пользователю в БД.

Использование:
    python make_admin.py <username>

Пример:
    python make_admin.py john
"""

import asyncio
import sys
from src.db import SessionDep
from src.repositories.users_repository import UserRepository
from src.db.unit_of_work import UnitOfWork
from src.db import get_session_maker


async def make_admin(username: str, session: SessionDep):
    repo = UserRepository(session)

    user = await repo.get_by_username(username)

    if not user:
        print(f"❌ Пользователь '{username}' не найден в БД")
        return

    if user.role == "admin":
        print(f"ℹ️  Пользователь '{username}' уже является администратором")
        return

    await repo.set_role(username, "admin")
    print(f"✅ Пользователю '{username}' (id={user.id}) назначена роль admin")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Использование: python make_admin.py <username>")
        sys.exit(1)

    username = sys.argv[1]
    # For a standalone script, we need to create a session manually
    from src.db import get_session_maker

    async def run_make_admin():
        async with UnitOfWork(get_session_maker()) as uow:
            await make_admin(username, uow.session)

    asyncio.run(run_make_admin())
