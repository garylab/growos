from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class CrawlRun(UUIDPrimaryKeyMixin, Base):
    """One historical crawl/audit snapshot of a domain."""
    __tablename__ = "crawl_runs"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collection_jobs.id", ondelete="SET NULL"))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_artifacts.id", ondelete="SET NULL"))
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False)
    provider_version: Mapped[str | None] = mapped_column(String(60))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_urls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    html_pages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    count_by_status: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    quality_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    summary: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    findings_count: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class PageSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "page_snapshots"
    __table_args__ = (Index("ix_page_snapshots_run_url", "crawl_run_id", "url"),)

    crawl_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crawl_runs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    path: Mapped[str] = mapped_column(String(2000), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(30), default="other", nullable=False)  # html|js|css|image|...
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    meta_description: Mapped[str | None] = mapped_column(Text)
    h1: Mapped[str | None] = mapped_column(Text)
    indexing: Mapped[str | None] = mapped_column(String(100))
    robots_index: Mapped[bool | None] = mapped_column(Boolean)
    denied_by_robots_txt: Mapped[bool | None] = mapped_column(Boolean)
    headings_count: Mapped[int | None] = mapped_column(Integer)
    headings_errors: Mapped[int | None] = mapped_column(Integer)
    headings_structure: Mapped[str | None] = mapped_column(Text)
    canonical: Mapped[str | None] = mapped_column(String(2000))
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)  # contact/social/schema signals
    cache_type_flags: Mapped[int | None] = mapped_column(Integer)
    cache_lifetime: Mapped[int | None] = mapped_column(Integer)
    og: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    seo_score: Mapped[int | None] = mapped_column(Integer)  # 0..100, computed from findings
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AuditFinding(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_findings"

    crawl_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crawl_runs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    page_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("page_snapshots.id", ondelete="CASCADE"))
    url: Mapped[str | None] = mapped_column(String(2000))
    code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)   # missing_title, broken_link, ...
    category: Mapped[str] = mapped_column(String(40), nullable=False)           # metadata|links|content|technical|performance|security
    severity: Mapped[str] = mapped_column(String(20), nullable=False)           # critical|warning|info
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PerformanceObservation(UUIDPrimaryKeyMixin, Base):
    """Lighthouse (lab) and Chrome UX Report (field) measurements. measurement_type distinguishes them."""
    __tablename__ = "performance_observations"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collection_jobs.id", ondelete="SET NULL"))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_artifacts.id", ondelete="SET NULL"))
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    strategy: Mapped[str] = mapped_column(String(20), default="mobile", nullable=False)
    measurement_type: Mapped[str] = mapped_column(String(10), nullable=False)  # lab|field
    tool_version: Mapped[str | None] = mapped_column(String(40))
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)   # performance, seo, ...
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)  # lcp_ms, cls, inp_ms, ...
    audits: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)        # failing audits (id, title, score)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SearchObservation(UUIDPrimaryKeyMixin, Base):
    """First-party search performance (Google Search Console). One row per date x query x page x country x device."""
    __tablename__ = "search_observations"
    __table_args__ = (
        UniqueConstraint("domain_id", "date", "query", "page", "country", "device", name="uq_search_obs"),
        Index("ix_search_obs_domain_date", "domain_id", "date"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collection_jobs.id", ondelete="SET NULL"))
    provider_key: Mapped[str] = mapped_column(String(60), default="google_search_console", nullable=False)
    property_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    query: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    page: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    country: Mapped[str] = mapped_column(String(5), default="", nullable=False)
    device: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ctr: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    position: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BingSearchObservation(UUIDPrimaryKeyMixin, Base):
    """First-party Bing search performance, deliberately kept out of `search_observations`.

    Two reasons it is a separate table rather than another `provider_key` in the Google one:

    * Nothing that reads `search_observations` filters by provider — totals, the scorecard, outcome measurement
      and the growth plan all sum the table as-is. Adding a second search engine to it would silently inflate
      every number the product presents as Search Console data, and any future query that forgot the filter
      would do it again. Separation makes that mistake impossible instead of merely discouraged.
    * The data genuinely has a different shape. Bing gives daily totals but query and page figures only as
      aggregates over its own rolling window, with no country or device breakdown, so rows here are not
      interchangeable with GSC rows even where the columns line up.

    `dataset` records which of those three shapes a row is, so an aggregate is never read as a daily figure.
    """
    __tablename__ = "bing_search_observations"
    __table_args__ = (
        UniqueConstraint("domain_id", "date", "dataset", "query", "page", name="uq_bing_search_obs"),
        Index("ix_bing_search_obs_domain_date", "domain_id", "date"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collection_jobs.id", ondelete="SET NULL"))
    provider_key: Mapped[str] = mapped_column(String(60), default="bing_webmaster", nullable=False)
    site_url: Mapped[str] = mapped_column(String(500), nullable=False)
    dataset: Mapped[str] = mapped_column(String(20), nullable=False)  # rank_traffic | query_stats | page_stats
    date: Mapped[date] = mapped_column(Date, nullable=False)
    query: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    page: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ctr: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    position: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReferringDomain(UUIDPrimaryKeyMixin, Base):
    """One referring domain as a provider reported it on a given day.

    Stored as a daily snapshot per provider so the trend (and newly gained / lost domains) can be derived without
    trusting any single run. Providers disagree on coverage, hence provider_key in the key.
    """
    __tablename__ = "referring_domains"
    __table_args__ = (UniqueConstraint("domain_id", "provider_key", "observed_on", "referring_domain",
                                       name="uq_referring_domain_day"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False)
    observed_on: Mapped[date] = mapped_column(Date, nullable=False)
    referring_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    backlinks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dofollow: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    domain_rating: Mapped[float | None] = mapped_column(Float)
    first_seen: Mapped[date | None] = mapped_column(Date)
    last_seen: Mapped[date | None] = mapped_column(Date)
    example_url: Mapped[str | None] = mapped_column(String(2000))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BacklinkProfileSnapshot(UUIDPrimaryKeyMixin, Base):
    """Complete profile counters, kept apart from a provider's selected/sample rows."""
    __tablename__ = "backlink_profile_snapshots"
    __table_args__ = (UniqueConstraint("domain_id", "provider_key", "observed_on",
                                       name="uq_backlink_profile_day"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False)
    observed_on: Mapped[date] = mapped_column(Date, nullable=False)
    authority_score: Mapped[float | None] = mapped_column(Float)
    backlinks: Mapped[int | None] = mapped_column(Integer)
    referring_domains: Mapped[int | None] = mapped_column(Integer)
    dofollow: Mapped[int | None] = mapped_column(Integer)
    nofollow: Mapped[int | None] = mapped_column(Integer)
    sampled_backlinks: Mapped[int | None] = mapped_column(Integer)
    sampled_referring_domains: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Backlink(UUIDPrimaryKeyMixin, Base):
    """One individual link: the page that links, the page it points at, and the anchor text.

    Unlike ReferringDomain this is not a daily snapshot — a link is a long-lived thing, so the row is upserted and
    `observed_on` records the last sync that still saw it. link_hash keys the row because the two URLs together are
    too long for a btree unique index.
    """
    __tablename__ = "backlinks"
    __table_args__ = (UniqueConstraint("domain_id", "provider_key", "link_hash", name="uq_backlink_link"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False)
    link_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    url_from: Mapped[str] = mapped_column(String(2000), nullable=False)
    url_to: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    referring_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    anchor: Mapped[str | None] = mapped_column(String(500))
    page_title: Mapped[str | None] = mapped_column(String(500))
    dofollow: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    domain_rating: Mapped[float | None] = mapped_column(Float)
    first_seen: Mapped[date | None] = mapped_column(Date)
    last_seen: Mapped[date | None] = mapped_column(Date)
    observed_on: Mapped[date] = mapped_column(Date, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KeywordMetric(UUIDPrimaryKeyMixin, Base):
    """What a target keyword is worth, as one provider saw it on one day.

    A snapshot rather than columns on `keywords`, because volume and difficulty drift and the trend is the useful
    part. Providers disagree, so provider_key is part of the key and numbers are never mixed across providers.
    """
    __tablename__ = "keyword_metrics"
    __table_args__ = (UniqueConstraint("keyword_id", "provider_key", "observed_on", name="uq_keyword_metric_day"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    keyword_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("keywords.id", ondelete="CASCADE"), index=True)
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False)
    observed_on: Mapped[date] = mapped_column(Date, nullable=False)
    search_volume: Mapped[int | None] = mapped_column(Integer)
    difficulty: Mapped[float | None] = mapped_column(Float)
    cpc: Mapped[float | None] = mapped_column(Float)
    competition: Mapped[float | None] = mapped_column(Float)
    intent: Mapped[str | None] = mapped_column(String(40))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RankedKeyword(UUIDPrimaryKeyMixin, Base):
    """A keyword some host ranks for, for your site and for competitors alike.

    `host` rather than a domain FK so a competitor the user has not added as a Domain can still be measured; the
    keyword gap is then a set difference over this one table.
    """
    __tablename__ = "ranked_keywords"
    __table_args__ = (UniqueConstraint("project_id", "provider_key", "host", "observed_on", "keyword",
                                       name="uq_ranked_keyword_day"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    is_own: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    observed_on: Mapped[date] = mapped_column(Date, nullable=False)
    keyword: Mapped[str] = mapped_column(String(300), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str | None] = mapped_column(String(2000))
    search_volume: Mapped[int | None] = mapped_column(Integer)
    traffic: Mapped[float | None] = mapped_column(Float)
    difficulty: Mapped[float | None] = mapped_column(Float)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RankObservation(UUIDPrimaryKeyMixin, Base):
    """Where a tracked keyword actually sits on the SERP, including 'checked and not found'."""
    __tablename__ = "rank_observations"
    __table_args__ = (UniqueConstraint("keyword_id", "domain_id", "provider_key", "observed_on",
                                       name="uq_rank_observation_day"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    keyword_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("keywords.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    provider_key: Mapped[str] = mapped_column(String(60), nullable=False)
    observed_on: Mapped[date] = mapped_column(Date, nullable=False)
    # NULL means the SERP was checked and the site was not in it — different from "never checked".
    position: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str | None] = mapped_column(String(2000))
    serp_features: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
