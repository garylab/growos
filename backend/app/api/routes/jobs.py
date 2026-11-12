from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_project
from app.core.db import get_db
from app.models import CollectionJob, JobLog, Project, Schedule
from app.queue import get_queue
from app.schemas.common import EnqueueIn, JobLogOut, JobOut, ScheduleIn, ScheduleOut
from app.tasks.registry import all_tasks, load_all

router = APIRouter(tags=["jobs"])
load_all()


@router.get("/tasks")
def list_task_types():
    return all_tasks()


@router.get("/projects/{project_id}/jobs", response_model=list[JobOut])
def list_jobs(project: Project = Depends(get_project), status: str | None = None, task_type: str | None = None,
              limit: int = Query(50, le=500), db: Session = Depends(get_db)):
    stmt = select(CollectionJob).where(CollectionJob.project_id == project.id).order_by(CollectionJob.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(CollectionJob.status == status)
    if task_type:
        stmt = stmt.where(CollectionJob.task_type == task_type)
    return db.scalars(stmt).all()


@router.post("/projects/{project_id}/jobs", response_model=JobOut, status_code=202)
def enqueue_job(body: EnqueueIn, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    if body.task_type not in all_tasks():
        raise HTTPException(400, f"Unknown task type {body.task_type}")
    key_parts = [body.task_type, str(project.id)] + [f"{k}={v}" for k, v in sorted(body.params.items()) if k in ("domain_id",)]
    job = get_queue().enqueue(db, task_type=body.task_type, params=body.params, project_id=project.id,
                              idempotency_key=":".join(key_parts), priority=body.priority)
    db.commit()
    db.refresh(job)
    return job


@router.get("/projects/{project_id}/jobs/catalog")
def jobs_catalog(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Jobs the user can run from the Overview dialog, tagged free/paid and filtered to what is configured."""
    from app.services.job_catalog import build_catalog
    return build_catalog(db, project)


@router.post("/projects/{project_id}/jobs/run-selected", status_code=202)
def run_selected(body: dict, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    from app.services.job_catalog import enqueue_selected
    enqueued = enqueue_selected(db, project, list(body.get("task_types") or []))
    return {"enqueued": enqueued, "count": len(enqueued)}


@router.get("/projects/{project_id}/jobs/activity")
def worker_activity(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    active = db.scalar(select(func.count()).select_from(CollectionJob).where(
        CollectionJob.project_id == project.id, CollectionJob.status.in_(["running", "queued"])))
    return {"active": active or 0}


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.get(CollectionJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/jobs/{job_id}/logs", response_model=list[JobLogOut])
def job_logs(job_id: uuid.UUID, db: Session = Depends(get_db)):
    return db.scalars(select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.id)).all()


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    if not get_queue().cancel(db, job_id):
        raise HTTPException(409, "Job is not active")
    return db.get(CollectionJob, job_id)


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    if not get_queue().retry(db, job_id):
        raise HTTPException(409, "Only failed or cancelled jobs can be retried")
    return db.get(CollectionJob, job_id)


# ------------------------------------------------------------------ schedules
@router.get("/projects/{project_id}/schedules", response_model=list[ScheduleOut])
def list_schedules(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return db.scalars(select(Schedule).where(Schedule.project_id == project.id).order_by(Schedule.created_at)).all()


@router.post("/projects/{project_id}/schedules", response_model=ScheduleOut, status_code=201)
def create_schedule(body: ScheduleIn, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    if body.task_type not in all_tasks():
        raise HTTPException(400, f"Unknown task type {body.task_type}")
    s = Schedule(project_id=project.id, task_type=body.task_type, params=body.params, interval_minutes=body.interval_minutes,
                 label=body.label, is_enabled=body.is_enabled, next_run_at=datetime.now(UTC))
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.patch("/projects/{project_id}/schedules/{schedule_id}", response_model=ScheduleOut)
def update_schedule(schedule_id: uuid.UUID, body: ScheduleIn, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    s = db.get(Schedule, schedule_id)
    if s is None or s.project_id != project.id:
        raise HTTPException(404, "Schedule not found")
    cadence_changed = s.interval_minutes != body.interval_minutes
    was_enabled = s.is_enabled
    s.task_type, s.params, s.interval_minutes, s.label, s.is_enabled = body.task_type, body.params, body.interval_minutes, body.label, body.is_enabled
    if body.is_enabled and (not was_enabled or cadence_changed):
        s.next_run_at = datetime.now(UTC) + timedelta(minutes=body.interval_minutes)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/projects/{project_id}/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: uuid.UUID, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    s = db.get(Schedule, schedule_id)
    if s is None or s.project_id != project.id:
        raise HTTPException(404, "Schedule not found")
    db.delete(s)
    db.commit()
