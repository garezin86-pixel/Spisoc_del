"""add clients.is_demo (демо-данные)

Пометка клиентов, созданных кнопкой «Загрузить демо-данные», чтобы их можно было убрать одним действием,
не задев настоящих клиентов. У существующих клиентов — false.

Revision ID: o0d1e2f3a4b5
Revises: n9c0d1e2f3a4
Create Date: 2026-10-26
"""

import sqlalchemy as sa

from alembic import op

revision = "o0d1e2f3a4b5"
down_revision = "n9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("clients", "is_demo")
