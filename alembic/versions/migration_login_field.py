"""add login and must_change_password to users

Revision ID: a8b6c0d2e4f7
Revises: f7a5b9c1d3e6
Create Date: 2026-07-27
"""

import sqlalchemy as sa

from alembic import op

revision = "a8b6c0d2e4f7"
down_revision = "f7a5b9c1d3e6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("login", sa.String(length=64), nullable=True))
    op.create_index("ix_users_login", "users", ["login"], unique=True)
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("users", "must_change_password")
    op.drop_index("ix_users_login", table_name="users")
    op.drop_column("users", "login")
