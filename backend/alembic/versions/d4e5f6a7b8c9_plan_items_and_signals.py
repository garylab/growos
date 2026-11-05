"""plan_items + page_snapshots.signals

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-02 22:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("page_snapshots", sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False))
    op.create_table(
        "plan_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("key", sa.String(300), nullable=False),
        sa.Column("section", sa.String(20), nullable=False),
        sa.Column("cadence", sa.String(20), nullable=False, server_default="once"),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("why", sa.Text(), nullable=False),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("suggestions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("impact", sa.Float(), nullable=False, server_default="50"),
        sa.Column("effort", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("priority", sa.Float(), nullable=False, server_default="0", index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="todo", index=True),
        sa.Column("completions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("next_due_at", sa.DateTime(timezone=True)),
        sa.Column("last_done_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(60), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_plan_items_key", "plan_items", ["project_id", "key"], unique=True)


def downgrade() -> None:
    op.drop_table("plan_items")
    op.drop_column("page_snapshots", "signals")
