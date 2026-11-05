"""google sign-in: users.google_sub and google_login_states

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-11-03 19:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_sub", sa.String(64)))
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)
    op.create_table(
        "google_login_states",
        sa.Column("state", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("google_login_states")
    op.drop_index("ix_users_google_sub", "users")
    op.drop_column("users", "google_sub")
