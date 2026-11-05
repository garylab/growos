"""bing webmaster: per-domain site url + its own observations table

Revision ID: d5e6f7a8b9c0
Revises: c5d6e7f8a9b0
Create Date: 2026-11-05 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "d5e6f7a8b9c0"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("domains", sa.Column("bing_site_url", sa.String(length=500), nullable=True))
    op.create_table(
        "bing_search_observations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", UUID(as_uuid=True), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("collection_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider_key", sa.String(length=60), nullable=False, server_default="bing_webmaster"),
        sa.Column("site_url", sa.String(length=500), nullable=False),
        sa.Column("dataset", sa.String(length=20), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("query", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("page", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ctr", sa.Float(), nullable=False, server_default="0"),
        sa.Column("position", sa.Float(), nullable=False, server_default="0"),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("domain_id", "date", "dataset", "query", "page", name="uq_bing_search_obs"),
    )
    op.create_index("ix_bing_search_observations_project_id", "bing_search_observations", ["project_id"])
    op.create_index("ix_bing_search_observations_domain_id", "bing_search_observations", ["domain_id"])
    op.create_index("ix_bing_search_obs_domain_date", "bing_search_observations", ["domain_id", "date"])


def downgrade() -> None:
    op.drop_index("ix_bing_search_obs_domain_date", table_name="bing_search_observations")
    op.drop_index("ix_bing_search_observations_domain_id", table_name="bing_search_observations")
    op.drop_index("ix_bing_search_observations_project_id", table_name="bing_search_observations")
    op.drop_table("bing_search_observations")
    op.drop_column("domains", "bing_site_url")
