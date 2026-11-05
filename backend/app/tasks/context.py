"""Execution context handed to every task: DB session, queue handle, job row, logging & progress helpers."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.artifacts import store_bytes, store_json
from app.models import CollectionJob, RawArtifact
from app.queue.base import TaskQueue


class JobCancelled(Exception):
    pass


@dataclass
class TaskContext:
    db: Session
    queue: TaskQueue
    job: CollectionJob

    @property
    def project_id(self) -> uuid.UUID | None:
        return self.job.project_id

    @property
    def params(self) -> dict[str, Any]:
        return self.job.params or {}

    def log(self, message: str, level: str = "info") -> None:
        self.queue.log(self.db, self.job.id, message, level)
        self.db.commit()

    def progress(self, pct: int, message: str | None = None) -> None:
        """Updates progress + heartbeat; raises JobCancelled if cancellation was requested."""
        if not self.queue.heartbeat(self.db, self.job.id, pct, message):
            raise JobCancelled()

    def save_artifact(self, provider_key: str, kind: str, payload: Any, *, content_type: str = "application/json",
                      meta: dict[str, Any] | None = None, ext: str | None = None) -> RawArtifact:
        pid = self.project_id or "global"
        if isinstance(payload, bytes):
            path, sha, size = store_bytes(pid, kind, payload, ext or "bin")
        else:
            path, sha, size = store_json(pid, kind, payload)
        art = RawArtifact(project_id=self.project_id, job_id=self.job.id, provider_key=provider_key, kind=kind,
                          storage_path=path, content_type=content_type, sha256=sha, size_bytes=size, meta=meta or {})
        self.db.add(art)
        self.db.flush()
        return art
