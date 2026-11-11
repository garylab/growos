from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

PLAN_SECTIONS = ("setup", "business", "fix", "routine")
PLAN_CADENCES = ("once", "daily", "weekly", "monthly")
PLAN_STATUSES = ("todo", "in_progress", "done", "skipped")


class PlanItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One user-facing checklist item of the Growth Plan (one-time fix, setup step or recurring routine)."""
    __tablename__ = "plan_items"
    __table_args__ = (Index("ix_plan_items_key", "project_id", "key", unique=True),
                      Index("uq_plan_items_seq", "project_id", "seq", unique=True))

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    # Stable per-project display number ("NO"), assigned once when the item is first created and never changed on
    # a rebuild — so a task keeps the same number for the life of the project even as the plan is re-synced.
    seq: Mapped[int | None] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(300), nullable=False)
    section: Mapped[str] = mapped_column(String(20), nullable=False)       # setup | business | fix | routine
    cadence: Mapped[str] = mapped_column(String(20), default="once", nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)      # website | content | video | community | backlinks | conversion | competitors | ai_visibility | business | setup
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False)
    steps: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)       # how to do it
    suggestions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)  # placeholders: topics, outline, targets, pages…
    evidence: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    impact: Mapped[float] = mapped_column(Float, default=50, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)   # 0..1, how sure the evidence is
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    origin: Mapped[str] = mapped_column(String(20), default="rule", nullable=False)  # rule | ai | user
    target_urls: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    target_keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    history: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)  # status changes, rescoring
    effort: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    priority: Mapped[float] = mapped_column(Float, default=0, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="todo", nullable=False, index=True)
    completions: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)  # routine: [{at, note}]
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # fix verified gone by data
    source: Mapped[str] = mapped_column(String(60), nullable=False)               # playbook rule id
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
