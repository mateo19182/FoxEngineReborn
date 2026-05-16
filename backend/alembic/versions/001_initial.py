"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-14
"""

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from foxengine.db.models import Base

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    bind: Connection = op.get_bind()
    Base.metadata.create_all(bind=bind)
    bind.execute(
        text(
            """
            INSERT INTO roles (id, name) VALUES
              ('a0000000-0000-4000-8000-000000000001', 'admin'),
              ('a0000000-0000-4000-8000-000000000002', 'operator'),
              ('a0000000-0000-4000-8000-000000000003', 'viewer')
            ON CONFLICT (name) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
