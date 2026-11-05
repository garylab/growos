"""keyword metrics, ranked keywords and rank tracking

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-11-04 14:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "keyword_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("keyword_id", UUID(as_uuid=True), sa.ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_key", sa.String(60), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("search_volume", sa.Integer()),
        sa.Column("difficulty", sa.Float()),
        sa.Column("cpc", sa.Float()),
        sa.Column("competition", sa.Float()),
        sa.Column("intent", sa.String(40)),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("keyword_id", "provider_key", "observed_on", name="uq_keyword_metric_day"),
    )
    op.create_index("ix_keyword_metrics_project_id", "keyword_metrics", ["project_id"])
    op.create_index("ix_keyword_metrics_keyword_id", "keyword_metrics", ["keyword_id"])

    op.create_table(
        "ranked_keywords",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_key", sa.String(60), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("is_own", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("keyword", sa.String(300), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(2000)),
        sa.Column("search_volume", sa.Integer()),
        sa.Column("traffic", sa.Float()),
        sa.Column("difficulty", sa.Float()),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("project_id", "provider_key", "host", "observed_on", "keyword", name="uq_ranked_keyword_day"),
    )
    op.create_index("ix_ranked_keywords_project_id", "ranked_keywords", ["project_id"])
    op.create_index("ix_ranked_keywords_host", "ranked_keywords", ["host"])

    op.create_table(
        "rank_observations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("keyword_id", UUID(as_uuid=True), sa.ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", UUID(as_uuid=True), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_key", sa.String(60), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("position", sa.Integer()),
        sa.Column("url", sa.String(2000)),
        sa.Column("serp_features", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("keyword_id", "domain_id", "provider_key", "observed_on", name="uq_rank_observation_day"),
    )
    op.create_index("ix_rank_observations_project_id", "rank_observations", ["project_id"])
    op.create_index("ix_rank_observations_keyword_id", "rank_observations", ["keyword_id"])
    op.create_index("ix_rank_observations_domain_id", "rank_observations", ["domain_id"])


def downgrade() -> None:
    op.drop_table("rank_observations")
    op.drop_table("ranked_keywords")
    op.drop_table("keyword_metrics")
