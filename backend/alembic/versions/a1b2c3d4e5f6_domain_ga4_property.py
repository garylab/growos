"""domain ga4_property

Revision ID: a1b2c3d4e5f6
Revises: c0326c15b047
Create Date: 2026-11-02 15:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "c0326c15b047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("domains", sa.Column("ga4_property", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("domains", "ga4_property")
