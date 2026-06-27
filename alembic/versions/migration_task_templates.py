"""add task_templates

Revision ID: add_task_templates
Revises: <замени на id последней миграции>
Create Date: 2026-06-19
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

from alembic import op

revision = "add_task_templates"
down_revision = "4c9b58a062c6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "task_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "task_template_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("task_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column(
            "priority",
            # create_type=False — enum taskpriority уже существует в БД
            PG_ENUM(
                "low",
                "medium",
                "high",
                "critical",
                name="taskpriority",
                create_type=False,
            ),
            nullable=False,
            server_default="medium",
        ),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_table("task_template_items")
    op.drop_table("task_templates")
