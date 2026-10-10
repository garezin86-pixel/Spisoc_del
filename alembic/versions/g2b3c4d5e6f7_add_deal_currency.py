"""add deals.currency

Валюта у каждой сделки своя. Существующие сделки получают UAH.

Revision ID: g2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-10-10
"""

import sqlalchemy as sa

from alembic import op

revision = "g2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("currency", sa.String(length=3), nullable=False, server_default="UAH"))


def downgrade() -> None:
    op.drop_column("deals", "currency")
