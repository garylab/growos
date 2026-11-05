from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    brand_name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand_aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    default_language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    default_country: Mapped[str] = mapped_column(String(5), default="US", nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    domains: Mapped[list["Domain"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    competitors: Mapped[list["Competitor"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Domain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A website tracked within a project. role=primary is the customer's site; competitor sites belong to a Competitor."""
    __tablename__ = "domains"
    __table_args__ = (UniqueConstraint("project_id", "hostname", name="uq_domain_project_hostname"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="primary", nullable=False)  # primary | competitor
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"))
    gsc_property: Mapped[str | None] = mapped_column(String(500))  # e.g. sc-domain:example.com
    ga4_property: Mapped[str | None] = mapped_column(String(100))  # GA4 property id, e.g. 123456789
    # The site exactly as it is verified in Bing Webmaster Tools, e.g. https://example.com — Bing matches on the
    # string, so it is stored rather than derived from base_url.
    bing_site_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    watch_urls: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)  # pages for change detection

    project: Mapped[Project] = relationship(back_populates="domains")
    competitor: Mapped["Competitor | None"] = relationship(back_populates="domains")


class Competitor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "competitors"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="competitors")
    # passive_deletes lets Postgres run the ON DELETE CASCADE on domains.competitor_id. Without it SQLAlchemy
    # nulls the FK first, leaving the competitor's sites behind as orphans with role="competitor".
    domains: Mapped[list[Domain]] = relationship(back_populates="competitor", passive_deletes=True)


class Keyword(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Target keywords/topics the business cares about (user-defined, or imported from GSC)."""
    __tablename__ = "keywords"
    __table_args__ = (UniqueConstraint("project_id", "text", "country", "language", name="uq_keyword"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(300), nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    country: Mapped[str] = mapped_column(String(5), default="US", nullable=False)
    is_target: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    importance: Mapped[int] = mapped_column(default=3, nullable=False)  # 1..5
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    source: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)
