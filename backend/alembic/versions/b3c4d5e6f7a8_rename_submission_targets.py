"""rename listing_destinations -> submission_targets; add embeddings and project profile columns

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-11-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("listing_destinations", "submission_targets")
    op.execute("ALTER INDEX ix_listing_destinations_slug RENAME TO ix_submission_targets_slug")
    op.execute("ALTER INDEX ix_listing_destinations_type RENAME TO ix_submission_targets_type")
    op.add_column("submission_targets", sa.Column("embedding", postgresql.ARRAY(sa.Float())))
    op.add_column("projects", sa.Column("category_tags", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"))
    op.add_column("projects", sa.Column("profile_embedding", postgresql.ARRAY(sa.Float())))
    op.add_column("projects", sa.Column("profile_hash", sa.String(length=64)))
    op.add_column("projects", sa.Column("profile_embedded_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("projects", "profile_embedded_at")
    op.drop_column("projects", "profile_hash")
    op.drop_column("projects", "profile_embedding")
    op.drop_column("projects", "category_tags")
    op.drop_column("submission_targets", "embedding")
    op.execute("ALTER INDEX ix_submission_targets_type RENAME TO ix_listing_destinations_type")
    op.execute("ALTER INDEX ix_submission_targets_slug RENAME TO ix_listing_destinations_slug")
    op.rename_table("submission_targets", "listing_destinations")
