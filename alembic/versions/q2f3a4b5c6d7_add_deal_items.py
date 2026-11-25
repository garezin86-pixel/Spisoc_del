"""add deal_items (оборудование сделки)

Smart Tables, этап 2: строки оборудования сделки — название (свободный текст) и цена (вручную).
Аддитивная миграция: только новая таблица. См. src/models/deal_item.py.

Revision ID: q2f3a4b5c6d7
Revises: p1e2f3a4b5c6
Create Date: 2026-11-22
"""

import sqlalchemy as sa

from alembic import op

revision = "q2f3a4b5c6d7"
down_revision = "p1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deal_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("deal_id", sa.Integer(), sa.ForeignKey("deals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_deal_items_workspace_id", "deal_items", ["workspace_id"])
    op.create_index("ix_deal_items_deal_id", "deal_items", ["deal_id"])


def downgrade() -> None:
    op.drop_index("ix_deal_items_deal_id", table_name="deal_items")
    op.drop_index("ix_deal_items_workspace_id", table_name="deal_items")
    op.drop_table("deal_items")
