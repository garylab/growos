"""merge growth opportunities into plan items

The rule engine existed twice: `rules.py` producing `growth_opportunities` and `playbook.py` producing `plan_items`,
with the same detections (low CTR, striking distance, broken links …) implemented with separate thresholds. This
collapses them onto `plan_items`, which is what the user actually works from.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-03 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plan_items", sa.Column("confidence", sa.Float(), nullable=False, server_default="0.7"))
    op.add_column("plan_items", sa.Column("score_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"))
    op.add_column("plan_items", sa.Column("origin", sa.String(20), nullable=False, server_default="rule"))
    op.add_column("plan_items", sa.Column("target_urls", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"))
    op.add_column("plan_items", sa.Column("target_keywords", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"))
    op.add_column("plan_items", sa.Column("history", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"))

    # Actions now hang off the checklist item they came from.
    op.add_column("action_records", sa.Column("plan_item_id", postgresql.UUID(as_uuid=True),
                                              sa.ForeignKey("plan_items.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_action_records_plan_item_id", "action_records", ["plan_item_id"])
    op.drop_column("action_records", "opportunity_id")

    op.drop_table("opportunity_history")
    op.drop_table("growth_opportunities")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: the opportunity tables duplicated plan_items and were removed.")
