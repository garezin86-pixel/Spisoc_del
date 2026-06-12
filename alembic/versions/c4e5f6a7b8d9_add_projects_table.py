"""add projects table

Revision ID: c4e5f6a7b8d9
Revises: b3d4e5f6a7c8
Create Date: 2026-06-11 12:00:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c4e5f6a7b8d9"
down_revision: Union[str, Sequence[str], None] = "b3d4e5f6a7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Таблица проектов
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])

    # M2M таблица участников проекта
    op.create_table(
        "project_member",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "project_id"),
    )

    # Связь задач с проектами (nullable — задачи без проекта остаются)
    op.add_column(
        "spisok_del",
        sa.Column("project_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tasks_project_id",
        "spisok_del",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",  # при удалении проекта задачи НЕ удаляются через FK
    )
    op.create_index("ix_spisok_del_project_id", "spisok_del", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_spisok_del_project_id", table_name="spisok_del")
    op.drop_constraint("fk_tasks_project_id", "spisok_del", type_="foreignkey")
    op.drop_column("spisok_del", "project_id")
    op.drop_table("project_member")
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_table("projects")
