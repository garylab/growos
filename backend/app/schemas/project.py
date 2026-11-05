from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    brand_name: str = Field(min_length=1, max_length=200)
    brand_aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    default_language: str = "en"
    default_country: str = "US"
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: str | None = None
    brand_name: str | None = None
    brand_aliases: list[str] | None = None
    description: str | None = None
    default_language: str | None = None
    default_country: str | None = None
    settings: dict[str, Any] | None = None


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    brand_name: str
    brand_aliases: list[str]
    description: str | None
    default_language: str
    default_country: str
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DomainIn(BaseModel):
    url: str = Field(min_length=4, max_length=500)
    role: str = "primary"
    competitor_id: uuid.UUID | None = None
    gsc_property: str | None = None
    ga4_property: str | None = None
    bing_site_url: str | None = None
    watch_urls: list[str] = Field(default_factory=list)

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ("primary", "competitor"):
            raise ValueError("role must be primary or competitor")
        return v


class DomainUpdate(BaseModel):
    gsc_property: str | None = None
    ga4_property: str | None = None
    bing_site_url: str | None = None
    watch_urls: list[str] | None = None
    is_active: bool | None = None
    competitor_id: uuid.UUID | None = None


class DomainOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    hostname: str
    base_url: str
    role: str
    competitor_id: uuid.UUID | None
    gsc_property: str | None
    ga4_property: str | None
    bing_site_url: str | None
    is_active: bool
    watch_urls: list[str]
    created_at: datetime


class CompetitorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list)
    website: str | None = None
    notes: str | None = None


class CompetitorUpdate(BaseModel):
    """Every field optional: the edit form sends only what changed."""
    name: str | None = Field(default=None, min_length=1, max_length=200)
    aliases: list[str] | None = None
    website: str | None = None
    notes: str | None = None


class CompetitorOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    aliases: list[str]
    notes: str | None
    created_at: datetime


class KeywordIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    language: str = "en"
    country: str = "US"
    importance: int = Field(default=3, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)


class KeywordUpdate(BaseModel):
    """Partial update. Promoting a discovered candidate to a target is the main use: everything that costs money —
    pricing, rank checks, the keyword gap — works from targets only."""
    is_target: bool | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = None


class KeywordOut(ORMModel):
    id: uuid.UUID
    text: str
    language: str
    country: str
    is_target: bool
    importance: int
    tags: list[str]
    source: str
    created_at: datetime
