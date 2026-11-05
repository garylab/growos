"""page_snapshots cache fields

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-02 19:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("page_snapshots", sa.Column("cache_type_flags", sa.Integer(), nullable=True))
    op.add_column("page_snapshots", sa.Column("cache_lifetime", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("page_snapshots", "cache_lifetime")
    op.drop_column("page_snapshots", "cache_type_flags")
