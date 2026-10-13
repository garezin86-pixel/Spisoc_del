"""add stages.color

Свой цвет у каждой стадии воронки ("#rrggbb"; NULL — цвет по виду стадии).

Revision ID: i4d5e6f7a8b9
Revises: h3c4d5e6f7a8
Create Date: 2026-10-12
"""

import sqlalchemy as sa

from alembic import op

revision = "i4d5e6f7a8b9"
down_revision = "h3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stages", sa.Column("color", sa.String(length=7), nullable=True))


def downgrade() -> None:
    op.drop_column("stages", "color")
