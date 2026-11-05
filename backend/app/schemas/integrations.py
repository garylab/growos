from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ConnectionIn(BaseModel):
    provider_key: str
    display_name: str | None = None
    project_id: uuid.UUID | None = None
    credentials: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectionUpdate(BaseModel):
    display_name: str | None = None
    credentials: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    is_enabled: bool | None = None
    # None means "all projects". Omitting the field leaves the scope untouched, so the route
    # checks model_fields_set rather than the value to tell the two apart.
    project_id: uuid.UUID | None = None


class ConnectionTestIn(BaseModel):
    connection_id: uuid.UUID | None = None
    credentials: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectionOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    provider_key: str
    category: str
    display_name: str
    config: dict[str, Any]
    status: str
    last_checked_at: datetime | None
    last_error: str | None
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    credential_preview: dict[str, str] = Field(default_factory=dict)
