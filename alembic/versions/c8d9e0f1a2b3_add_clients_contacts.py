"""add clients, contacts and projects.client_id

Этап 1 lite-CRM: клиенты, контактные лица и необязательная связь проекта с клиентом.
Все новые таблицы — tenant (workspace_id NOT NULL), с мягким удалением.
См. src/models/client.py.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-10-07
"""

import sqlalchemy as sa

from alembic import op

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_clients_workspace_id", "clients", ["workspace_id"])
    op.create_index("ix_clients_owner_id", "clients", ["owner_id"])

    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("position", sa.String(length=200), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_contacts_workspace_id", "contacts", ["workspace_id"])
    op.create_index("ix_contacts_client_id", "contacts", ["client_id"])

    op.add_column("projects", sa.Column("client_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_projects_client_id", "projects", "clients", ["client_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_projects_client_id", "projects", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_projects_client_id", table_name="projects")
    op.drop_constraint("fk_projects_client_id", "projects", type_="foreignkey")
    op.drop_column("projects", "client_id")

    op.drop_index("ix_contacts_client_id", table_name="contacts")
    op.drop_index("ix_contacts_workspace_id", table_name="contacts")
    op.drop_table("contacts")

    op.drop_index("ix_clients_owner_id", table_name="clients")
    op.drop_index("ix_clients_workspace_id", table_name="clients")
    op.drop_table("clients")
