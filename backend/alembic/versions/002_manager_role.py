"""add manager role

Revision ID: 002
Revises: 001
Create Date: 2026-05-15
"""

from alembic import op
from sqlalchemy import text

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
            INSERT INTO roles (id, name) VALUES
              ('a0000000-0000-4000-8000-000000000004', 'manager')
            ON CONFLICT (name) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(text("DELETE FROM roles WHERE name = 'manager'"))
