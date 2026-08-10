# alembic/versions/b278696a9fdf_add_chat_messages.py
"""add_chat_messages

Командный чат — общий канал для непринуждённого общения (не привязан к
задаче, в отличие от комментариев). См. src/models/chat_message.py.

Revision ID: b278696a9fdf
Revises: 9c61ad13e22d
Create Date: 2026-08-09 09:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "b278696a9fdf"
down_revision = "9c61ad13e22d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chat_messages" in inspector.get_table_names():
        return

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_chat_messages_user_id", "chat_messages", ["user_id"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "chat_messages" in inspector.get_table_names():
        op.drop_table("chat_messages")
