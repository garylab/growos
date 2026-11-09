"""action_records.plan_item_key: stable link to the plan item that survives plan regeneration

Revision ID: f1a2b3c4d5e6
Revises: e7f8a9b0c1d2
Create Date: 2026-11-07
"""
from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("action_records", sa.Column("plan_item_key", sa.String(length=300), nullable=True))
    op.create_index("ix_action_records_plan_item_key", "action_records", ["plan_item_key"])
    # Backfill the key for actions already linked to a plan item.
    op.execute(
        "UPDATE action_records a SET plan_item_key = p.key "
        "FROM plan_items p WHERE a.plan_item_id = p.id AND a.plan_item_key IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_action_records_plan_item_key", table_name="action_records")
    op.drop_column("action_records", "plan_item_key")
