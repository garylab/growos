from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PromptDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prompt_definitions"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String(40), default="informational", nullable=False)  # informational|commercial|comparison|navigational|transactional
    topic: Mapped[str | None] = mapped_column(String(120))
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    country: Mapped[str] = mapped_column(String(5), default="US", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    samples_per_run: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)


class AIAnswerObservation(UUIDPrimaryKeyMixin, Base):
    """One sampled answer from one AI provider for one prompt. Never overwritten."""
    __tablename__ = "ai_answer_observations"
    __table_args__ = (Index("ix_ai_obs_project_run", "project_id", "run_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    prompt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("prompt_definitions.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collection_jobs.id", ondelete="SET NULL"))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_artifacts.id", ondelete="SET NULL"))
    run_id: Mapped[uuid.UUID] = mapped_column(nullable=False)  # groups all samples of one "run prompts" job
    sample_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("provider_connections.id", ondelete="SET NULL"))
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(120))  # as reported by the API response
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    country: Mapped[str] = mapped_column(String(5), nullable=False)
    request_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    grounded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    grounding_type: Mapped[str] = mapped_column(String(40), default="none", nullable=False)  # none|web_search|provider_search
    answer_text: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)  # [{url, domain, title}]
    brand_mentioned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    brand_position: Mapped[int | None] = mapped_column(Integer)
    own_domain_cited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sentiment: Mapped[str | None] = mapped_column(String(20))
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    answer_hash: Mapped[str | None] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AIAnswerMention(UUIDPrimaryKeyMixin, Base):
    """Normalized entity mention extracted from an AI answer (brand or competitor)."""
    __tablename__ = "ai_answer_mentions"

    observation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_answer_observations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # brand|competitor
    entity_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"))
    position: Mapped[int | None] = mapped_column(Integer)         # order of first appearance among entities (1 = first)
    list_rank: Mapped[int | None] = mapped_column(Integer)        # rank within a list/numbered recommendation, if any
    mention_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sentiment: Mapped[str] = mapped_column(String(20), default="neutral", nullable=False)
    sentiment_method: Mapped[str] = mapped_column(String(20), default="lexicon", nullable=False)
    context_snippet: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
