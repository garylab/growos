"""listing_destinations: submission targets synced from awesome-submitlist

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-11-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "listing_destinations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("website_url", sa.String(length=1000)),
        sa.Column("submission_url", sa.String(length=1000)),
        sa.Column("logo_url", sa.String(length=1000)),
        sa.Column("description", sa.Text()),
        sa.Column("audience", sa.Text()),
        sa.Column("eligibility", sa.Text()),
        sa.Column("pricing", sa.String(length=40)),
        sa.Column("pricing_note", sa.Text()),
        sa.Column("link_type", sa.String(length=40)),
        sa.Column("domain_rating", sa.Integer()),
        sa.Column("monthly_traffic", sa.Integer()),
        sa.Column("categories", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("subreddit", postgresql.JSONB()),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_listing_destinations_slug", "listing_destinations", ["slug"], unique=True)
    op.create_index("ix_listing_destinations_type", "listing_destinations", ["type"])


def downgrade() -> None:
    op.drop_index("ix_listing_destinations_type", table_name="listing_destinations")
    op.drop_index("ix_listing_destinations_slug", table_name="listing_destinations")
    op.drop_table("listing_destinations")
