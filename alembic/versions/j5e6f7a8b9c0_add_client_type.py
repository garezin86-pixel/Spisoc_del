"""add clients.client_type

Тип клиента: компания (B2B, company) или частное лицо (B2C, person). Существующие клиенты — компании.

Revision ID: j5e6f7a8b9c0
Revises: i4d5e6f7a8b9
Create Date: 2026-10-13
"""

import sqlalchemy as sa

from alembic import op

revision = "j5e6f7a8b9c0"
down_revision = "i4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("client_type", sa.String(length=10), nullable=False, server_default="company"))


def downgrade() -> None:
    op.drop_column("clients", "client_type")
