from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import CollectionJob

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/health/worker")
def worker_health(db: Session = Depends(get_db)) -> dict:
    """Reports whether a worker has claimed any job recently (heartbeat within 15 minutes) and queue depth."""
    from datetime import UTC, datetime, timedelta
    from sqlalchemy import func
    recent = datetime.now(UTC) - timedelta(minutes=15)
    last_hb = db.scalar(select(func.max(CollectionJob.heartbeat_at)))
    queued = db.scalar(select(func.count()).select_from(CollectionJob).where(CollectionJob.status == "queued")) or 0
    running = db.scalar(select(func.count()).select_from(CollectionJob).where(CollectionJob.status == "running")) or 0
    return {"last_heartbeat_at": last_hb, "worker_seen_recently": bool(last_hb and last_hb >= recent), "queued": queued, "running": running}
