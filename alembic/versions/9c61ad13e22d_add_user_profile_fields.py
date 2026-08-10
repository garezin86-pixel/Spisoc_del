# alembic/versions/9c61ad13e22d_add_user_profile_fields.py
"""add_user_profile_fields

Добавляет в users: position (должность) и avatar_storage_key/avatar_storage_url
(тот же паттерн, что у AttachmentModel) — для страницы профиля пользователя.

Revision ID: 9c61ad13e22d
Revises: 9d80aa05e776
Create Date: 2026-08-08 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "9c61ad13e22d"
down_revision = "9d80aa05e776"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_columns = [col["name"] for col in inspector.get_columns("users")]

    if "position" not in existing_columns:
        op.add_column("users", sa.Column("position", sa.String(120), nullable=True))
    if "avatar_storage_key" not in existing_columns:
        op.add_column("users", sa.Column("avatar_storage_key", sa.String(500), nullable=True))
    if "avatar_storage_url" not in existing_columns:
        op.add_column("users", sa.Column("avatar_storage_url", sa.String(1000), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_columns = [col["name"] for col in inspector.get_columns("users")]

    for col in ("avatar_storage_url", "avatar_storage_key", "position"):
        if col in existing_columns:
            op.drop_column("users", col)
