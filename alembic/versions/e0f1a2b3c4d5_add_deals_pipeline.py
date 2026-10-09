"""add pipelines, stages, deals

Этап 3 lite-CRM: сделки и воронка. См. src/models/deal.py.
Воронка по умолчанию создаётся приложением при первом обращении компании, миграция данных не сеет.

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-10-08
"""

import sqlalchemy as sa

from alembic import op

revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def _ws():
    return sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "pipelines",
        sa.Column("id", sa.Integer(), primary_key=True),
        _ws(),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pipelines_workspace_id", "pipelines", ["workspace_id"])

    op.create_table(
        "stages",
        sa.Column("id", sa.Integer(), primary_key=True),
        _ws(),
        sa.Column("pipeline_id", sa.Integer(), sa.ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_stages_workspace_id", "stages", ["workspace_id"])
    op.create_index("ix_stages_pipeline_id", "stages", ["pipeline_id"])

    op.create_table(
        "deals",
        sa.Column("id", sa.Integer(), primary_key=True),
        _ws(),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_id", sa.Integer(), sa.ForeignKey("stages.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lost_reason", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_deals_workspace_id", "deals", ["workspace_id"])
    op.create_index("ix_deals_client_id", "deals", ["client_id"])
    op.create_index("ix_deals_stage_id", "deals", ["stage_id"])
    op.create_index("ix_deals_owner_id", "deals", ["owner_id"])


def downgrade() -> None:
    for idx in ("ix_deals_owner_id", "ix_deals_stage_id", "ix_deals_client_id", "ix_deals_workspace_id"):
        op.drop_index(idx, table_name="deals")
    op.drop_table("deals")
    for idx in ("ix_stages_pipeline_id", "ix_stages_workspace_id"):
        op.drop_index(idx, table_name="stages")
    op.drop_table("stages")
    op.drop_index("ix_pipelines_workspace_id", table_name="pipelines")
    op.drop_table("pipelines")
