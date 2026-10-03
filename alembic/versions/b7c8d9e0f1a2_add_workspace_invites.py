"""add workspace_invites

Приглашения в компанию (workspace): токен, срок действия, отзыв.
См. src/models/workspace_invite.py.

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f7
Create Date: 2026-10-03
"""

import sqlalchemy as sa

from alembic import op

revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workspace_invites_token", "workspace_invites", ["token"], unique=True)
    op.create_index("ix_workspace_invites_workspace_id", "workspace_invites", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_invites_workspace_id", table_name="workspace_invites")
    op.drop_index("ix_workspace_invites_token", table_name="workspace_invites")
    op.drop_table("workspace_invites")
