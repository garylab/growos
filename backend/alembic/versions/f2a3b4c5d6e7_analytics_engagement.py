"""analytics engagement: engaged_sessions and engagement_time_sec

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-03 21:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rows collected before this migration keep 0; they fill in on the next GA4 sync.
    op.add_column("analytics_events", sa.Column("engaged_sessions", sa.Integer(), server_default="0", nullable=False))
    op.add_column("analytics_events", sa.Column("engagement_time_sec", sa.Float(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("analytics_events", "engagement_time_sec")
    op.drop_column("analytics_events", "engaged_sessions")
