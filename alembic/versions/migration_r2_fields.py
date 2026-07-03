"""add r2 storage fields to attachments

Revision ID: c3a5e9f1b7d2
Revises: f7e8d9c0b1a2
Create Date: 2025-06-30

"""

import sqlalchemy as sa

from alembic import op

revision = "c3a5e9f1b7d2"
down_revision = "f7e8d9c0b1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attachments", sa.Column("storage_key", sa.String(500), nullable=True))
    op.add_column("attachments", sa.Column("storage_url", sa.String(1000), nullable=True))


def downgrade() -> None:
    op.drop_column("attachments", "storage_url")
    op.drop_column("attachments", "storage_key")
