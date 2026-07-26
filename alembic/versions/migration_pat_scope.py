"""add scope to personal access tokens

Revision ID: a2f9c1d4b6e8
Revises: d02b61f43b1a
Create Date: 2026-07-26
"""

import sqlalchemy as sa

from alembic import op

revision = "a2f9c1d4b6e8"
down_revision = "d02b61f43b1a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "personal_access_tokens",
        sa.Column(
            "scope",
            sa.String(length=20),
            nullable=False,
            server_default="read_write",
        ),
    )


def downgrade():
    op.drop_column("personal_access_tokens", "scope")
