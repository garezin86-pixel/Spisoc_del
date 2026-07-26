"""add webhooks table

Revision ID: b3c1d5e7f9a0
Revises: a2f9c1d4b6e8
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "b3c1d5e7f9a0"
down_revision = "a2f9c1d4b6e8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "webhooks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("secret", sa.String(length=100), nullable=False),
        sa.Column("secret_prefix", sa.String(length=20), nullable=False),
        sa.Column("events", JSONB(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_webhooks_user_id", "webhooks", ["user_id"])
    op.create_index("ix_webhooks_user_active", "webhooks", ["user_id", "is_active"])


def downgrade():
    op.drop_index("ix_webhooks_user_active", table_name="webhooks")
    op.drop_index("ix_webhooks_user_id", table_name="webhooks")
    op.drop_table("webhooks")
