from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

CONTENT_KINDS = ("article", "social_post", "video_script")
CONTENT_STATUSES = ("draft", "approved", "published", "discarded")
CHANNELS = ("blog", "linkedin", "x", "facebook", "instagram", "youtube_short", "tiktok", "reddit", "newsletter")


class ContentDraft(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A piece of content generated for a checklist item: article, social post or short-video script."""
    __tablename__ = "content_drafts"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    plan_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plan_items.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), default="blog", nullable=False)
    topic: Mapped[str] = mapped_column(String(400), nullable=False)
    title: Mapped[str | None] = mapped_column(String(400))
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    assets: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)  # hashtags, captions(SRT), shots, variants
    evidence: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)     # why this topic, from our data
    provider_key: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    published_url: Mapped[str | None] = mapped_column(String(2000))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
