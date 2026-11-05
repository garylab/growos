"""page_snapshots.canonical

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-02 21:40:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("page_snapshots", sa.Column("canonical", sa.String(length=2000), nullable=True))


def downgrade() -> None:
    op.drop_column("page_snapshots", "canonical")
