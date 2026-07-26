"""add task_dependencies table

Revision ID: e6f4a8b0c2d5
Revises: d5e3f7a9b2c4
Create Date: 2026-07-26
"""

import sqlalchemy as sa

from alembic import op

revision = "e6f4a8b0c2d5"
down_revision = "d5e3f7a9b2c4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "task_dependencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("blocker_task_id", sa.Integer(), sa.ForeignKey("spisok_del.id", ondelete="CASCADE"), nullable=False),
        sa.Column("blocked_task_id", sa.Integer(), sa.ForeignKey("spisok_del.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("blocker_task_id", "blocked_task_id", name="uq_task_dependency_pair"),
        sa.CheckConstraint("blocker_task_id != blocked_task_id", name="ck_task_dependency_not_self"),
    )
    op.create_index("ix_task_dependencies_blocker", "task_dependencies", ["blocker_task_id"])
    op.create_index("ix_task_dependencies_blocked", "task_dependencies", ["blocked_task_id"])


def downgrade():
    op.drop_index("ix_task_dependencies_blocked", table_name="task_dependencies")
    op.drop_index("ix_task_dependencies_blocker", table_name="task_dependencies")
    op.drop_table("task_dependencies")
