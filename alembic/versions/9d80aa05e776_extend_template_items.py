# alembic/versions/9d80aa05e776_extend_template_items.py
"""extend_template_items

Расширяет task_template_items: description, deadline_offset_days, tags,
checklist — чтобы шаблон описывал не только заголовок+приоритет, а полный
набор того, что появилось в задачах за последнее время (дедлайн, теги,
чек-лист), и при применении к проекту создавал полноценные задачи.

Revision ID: 9d80aa05e776
Revises: f8a1b2c3d4e5
Create Date: 2026-08-08 10:00:00.000000

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "9d80aa05e776"
down_revision = "f8a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = [col["name"] for col in inspector.get_columns("task_template_items")]
    is_postgres = bind.dialect.name == "postgresql"
    json_type = postgresql.JSONB() if is_postgres else sa.JSON()

    if "description" not in existing_columns:
        op.add_column("task_template_items", sa.Column("description", sa.Text(), nullable=True))
    if "deadline_offset_days" not in existing_columns:
        op.add_column("task_template_items", sa.Column("deadline_offset_days", sa.Integer(), nullable=True))
    if "tags" not in existing_columns:
        op.add_column("task_template_items", sa.Column("tags", json_type, nullable=True))
    if "checklist" not in existing_columns:
        op.add_column("task_template_items", sa.Column("checklist", json_type, nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_columns = [col["name"] for col in inspector.get_columns("task_template_items")]

    for col in ("checklist", "tags", "deadline_offset_days", "description"):
        if col in existing_columns:
            op.drop_column("task_template_items", col)
