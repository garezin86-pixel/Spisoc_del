"""add custom_fields and custom_field_values (свои поля)

Smart Tables, этап 3: пользовательские поля клиентов и сделок и их значения.
Аддитивная миграция: только две новые таблицы, таблицы CRM не меняются. См. src/models/custom_field.py.

Revision ID: r3a4b5c6d7e8
Revises: q2f3a4b5c6d7
Create Date: 2026-11-22
"""

import sqlalchemy as sa

from alembic import op

revision = "r3a4b5c6d7e8"
down_revision = "q2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_fields",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("field_type", sa.String(length=10), nullable=False),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_custom_fields_workspace_id", "custom_fields", ["workspace_id"])
    op.create_index("ix_custom_fields_workspace_entity", "custom_fields", ["workspace_id", "entity_type"])

    op.create_table(
        "custom_field_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("custom_fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("value_text", sa.String(length=2000), nullable=True),
        sa.Column("value_number", sa.Numeric(18, 4), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("value_bool", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("field_id", "entity_id", name="uq_custom_field_values_field_entity"),
    )
    op.create_index("ix_custom_field_values_workspace_id", "custom_field_values", ["workspace_id"])
    op.create_index("ix_custom_field_values_entity_id", "custom_field_values", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_custom_field_values_entity_id", table_name="custom_field_values")
    op.drop_index("ix_custom_field_values_workspace_id", table_name="custom_field_values")
    op.drop_table("custom_field_values")
    op.drop_index("ix_custom_fields_workspace_entity", table_name="custom_fields")
    op.drop_index("ix_custom_fields_workspace_id", table_name="custom_fields")
    op.drop_table("custom_fields")
