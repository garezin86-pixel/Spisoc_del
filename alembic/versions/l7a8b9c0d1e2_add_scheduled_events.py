"""add scheduled_events

Этап 4 lite-CRM: запланированные встречи и звонки. См. src/models/scheduled_event.py.

Revision ID: l7a8b9c0d1e2
Revises: k6f7a8b9c0d1
Create Date: 2026-10-13
"""

import sqlalchemy as sa

from alembic import op

revision = "l7a8b9c0d1e2"
down_revision = "k6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("assignee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="planned"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "completed_interaction_id",
            sa.Integer(),
            sa.ForeignKey("interactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_scheduled_events_workspace_id", "scheduled_events", ["workspace_id"])
    op.create_index("ix_scheduled_events_assignee_starts", "scheduled_events", ["assignee_id", "starts_at"])
    op.create_index("ix_scheduled_events_client_starts", "scheduled_events", ["client_id", "starts_at"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_events_client_starts", table_name="scheduled_events")
    op.drop_index("ix_scheduled_events_assignee_starts", table_name="scheduled_events")
    op.drop_index("ix_scheduled_events_workspace_id", table_name="scheduled_events")
    op.drop_table("scheduled_events")
