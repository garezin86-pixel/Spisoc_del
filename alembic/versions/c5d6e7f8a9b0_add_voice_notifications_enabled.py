"""add voice_notifications_enabled to notification_settings

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-07-11

Опциональные (opt-in, по умолчанию выключены) голосовые TTS-уведомления
через Groq PlayAI TTS — см. src/services/voice_ai.py:synthesize_speech.
"""

import sqlalchemy as sa

from alembic import op

revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_settings",
        sa.Column("voice_notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("notification_settings", "voice_notifications_enabled")
