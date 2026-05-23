"""add purged_at to batches

Revision ID: 006
Revises: 005
Create Date: 2026-05-19
"""

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "batches",
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("batches", "purged_at")
