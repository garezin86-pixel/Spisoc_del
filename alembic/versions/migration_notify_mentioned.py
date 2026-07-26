"""add notify_mentioned to notification_settings

Revision ID: c4d2e6f8a1b3
Revises: b3c1d5e7f9a0
Create Date: 2026-07-26
"""

import sqlalchemy as sa

from alembic import op

revision = "c4d2e6f8a1b3"
down_revision = "b3c1d5e7f9a0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notification_settings",
        sa.Column("notify_mentioned", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade():
    op.drop_column("notification_settings", "notify_mentioned")
