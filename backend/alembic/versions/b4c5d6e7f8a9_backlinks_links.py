"""backlinks: individual links with anchor text

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-11-04 11:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backlinks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", UUID(as_uuid=True), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_key", sa.String(60), nullable=False),
        sa.Column("link_hash", sa.String(64), nullable=False),
        sa.Column("url_from", sa.String(2000), nullable=False),
        sa.Column("url_to", sa.String(2000), server_default="", nullable=False),
        sa.Column("referring_domain", sa.String(255), nullable=False),
        sa.Column("anchor", sa.String(500)),
        sa.Column("page_title", sa.String(500)),
        sa.Column("dofollow", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("domain_rating", sa.Float()),
        sa.Column("first_seen", sa.Date()),
        sa.Column("last_seen", sa.Date()),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("domain_id", "provider_key", "link_hash", name="uq_backlink_link"),
    )
    op.create_index("ix_backlinks_project_id", "backlinks", ["project_id"])
    op.create_index("ix_backlinks_domain_id", "backlinks", ["domain_id"])
    op.create_index("ix_backlinks_referring_domain", "backlinks", ["referring_domain"])


def downgrade() -> None:
    op.drop_table("backlinks")
