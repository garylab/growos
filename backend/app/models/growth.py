from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

ACTION_STATUSES = ("planned", "in_progress", "done", "cancelled")

# Growth-plan statuses (todo/in_progress/done/skipped) map onto action statuses here — in one place, so the two
# vocabularies cannot drift. Used when a plan item is promoted into a tracked result.
PLAN_TO_ACTION_STATUS = {"todo": "planned", "in_progress": "in_progress", "done": "done", "skipped": "cancelled"}


def plan_status_to_action(plan_status: str) -> str:
    """The action status that corresponds to a plan item's status. Unknown values fall back to 'planned'."""
    return PLAN_TO_ACTION_STATUS.get(plan_status, "planned")


class ActionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An optimization action the user commits to (optionally derived from an opportunity)."""
    __tablename__ = "action_records"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    plan_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plan_items.id", ondelete="SET NULL"), index=True)
    # The plan item's stable key, stored alongside the id so the link survives plan regeneration: the playbook
    # upserts plan items by key, but a key change gives a new row (and SET NULL orphans plan_item_id). The key lets
    # us re-resolve the current plan item. See app/api/routes/actions.py:_plan_items_for.
    plan_item_key: Mapped[str | None] = mapped_column(String(300), index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="planned", nullable=False, index=True)
    owner: Mapped[str | None] = mapped_column(String(120))
    target_urls: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    target_keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    target_prompt_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class OutcomeMeasurement(UUIDPrimaryKeyMixin, Base):
    """Before/after measurement of an action's target metrics from first-party or observed data."""
    __tablename__ = "outcome_measurements"

    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("action_records.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    metric_key: Mapped[str] = mapped_column(String(80), nullable=False)   # gsc_clicks, gsc_impressions, gsc_ctr, gsc_position, ai_brand_mention_rate, ...
    source: Mapped[str] = mapped_column(String(60), nullable=False)       # google_search_console | ai_visibility | analytics
    measurement_type: Mapped[str] = mapped_column(String(20), nullable=False)  # first_party | observed | estimated
    baseline_period: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    comparison_period: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    baseline_value: Mapped[float | None] = mapped_column(Float)
    current_value: Mapped[float | None] = mapped_column(Float)
    delta: Mapped[float | None] = mapped_column(Float)
    delta_pct: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
