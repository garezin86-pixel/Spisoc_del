"""add spisok_del.client_id (задача ↔ клиент)

Настоящая связь задачи с клиентом CRM вместо пометки в названии/описании. Необязательная; при жёстком удалении клиента
обнуляется (мягко удалённого клиента API просто не показывает).

Revision ID: n9c0d1e2f3a4
Revises: m8b9c0d1e2f3
Create Date: 2026-10-18
"""

import sqlalchemy as sa

from alembic import op

revision = "n9c0d1e2f3a4"
down_revision = "m8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "spisok_del",
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_spisok_del_client_id", "spisok_del", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_spisok_del_client_id", table_name="spisok_del")
    op.drop_column("spisok_del", "client_id")
