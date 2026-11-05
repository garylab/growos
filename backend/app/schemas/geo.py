from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class PromptIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000)
    intent: str = "informational"
    topic: str | None = None
    language: str = "en"
    country: str = "US"
    is_active: bool = True
    samples_per_run: int = Field(default=3, ge=1, le=10)
    tags: list[str] = Field(default_factory=list)


class PromptUpdate(BaseModel):
    text: str | None = None
    intent: str | None = None
    topic: str | None = None
    language: str | None = None
    country: str | None = None
    is_active: bool | None = None
    samples_per_run: int | None = Field(default=None, ge=1, le=10)
    tags: list[str] | None = None


class PromptOut(ORMModel):
    id: uuid.UUID
    text: str
    intent: str
    topic: str | None
    language: str
    country: str
    is_active: bool
    samples_per_run: int
    tags: list[str]
    created_at: datetime


class RunPromptsIn(BaseModel):
    prompt_ids: list[uuid.UUID] = Field(default_factory=list)
    provider_keys: list[str] = Field(default_factory=list)
    samples: int | None = Field(default=None, ge=1, le=10)


class MentionOut(ORMModel):
    entity_type: str
    entity_name: str
    position: int | None
    list_rank: int | None
    mention_count: int
    sentiment: str
    context_snippet: str | None


class ObservationOut(ORMModel):
    id: uuid.UUID
    prompt_id: uuid.UUID
    run_id: uuid.UUID
    sample_index: int
    provider_key: str
    model: str
    model_version: str | None
    language: str
    country: str
    request_config: dict[str, Any]
    grounded: bool
    grounding_type: str
    answer_text: str | None
    citations: list[Any]
    brand_mentioned: bool
    brand_position: int | None
    own_domain_cited: bool
    sentiment: str | None
    latency_ms: int | None
    error: str | None
    observed_at: datetime
    mentions: list[MentionOut] = Field(default_factory=list)
