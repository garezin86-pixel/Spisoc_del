"""add user_custom_tables and user_custom_table_columns (самостоятельные таблицы)

Smart Tables, этап 4.1: таблицы пользователей и их колонки. Строки и ячейки — в следующей миграции (4.2).
Аддитивная миграция: только новые таблицы. См. src/models/user_custom_table.py.

Revision ID: s4a5b6c7d8e9
Revises: r3a4b5c6d7e8
Create Date: 2026-11-23
"""

import sqlalchemy as sa

from alembic import op

revision = "s4a5b6c7d8e9"
down_revision = "r3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_custom_tables",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("icon", sa.String(length=16), nullable=True),
        sa.Column("visibility", sa.String(length=10), nullable=False, server_default="shared"),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_custom_tables_workspace_id", "user_custom_tables", ["workspace_id"])

    op.create_table(
        "user_custom_table_columns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("table_id", sa.Integer(), sa.ForeignKey("user_custom_tables.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("data_type", sa.String(length=10), nullable=False),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_custom_table_columns_workspace_id", "user_custom_table_columns", ["workspace_id"])
    op.create_index("ix_user_custom_table_columns_table_id", "user_custom_table_columns", ["table_id"])


def downgrade() -> None:
    op.drop_index("ix_user_custom_table_columns_table_id", table_name="user_custom_table_columns")
    op.drop_index("ix_user_custom_table_columns_workspace_id", table_name="user_custom_table_columns")
    op.drop_table("user_custom_table_columns")
    op.drop_index("ix_user_custom_tables_workspace_id", table_name="user_custom_tables")
    op.drop_table("user_custom_tables")
