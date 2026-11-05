"""PostgreSQL-backed TaskQueue using SELECT ... FOR UPDATE SKIP LOCKED."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import CollectionJob, JobLog
from app.queue.base import TaskQueue

ACTIVE_STATUSES = ("queued", "running")


class PostgresTaskQueue(TaskQueue):
    def enqueue(self, db: Session, *, task_type: str, params: dict[str, Any], project_id: uuid.UUID | None,
                idempotency_key: str | None = None, priority: int = 100, max_attempts: int = 3,
                scheduled_at: datetime | None = None, triggered_by: str = "user") -> CollectionJob:
        if idempotency_key:
            existing = db.scalar(select(CollectionJob).where(CollectionJob.idempotency_key == idempotency_key))
            if existing is not None:
                if existing.status in ACTIVE_STATUSES:
                    return existing
                # Terminal job with the same key: release the key so it stays in history and a new run can start.
                existing.idempotency_key = f"{idempotency_key}#{existing.id.hex[:8]}"
                db.flush()
        job = CollectionJob(project_id=project_id, task_type=task_type, params=params,
                            idempotency_key=idempotency_key, priority=priority, max_attempts=max_attempts,
                            scheduled_at=scheduled_at or datetime.now(UTC), triggered_by=triggered_by)
        db.add(job)
        db.flush()
        self.log(db, job.id, f"Job queued ({task_type})")
        return job

    def claim(self, db: Session, worker_id: str, task_types: list[str] | None = None) -> CollectionJob | None:
        stmt = (select(CollectionJob)
                .where(CollectionJob.status == "queued", CollectionJob.scheduled_at <= datetime.now(UTC))
                .order_by(CollectionJob.priority.asc(), CollectionJob.scheduled_at.asc())
                .with_for_update(skip_locked=True).limit(1))
        if task_types:
            stmt = stmt.where(CollectionJob.task_type.in_(task_types))
        job = db.scalar(stmt)
        if job is None:
            return None
        now = datetime.now(UTC)
        job.status = "running"
        job.worker_id = worker_id
        job.started_at = now
        job.heartbeat_at = now
        job.attempts += 1
        job.error = None
        db.flush()
        self.log(db, job.id, f"Claimed by {worker_id} (attempt {job.attempts}/{job.max_attempts})")
        db.commit()
        return job

    def heartbeat(self, db: Session, job_id: uuid.UUID, progress: int | None = None, message: str | None = None) -> bool:
        values: dict[str, Any] = {"heartbeat_at": datetime.now(UTC)}
        if progress is not None:
            values["progress"] = max(0, min(100, int(progress)))
        if message is not None:
            values["progress_message"] = message[:500]
        db.execute(update(CollectionJob).where(CollectionJob.id == job_id).values(**values))
        cancel = db.scalar(select(CollectionJob.cancel_requested).where(CollectionJob.id == job_id))
        db.commit()
        return not bool(cancel)

    def log(self, db: Session, job_id: uuid.UUID, message: str, level: str = "info") -> None:
        db.add(JobLog(job_id=job_id, level=level, message=message[:4000]))
        db.flush()

    def complete(self, db: Session, job_id: uuid.UUID, result: dict[str, Any] | None = None) -> None:
        db.execute(update(CollectionJob).where(CollectionJob.id == job_id).values(
            status="succeeded", finished_at=datetime.now(UTC), progress=100, result=result or {}))
        self.log(db, job_id, "Job succeeded")
        db.commit()

    def fail(self, db: Session, job_id: uuid.UUID, error: str, retry: bool = True) -> None:
        job = db.get(CollectionJob, job_id)
        if job is None:
            return
        can_retry = retry and job.attempts < job.max_attempts and not job.cancel_requested
        job.error = error[:4000]
        job.finished_at = datetime.now(UTC)
        if can_retry:
            backoff = timedelta(seconds=min(600, 15 * (2 ** (job.attempts - 1))))
            job.status = "queued"
            job.scheduled_at = datetime.now(UTC) + backoff
            self.log(db, job_id, f"Attempt failed: {error[:500]} — retrying in {int(backoff.total_seconds())}s", "warning")
        else:
            job.status = "cancelled" if job.cancel_requested else "failed"
            self.log(db, job_id, f"Job failed: {error[:500]}", "error")
        db.commit()

    def cancel(self, db: Session, job_id: uuid.UUID) -> bool:
        job = db.get(CollectionJob, job_id)
        if job is None or job.status not in ACTIVE_STATUSES:
            return False
        if job.status == "queued":
            job.status = "cancelled"
            job.finished_at = datetime.now(UTC)
        job.cancel_requested = True
        self.log(db, job_id, "Cancellation requested", "warning")
        db.commit()
        return True

    def retry(self, db: Session, job_id: uuid.UUID) -> bool:
        job = db.get(CollectionJob, job_id)
        if job is None or job.status not in ("failed", "cancelled"):
            return False
        job.status = "queued"
        job.cancel_requested = False
        job.attempts = 0
        job.error = None
        job.progress = 0
        job.scheduled_at = datetime.now(UTC)
        job.finished_at = None
        self.log(db, job_id, "Manually retried")
        db.commit()
        return True

    def reap_stale(self, db: Session, timeout_seconds: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
        stale = db.scalars(select(CollectionJob).where(CollectionJob.status == "running",
                                                       CollectionJob.heartbeat_at < cutoff)).all()
        for job in stale:
            self.fail(db, job.id, f"Worker heartbeat lost (no heartbeat since {job.heartbeat_at:%Y-%m-%d %H:%M:%S})")
        return len(stale)
