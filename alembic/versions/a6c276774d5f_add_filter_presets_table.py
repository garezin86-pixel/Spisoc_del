"""add filter_presets table

Revision ID: a6c276774d5f
Revises: d6e7f8a9b0c1
Create Date: 2026-07-25 15:38:35.308555

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6c276774d5f"
down_revision: Union[str, Sequence[str], None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "filter_presets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "backlog",
                "todo",
                "in_progress",
                "review",
                "done",
                name="taskstatus",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "priority",
            postgresql.ENUM(
                "low",
                "medium",
                "high",
                "critical",
                name="taskpriority",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("tag_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("filter_user_group", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_filter_preset_user_name"),
    )
    # Посторонние DROP INDEX/CONSTRAINT по personal_access_tokens,
    # push_subscriptions, spisok_del, task_checklist_items, task_tags —
    # удалены из этой миграции: это несвязанный дрейф между моделями и БД
    # (в т.ч. индекс полнотекстового поиска ix_spisok_del_title_description_gin),
    # накопившийся раньше и не имеющий отношения к filter_presets. Разбирать
    # этот дрейф — отдельная задача, отдельной миграцией, после явной проверки,
    # что каждый DROP там действительно осознанный.


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("filter_presets")
