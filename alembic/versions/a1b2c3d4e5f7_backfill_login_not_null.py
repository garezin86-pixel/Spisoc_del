"""backfill login for existing users, make it NOT NULL

До сих пор login проставлял только Telegram-бот (build_login_base +
дедупликация суффиксом, см. src/services/login_service.py). Пользователи,
заведённые через веб-регистрацию или из админки, оставались с login=NULL —
из-за этого AuthService.login был вынужден держать fallback на username
при входе. Код уже поправлен (см. коммит с login_service.py): все три
места создания пользователя теперь всегда задают login. Эта миграция
закрывает хвост существующих данных.

В отличие от миграций workspace_id (там backfill и NOT NULL были
намеренно разнесены на разные деплои — 13 таблиц, откат чувствителен к
коллизиям между компаниями), здесь всё в одной таблице и в одном поле,
разносить не стал.

Дедупликация построена так же, как в src/services/login_service.py и в
прежней версии бота: суффикс 2, 3, ... при коллизии. Обрабатываем строки
по возрастанию id — детерминированный порядок, чтобы повторный прогон (если
миграция вдруг попадёт в лог дважды до попытки повторного применения)
давал одинаковый результат. login НЕ импортируем как ORM-модель — только
чистая функция build_login_base(fio), без обращений к БД/моделям.

Revision ID: a1b2c3d4e5f7
Revises: f5a6b7c8d9e0
Create Date: 2026-09-30
"""

import sqlalchemy as sa

from alembic import op
from src.utils.login_generator import build_login_base

revision = "a1b2c3d4e5f7"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    existing_logins = set(conn.execute(sa.text("SELECT login FROM users WHERE login IS NOT NULL")).scalars())

    rows = conn.execute(sa.text("SELECT id, username FROM users WHERE login IS NULL ORDER BY id")).all()

    for user_id, username in rows:
        base_login = build_login_base(username or "")
        login = base_login
        suffix = 2
        while login in existing_logins:
            login = f"{base_login}{suffix}"
            suffix += 1
        existing_logins.add(login)

        conn.execute(
            sa.text("UPDATE users SET login = :login WHERE id = :id"),
            {"login": login, "id": user_id},
        )

    op.alter_column("users", "login", nullable=False)


def downgrade() -> None:
    # Откат делает login снова nullable, но НЕ обнуляет проставленные
    # значения — как и с workspace_id, "развидеть" данные откат не должен,
    # только снять ограничение. Если это единственная причина отката,
    # обнулять руками (UPDATE users SET login = NULL) осознанно и отдельно.
    op.alter_column("users", "login", nullable=True)
