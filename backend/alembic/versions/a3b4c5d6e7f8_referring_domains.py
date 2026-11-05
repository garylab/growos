"""backlinks: referring_domains daily snapshots

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-11-04 09:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "referring_domains",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", UUID(as_uuid=True), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_key", sa.String(60), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("referring_domain", sa.String(255), nullable=False),
        sa.Column("backlinks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("dofollow", sa.Integer(), server_default="0", nullable=False),
        sa.Column("domain_rating", sa.Float()),
        sa.Column("first_seen", sa.Date()),
        sa.Column("last_seen", sa.Date()),
        sa.Column("example_url", sa.String(2000)),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("domain_id", "provider_key", "observed_on", "referring_domain", name="uq_referring_domain_day"),
    )
    op.create_index("ix_referring_domains_project_id", "referring_domains", ["project_id"])
    op.create_index("ix_referring_domains_domain_id", "referring_domains", ["domain_id"])


def downgrade() -> None:
    op.drop_table("referring_domains")
