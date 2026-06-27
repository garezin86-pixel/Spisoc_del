"""add soft delete (deleted_at) to tasks and comments

Revision ID: a1b2c3d4e5f6
Revises: 44ccc0086910
Create Date: 2026-05-19 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "44ccc0086910"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── spisok_del ────────────────────────────────────────────────────────────
    op.add_column(
        "spisok_del",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_spisok_del_not_deleted",
        "spisok_del",
        ["id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_spisok_del_user_not_deleted",
        "spisok_del",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_spisok_del_group_not_deleted",
        "spisok_del",
        ["group_id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── comments ──────────────────────────────────────────────────────────────
    op.add_column(
        "comments",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_comments_not_deleted",
        "comments",
        ["task_id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_comments_not_deleted",
        table_name="comments",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_column("comments", "deleted_at")

    op.drop_index(
        "ix_spisok_del_group_not_deleted",
        table_name="spisok_del",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_spisok_del_user_not_deleted",
        table_name="spisok_del",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_spisok_del_not_deleted",
        table_name="spisok_del",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_column("spisok_del", "deleted_at")
