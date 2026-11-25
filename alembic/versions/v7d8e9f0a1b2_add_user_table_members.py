"""add user_custom_table_members (ограниченный доступ к самостоятельным таблицам)

Smart Tables, этап 4.5: участники таблицы с видимостью `restricted` и право менять строки (can_edit).
Аддитивная миграция: только новая таблица; существующие таблицы и их видимость не меняются
(значение visibility `restricted` помещается в существующую колонку String(10)).

Revision ID: v7d8e9f0a1b2
Revises: u6c7d8e9f0a1
Create Date: 2026-11-24
"""

import sqlalchemy as sa

from alembic import op

revision = "v7d8e9f0a1b2"
down_revision = "u6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_custom_table_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("table_id", sa.Integer(), sa.ForeignKey("user_custom_tables.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("can_edit", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("table_id", "user_id", name="uq_user_custom_table_members_table_user"),
    )
    op.create_index("ix_user_custom_table_members_workspace_id", "user_custom_table_members", ["workspace_id"])
    op.create_index("ix_user_custom_table_members_user_id", "user_custom_table_members", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_custom_table_members_user_id", table_name="user_custom_table_members")
    op.drop_index("ix_user_custom_table_members_workspace_id", table_name="user_custom_table_members")
    op.drop_table("user_custom_table_members")
