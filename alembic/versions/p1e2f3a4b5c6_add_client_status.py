"""add clients.status (статус клиента)

Статус клиента: active / inactive / blacklisted. У всех существующих клиентов — active.

Revision ID: p1e2f3a4b5c6
Revises: o0d1e2f3a4b5
Create Date: 2026-10-29
"""

import sqlalchemy as sa

from alembic import op

revision = "p1e2f3a4b5c6"
down_revision = "o0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("status", sa.String(length=12), nullable=False, server_default="active"))
    op.create_index("ix_clients_status", "clients", ["status"])


def downgrade() -> None:
    op.drop_index("ix_clients_status", table_name="clients")
    op.drop_column("clients", "status")
