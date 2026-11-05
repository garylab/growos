"""TaskQueue interface. The business logic only depends on this; the Postgres implementation can be
swapped for Redis/RabbitMQ later without touching tasks or API code."""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import CollectionJob


class TaskQueue(ABC):
    @abstractmethod
    def enqueue(self, db: Session, *, task_type: str, params: dict[str, Any], project_id: uuid.UUID | None,
                idempotency_key: str | None = None, priority: int = 100, max_attempts: int = 3,
                scheduled_at: datetime | None = None, triggered_by: str = "user") -> CollectionJob: ...

    @abstractmethod
    def claim(self, db: Session, worker_id: str, task_types: list[str] | None = None) -> CollectionJob | None: ...

    @abstractmethod
    def heartbeat(self, db: Session, job_id: uuid.UUID, progress: int | None = None, message: str | None = None) -> bool:
        """Returns False if cancellation was requested."""

    @abstractmethod
    def log(self, db: Session, job_id: uuid.UUID, message: str, level: str = "info") -> None: ...

    @abstractmethod
    def complete(self, db: Session, job_id: uuid.UUID, result: dict[str, Any] | None = None) -> None: ...

    @abstractmethod
    def fail(self, db: Session, job_id: uuid.UUID, error: str, retry: bool = True) -> None: ...

    @abstractmethod
    def cancel(self, db: Session, job_id: uuid.UUID) -> bool: ...

    @abstractmethod
    def retry(self, db: Session, job_id: uuid.UUID) -> bool: ...

    @abstractmethod
    def reap_stale(self, db: Session, timeout_seconds: int) -> int: ...
