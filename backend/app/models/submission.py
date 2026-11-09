from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class SubmissionTarget(UUIDPrimaryKeyMixin, Base):
    """A place to submit or claim a listing: directory, citation site, marketplace, subreddit, newsletter, etc.

    Mirrored monthly from the public awesome-submitlist dataset and keyed by the source `slug`. An optional
    embedding of its text (name + audience + description + categories) powers semantic matching.
    """
    __tablename__ = "submission_targets"

    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    website_url: Mapped[str | None] = mapped_column(String(1000))
    submission_url: Mapped[str | None] = mapped_column(String(1000))
    logo_url: Mapped[str | None] = mapped_column(String(1000))
    description: Mapped[str | None] = mapped_column(Text)
    audience: Mapped[str | None] = mapped_column(Text)
    eligibility: Mapped[str | None] = mapped_column(Text)
    pricing: Mapped[str | None] = mapped_column(String(40))
    pricing_note: Mapped[str | None] = mapped_column(Text)
    link_type: Mapped[str | None] = mapped_column(String(40))
    domain_rating: Mapped[int | None] = mapped_column(Integer)
    monthly_traffic: Mapped[int | None] = mapped_column(Integer)
    categories: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    subreddit: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
