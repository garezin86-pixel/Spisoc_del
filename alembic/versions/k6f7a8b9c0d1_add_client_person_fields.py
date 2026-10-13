"""add clients.birth_date and clients.gender

Поля частного лица (B2C): дата рождения и пол. У компаний остаются пустыми.

Revision ID: k6f7a8b9c0d1
Revises: j5e6f7a8b9c0
Create Date: 2026-10-13
"""

import sqlalchemy as sa

from alembic import op

revision = "k6f7a8b9c0d1"
down_revision = "j5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column("clients", sa.Column("gender", sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "gender")
    op.drop_column("clients", "birth_date")
