"""add group_id to projects

Revision ID: d5e6f7a8b9c0
Revises: c4e5f6a7b8d9
Create Date: 2026-06-12 10:00:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4e5f6a7b8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("group_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_projects_group_id",
        "projects",
        "groups",
        ["group_id"],
        ["id"],
        ondelete="SET NULL",  # при удалении группы проект остаётся, group_id = NULL
    )
    op.create_index("ix_projects_group_id", "projects", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_projects_group_id", table_name="projects")
    op.drop_constraint("fk_projects_group_id", "projects", type_="foreignkey")
    op.drop_column("projects", "group_id")
