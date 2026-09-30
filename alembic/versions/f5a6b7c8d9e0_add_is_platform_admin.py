"""add is_platform_admin, backfill for current role=admin users

Разводит два смысла, до сих пор смешанных в одном поле role:
  - role == "admin"       — админ СВОЕГО workspace (может редактировать
                             чужие задачи в своей компании, см.
                             src/services/permissions.py) — после
                             мультитенантности так будет у первого
                             регистранта каждой новой компании.
  - is_platform_admin      — доступ в SQLAdmin, то есть к сырому CRUD по
                             ВСЕМ workspace сразу (см.
                             src/admin/views/admin_auth.py). Никогда не
                             выставляется через API/регистрацию/инвайты —
                             только вручную в БД.

Backfill даёт is_platform_admin = true всем, у кого role == "admin" на
момент миграции: это пользователи из ещё однотенантной версии, они и
раньше имели доступ в SQLAdmin (тогда проверка шла по role), поэтому
здесь их фактический уровень доступа не меняется — только называется
явно. Новые workspace-админы, зарегистрированные ПОСЛЕ этой миграции,
получат role="admin" через обычную регистрацию, но is_platform_admin у
них останется false (значение по умолчанию для новой колонки).

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-09-29
"""

import sqlalchemy as sa

from alembic import op

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE users SET is_platform_admin = true WHERE role = 'admin'")


def downgrade() -> None:
    op.drop_column("users", "is_platform_admin")
