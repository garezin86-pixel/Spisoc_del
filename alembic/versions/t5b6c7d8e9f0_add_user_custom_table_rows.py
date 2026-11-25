"""add user_custom_table_rows and user_custom_table_cells (строки самостоятельных таблиц)

Smart Tables, этап 4.2: строки и ячейки (типизированные value_* колонки, как у своих полей).
Аддитивная миграция: только новые таблицы. См. src/models/user_custom_table.py.

Revision ID: t5b6c7d8e9f0
Revises: s4a5b6c7d8e9
Create Date: 2026-11-23
"""

import sqlalchemy as sa

from alembic import op

revision = "t5b6c7d8e9f0"
down_revision = "s4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_custom_table_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("table_id", sa.Integer(), sa.ForeignKey("user_custom_tables.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_custom_table_rows_workspace_id", "user_custom_table_rows", ["workspace_id"])
    op.create_index("ix_user_custom_table_rows_table_id", "user_custom_table_rows", ["table_id"])

    op.create_table(
        "user_custom_table_cells",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column(
            "row_id", sa.Integer(), sa.ForeignKey("user_custom_table_rows.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "column_id",
            sa.Integer(),
            sa.ForeignKey("user_custom_table_columns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value_text", sa.String(length=2000), nullable=True),
        sa.Column("value_number", sa.Numeric(18, 4), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("value_bool", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("row_id", "column_id", name="uq_user_custom_table_cells_row_column"),
    )
    op.create_index("ix_user_custom_table_cells_workspace_id", "user_custom_table_cells", ["workspace_id"])
    op.create_index("ix_user_custom_table_cells_column_id", "user_custom_table_cells", ["column_id"])


def downgrade() -> None:
    op.drop_index("ix_user_custom_table_cells_column_id", table_name="user_custom_table_cells")
    op.drop_index("ix_user_custom_table_cells_workspace_id", table_name="user_custom_table_cells")
    op.drop_table("user_custom_table_cells")
    op.drop_index("ix_user_custom_table_rows_table_id", table_name="user_custom_table_rows")
    op.drop_index("ix_user_custom_table_rows_workspace_id", table_name="user_custom_table_rows")
    op.drop_table("user_custom_table_rows")
