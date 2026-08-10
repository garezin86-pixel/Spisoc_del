# alembic/versions/fd18a8921627_add_chat_group_scope.py
"""add_chat_group_scope

Добавляет chat_messages.group_id — NULL значит общий канал (видно всем),
заполненное значение — приватный канал конкретной группы (видно только
участникам). См. src/services/chat_service.py.

Revision ID: fd18a8921627
Revises: b278696a9fdf
Create Date: 2026-08-09 14:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "fd18a8921627"
down_revision = "b278696a9fdf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_columns = [col["name"] for col in inspector.get_columns("chat_messages")]

    if "group_id" not in existing_columns:
        op.add_column(
            "chat_messages",
            sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=True),
        )
        op.create_index("ix_chat_messages_group_id", "chat_messages", ["group_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_indexes = [ix["name"] for ix in inspector.get_indexes("chat_messages")]
    existing_columns = [col["name"] for col in inspector.get_columns("chat_messages")]

    if "ix_chat_messages_group_id" in existing_indexes:
        op.drop_index("ix_chat_messages_group_id", table_name="chat_messages")
    if "group_id" in existing_columns:
        op.drop_column("chat_messages", "group_id")
