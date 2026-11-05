"""backlink profile totals separate from sampled rows

Revision ID: e7f8a9b0c1d2
Revises: d5e6f7a8b9c0
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "e7f8a9b0c1d2"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backlink_profile_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", UUID(as_uuid=True), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_key", sa.String(60), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("authority_score", sa.Float()), sa.Column("backlinks", sa.Integer()),
        sa.Column("referring_domains", sa.Integer()), sa.Column("dofollow", sa.Integer()),
        sa.Column("nofollow", sa.Integer()), sa.Column("sampled_backlinks", sa.Integer()),
        sa.Column("sampled_referring_domains", sa.Integer()), sa.Column("note", sa.Text()),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("domain_id", "provider_key", "observed_on", name="uq_backlink_profile_day"),
    )
    op.create_index("ix_backlink_profile_snapshots_project_id", "backlink_profile_snapshots", ["project_id"])
    op.create_index("ix_backlink_profile_snapshots_domain_id", "backlink_profile_snapshots", ["domain_id"])


def downgrade() -> None:
    op.drop_index("ix_backlink_profile_snapshots_domain_id", table_name="backlink_profile_snapshots")
    op.drop_index("ix_backlink_profile_snapshots_project_id", table_name="backlink_profile_snapshots")
    op.drop_table("backlink_profile_snapshots")
