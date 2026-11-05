from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ActionIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    plan_item_id: uuid.UUID | None = None
    status: str = "planned"
    owner: str | None = None
    target_urls: list[str] = Field(default_factory=list)
    target_keywords: list[str] = Field(default_factory=list)
    target_prompt_ids: list[str] = Field(default_factory=list)
    notes: str | None = None


class ActionUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    owner: str | None = None
    target_urls: list[str] | None = None
    target_keywords: list[str] | None = None
    target_prompt_ids: list[str] | None = None
    notes: str | None = None


class ActionOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    plan_item_id: uuid.UUID | None
    title: str
    description: str | None
    status: str
    owner: str | None
    target_urls: list[str]
    target_keywords: list[str]
    target_prompt_ids: list[str]
    started_at: datetime | None
    completed_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class OutcomeOut(ORMModel):
    id: uuid.UUID
    action_id: uuid.UUID
    metric_key: str
    source: str
    measurement_type: str
    baseline_period: dict[str, Any]
    comparison_period: dict[str, Any]
    baseline_value: float | None
    current_value: float | None
    delta: float | None
    delta_pct: float | None
    details: dict[str, Any]
    measured_at: datetime


class AnalysisIn(BaseModel):
    focus: str | None = None
