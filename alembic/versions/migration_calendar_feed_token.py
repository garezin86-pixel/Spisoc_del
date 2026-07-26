"""add calendar_feed_token to users

Revision ID: d5e3f7a9b2c4
Revises: c4d2e6f8a1b3
Create Date: 2026-07-26
"""

import sqlalchemy as sa

from alembic import op

revision = "d5e3f7a9b2c4"
down_revision = "c4d2e6f8a1b3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("calendar_feed_token", sa.String(length=64), nullable=True))
    op.create_index("ix_users_calendar_feed_token", "users", ["calendar_feed_token"], unique=True)


def downgrade():
    op.drop_index("ix_users_calendar_feed_token", table_name="users")
    op.drop_column("users", "calendar_feed_token")
