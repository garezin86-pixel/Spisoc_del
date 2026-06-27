"""add template visibility

Revision ID: add_template_visibility
Revises: add_task_templates
Create Date: 2026-06-23
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

from alembic import op

revision = "add_template_visibility"
down_revision = "add_task_templates"
branch_labels = None
depends_on = None

# Создаём новый enum тип
visibility_enum = PG_ENUM(
    "private",
    "group",
    "global",
    name="templatevisibility",
    create_type=True,
)


def upgrade():
    visibility_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "task_templates",
        sa.Column(
            "visibility",
            PG_ENUM(
                "private",
                "group",
                "global",
                name="templatevisibility",
                create_type=False,
            ),
            nullable=False,
            server_default="private",
        ),
    )
    op.add_column(
        "task_templates",
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("task_templates", "group_id")
    op.drop_column("task_templates", "visibility")
    visibility_enum.drop(op.get_bind(), checkfirst=True)
