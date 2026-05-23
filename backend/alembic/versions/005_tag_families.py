"""add tag families table and link tags

Revision ID: 005
Revises: 004
Create Date: 2026-05-18
"""

import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tag_families",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_tag_families_code"),
    )
    op.add_column("tags", sa.Column("family_id", sa.UUID(), nullable=True))
    op.create_index("ix_tags_family_id", "tags", ["family_id"], unique=False)
    op.create_foreign_key(
        "fk_tags_family_id",
        "tags",
        "tag_families",
        ["family_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        INSERT INTO tag_families (id, code)
        SELECT gen_random_uuid(), fam
        FROM (
          SELECT DISTINCT
            CASE upper(type)
              WHEN 'LOGIN' THEN 'CREDENTIAL'
              WHEN 'LEAK' THEN 'DATA_LEAK'
              WHEN 'VM' THEN 'INFRASTRUCTURE'
              ELSE NULL
            END AS fam
          FROM tags
          WHERE deleted_at IS NULL AND type IS NOT NULL
        ) q
        WHERE fam IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE tags t
        SET family_id = tf.id
        FROM tag_families tf
        WHERE tf.code = (
          CASE upper(t.type)
            WHEN 'LOGIN' THEN 'CREDENTIAL'
            WHEN 'LEAK' THEN 'DATA_LEAK'
            WHEN 'VM' THEN 'INFRASTRUCTURE'
            ELSE NULL
          END
        )
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_tags_family_id", "tags", type_="foreignkey")
    op.drop_index("ix_tags_family_id", table_name="tags")
    op.drop_column("tags", "family_id")
    op.drop_table("tag_families")
