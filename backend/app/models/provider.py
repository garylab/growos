from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProviderConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A configured external provider (API keys are encrypted at rest)."""
    __tablename__ = "provider_connections"

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)   # e.g. openai, gemini, gsc
    category: Mapped[str] = mapped_column(String(40), nullable=False)                   # ai, search_performance, ...
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)  # non-secret settings
    status: Mapped[str] = mapped_column(String(30), default="unverified", nullable=False)  # unverified|healthy|error|disabled
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)


class ProviderUsage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "provider_usage"

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("provider_connections.id", ondelete="SET NULL"))
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    units: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    unit_type: Mapped[str] = mapped_column(String(30), default="requests", nullable=False)  # requests|tokens|urls
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collection_jobs.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
