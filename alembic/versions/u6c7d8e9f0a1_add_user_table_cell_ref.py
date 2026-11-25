"""add user_custom_table_cells.value_ref (связи с CRM)

Smart Tables, этап 4.4: колонки-связи (клиент, сделка, пользователь) хранят id записи в value_ref.
Аддитивная миграция: одна nullable-колонка и индекс; существующие данные не затрагиваются.

Revision ID: u6c7d8e9f0a1
Revises: t5b6c7d8e9f0
Create Date: 2026-11-24
"""

import sqlalchemy as sa

from alembic import op

revision = "u6c7d8e9f0a1"
down_revision = "t5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_custom_table_cells", sa.Column("value_ref", sa.Integer(), nullable=True))
    op.create_index("ix_user_custom_table_cells_value_ref", "user_custom_table_cells", ["value_ref"])


def downgrade() -> None:
    op.drop_index("ix_user_custom_table_cells_value_ref", table_name="user_custom_table_cells")
    op.drop_column("user_custom_table_cells", "value_ref")
