"""Add a stable per-project display number (seq) to plan_items.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-11-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plan_items", sa.Column("seq", sa.Integer(), nullable=True))
    # Backfill existing rows: number each project's items 1..N in creation order so numbers are stable going forward.
    op.execute(
        """
        WITH numbered AS (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY created_at, id) AS rn
            FROM plan_items
        )
        UPDATE plan_items p SET seq = n.rn FROM numbered n WHERE p.id = n.id
        """
    )
    op.create_index("uq_plan_items_seq", "plan_items", ["project_id", "seq"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_plan_items_seq", table_name="plan_items")
    op.drop_column("plan_items", "seq")
