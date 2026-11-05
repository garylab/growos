from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class JobOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    task_type: str
    params: dict[str, Any]
    status: str
    priority: int
    progress: int
    progress_message: str | None
    attempts: int
    max_attempts: int
    scheduled_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None
    worker_id: str | None
    cancel_requested: bool
    error: str | None
    result: dict[str, Any] | None
    triggered_by: str
    created_at: datetime


class JobLogOut(ORMModel):
    id: int
    ts: datetime
    level: str
    message: str


class EnqueueIn(BaseModel):
    task_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    priority: int = 100


class ScheduleIn(BaseModel):
    task_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    interval_minutes: int = Field(ge=15, le=43200)
    label: str | None = None
    is_enabled: bool = True


class ScheduleOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    task_type: str
    params: dict[str, Any]
    interval_minutes: int
    is_enabled: bool
    next_run_at: datetime
    last_enqueued_at: datetime | None
    label: str | None
