"""add source sha256 to batches

Revision ID: 003
Revises: 002
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.exec_driver_sql(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='batches' AND column_name='source_sha256'"
    )
    if not result.fetchone():
        op.add_column("batches", sa.Column("source_sha256", sa.String(length=64), nullable=True))
        op.create_index("ix_batches_source_sha256", "batches", ["source_sha256"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_batches_source_sha256", table_name="batches")
    op.drop_column("batches", "source_sha256")
