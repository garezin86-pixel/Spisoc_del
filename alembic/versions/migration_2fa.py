"""add 2fa fields and recovery codes

Revision ID: f7a5b9c1d3e6
Revises: e6f4a8b0c2d5
Create Date: 2026-07-26
"""

import sqlalchemy as sa

from alembic import op

revision = "f7a5b9c1d3e6"
down_revision = "e6f4a8b0c2d5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("totp_secret", sa.String(length=64), nullable=True))
    op.add_column(
        "users",
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "two_factor_recovery_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_2fa_recovery_codes_user_id", "two_factor_recovery_codes", ["user_id"])


def downgrade():
    op.drop_index("ix_2fa_recovery_codes_user_id", table_name="two_factor_recovery_codes")
    op.drop_table("two_factor_recovery_codes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
