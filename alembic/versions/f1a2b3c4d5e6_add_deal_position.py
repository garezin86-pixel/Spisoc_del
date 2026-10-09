"""add deals.position

Порядок сделок внутри колонки канбана. Существующие сделки получают 0 (порядок среди них — по id).

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-10-09
"""

import sqlalchemy as sa

from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("position", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_deals_stage_position", "deals", ["stage_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_deals_stage_position", table_name="deals")
    op.drop_column("deals", "position")
