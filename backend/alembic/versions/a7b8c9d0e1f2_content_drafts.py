"""content drafts

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-02 21:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("plan_items.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False, server_default="blog"),
        sa.Column("topic", sa.String(400), nullable=False),
        sa.Column("title", sa.String(400)),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("assets", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("provider_key", sa.String(60)),
        sa.Column("model", sa.String(120)),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("published_url", sa.String(2000)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_content_drafts_project_id", "content_drafts", ["project_id"])
    op.create_index("ix_content_drafts_plan_item_id", "content_drafts", ["plan_item_id"])
    op.create_index("ix_content_drafts_status", "content_drafts", ["status"])


def downgrade() -> None:
    op.drop_table("content_drafts")
