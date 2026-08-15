# alembic/versions/342cd9c75837_add_chat_dm_recipient.py
"""add_chat_dm_recipient

Добавляет chat_messages.recipient_id — личные сообщения между двумя
пользователями (взаимоисключимо с group_id). См. src/services/chat_service.py.

Revision ID: 342cd9c75837
Revises: fd18a8921627
Create Date: 2026-08-10 10:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "342cd9c75837"
down_revision = "fd18a8921627"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_columns = [col["name"] for col in inspector.get_columns("chat_messages")]

    if "recipient_id" not in existing_columns:
        op.add_column(
            "chat_messages",
            sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        )
        op.create_index("ix_chat_messages_recipient_id", "chat_messages", ["recipient_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_indexes = [ix["name"] for ix in inspector.get_indexes("chat_messages")]
    existing_columns = [col["name"] for col in inspector.get_columns("chat_messages")]

    if "ix_chat_messages_recipient_id" in existing_indexes:
        op.drop_index("ix_chat_messages_recipient_id", table_name="chat_messages")
    if "recipient_id" in existing_columns:
        op.drop_column("chat_messages", "recipient_id")
