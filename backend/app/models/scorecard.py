from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class ScorecardSnapshot(UUIDPrimaryKeyMixin, Base):
    """A daily point of the three indices + overall + revenue run-rate, so the scorecard can show trend lines."""
    __tablename__ = "scorecard_snapshots"
    __table_args__ = (Index("ix_scorecard_snapshot_day", "project_id", "day", unique=True),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    overall: Mapped[float | None] = mapped_column(Float)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)       # {index_key: score|null}
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)      # {index_key: 0..1}
    revenue_run_rate: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
