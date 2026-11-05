from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class BrandMention(UUIDPrimaryKeyMixin, Base):
    """A public mention of the brand or a competitor found via an authorized source (RSS, HN, Bluesky...)."""
    __tablename__ = "brand_mentions"
    __table_args__ = (UniqueConstraint("project_id", "provider_key", "source_id", "entity_name", name="uq_brand_mention"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collection_jobs.id", ondelete="SET NULL"))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_artifacts.id", ondelete="SET NULL"))
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2000))
    source_name: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(Text)
    content_excerpt: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(200))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # brand|competitor|topic
    entity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"))
    sentiment: Mapped[str] = mapped_column(String(20), default="neutral", nullable=False)
    sentiment_method: Mapped[str] = mapped_column(String(20), default="lexicon", nullable=False)
    topics: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    intent: Mapped[str] = mapped_column(String(30), default="none", nullable=False)  # none|question|recommendation_request|complaint|purchase_intent
    engagement: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)  # points, comments, likes
    language: Mapped[str | None] = mapped_column(String(10))
    is_relevant: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CompetitorObservation(UUIDPrimaryKeyMixin, Base):
    """Snapshot of a watched competitor page (pricing, features) and change detection against the previous one."""
    __tablename__ = "competitor_observations"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collection_jobs.id", ondelete="SET NULL"))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_artifacts.id", ondelete="SET NULL"))
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(Text)
    text_length: Mapped[int | None] = mapped_column(Integer)
    changed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    change_ratio: Mapped[float | None] = mapped_column(Float)
    diff_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)  # added/removed lines, price-like changes
    previous_observation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("competitor_observations.id", ondelete="SET NULL"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AnalyticsEvent(UUIDPrimaryKeyMixin, Base):
    """Daily first-party analytics aggregates per landing page (imported from the customer's analytics)."""
    __tablename__ = "analytics_events"
    __table_args__ = (UniqueConstraint("domain_id", "date", "landing_page", "source", "medium", name="uq_analytics_event"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    landing_page: Mapped[str] = mapped_column(String(2000), nullable=False)
    source: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    medium: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conversions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revenue: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    # GA4 engagement: sessions that engaged, and total seconds of engagement across all sessions.
    engaged_sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    engagement_time_sec: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
