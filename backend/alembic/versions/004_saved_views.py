"""add saved views table

Revision ID: 004
Revises: 003
Create Date: 2026-05-18
"""

import sqlalchemy as sa

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_views",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("dsl", sa.Text(), nullable=False),
        sa.Column("view", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_saved_views_user_name"),
    )
    op.create_index("ix_saved_views_user_id", "saved_views", ["user_id"], unique=False)
    op.create_index("ix_saved_views_updated_at", "saved_views", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_saved_views_updated_at", table_name="saved_views")
    op.drop_index("ix_saved_views_user_id", table_name="saved_views")
    op.drop_table("saved_views")
