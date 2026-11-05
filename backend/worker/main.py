"""GrowOS worker: consumes the PostgreSQL task queue and runs recurring schedules (APScheduler)."""
from __future__ import annotations

import os
import signal
import socket
import threading
import time
import traceback
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.safe_http import UnsafeURLError
from app.core.logging import configure_logging, get_logger
from app.models import Schedule
from app.queue import get_queue
from app.services.providers import ProviderNotConfigured
from app.tasks.context import JobCancelled, TaskContext
from app.tasks.registry import get_task, load_all, task_types_for_queue

settings = get_settings()
configure_logging(settings.log_level, json_output=settings.app_env != "development")
log = get_logger("worker")
load_all()
queue = get_queue()
STOP = threading.Event()
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
HEARTBEAT_FILE = os.environ.get("WORKER_HEARTBEAT_FILE", "/tmp/growos-worker-heartbeat")
# Errors caused by configuration or invalid input: retrying cannot help, fail immediately.
from app.services.usage import BudgetExceeded
NON_RETRYABLE = (ValueError, KeyError, ImportError, ProviderNotConfigured, UnsafeURLError, BudgetExceeded)


def claim_types() -> list[str] | None:
    """Task types this worker may take, or None for all of them.

    A worker whose image lacks the crawler binary must not claim a crawl: it would fail the job rather than leave
    it for the worker that can run it. Blank WORKER_QUEUE keeps the old single-worker behaviour.
    """
    name = (settings.worker_queue or "").strip()
    if not name:
        return None
    types = task_types_for_queue(name)
    if not types:
        raise SystemExit(f"WORKER_QUEUE={name!r} matches no registered task types")
    return types


CLAIM_TYPES = claim_types()


def run_one(worker_name: str) -> bool:
    Session = get_sessionmaker()
    db = Session()
    try:
        job = queue.claim(db, worker_name, CLAIM_TYPES)
        if job is None:
            return False
        log.info("job.start", job_id=str(job.id), task_type=job.task_type, attempt=job.attempts)
        ctx = TaskContext(db=db, queue=queue, job=job)
        try:
            handler = get_task(job.task_type)
            result = handler(ctx)
            queue.complete(db, job.id, result)
            log.info("job.done", job_id=str(job.id), task_type=job.task_type)
        except JobCancelled:
            db.rollback()
            queue.fail(db, job.id, "Cancelled by user", retry=False)
            log.info("job.cancelled", job_id=str(job.id))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            retry = not isinstance(exc, NON_RETRYABLE)
            queue.fail(db, job.id, f"{type(exc).__name__}: {exc}", retry=retry)
            log.error("job.failed", job_id=str(job.id), task_type=job.task_type, error=str(exc), tb=traceback.format_exc()[-2000:])
            if not retry or job.attempts >= job.max_attempts:
                _notify_job_failure(db, job, exc)
        return True
    finally:
        db.close()


def worker_loop(index: int) -> None:
    name = f"{WORKER_ID}#{index}"
    while not STOP.is_set():
        try:
            if not run_one(name):
                STOP.wait(settings.worker_poll_interval_seconds)
        except Exception as exc:  # noqa: BLE001 — e.g. DB connection hiccup
            log.error("worker.loop_error", error=str(exc))
            STOP.wait(5)


def enqueue_due_schedules() -> None:
    Session = get_sessionmaker()
    with Session() as db:
        now = datetime.now(UTC)
        due = db.scalars(select(Schedule).where(Schedule.is_enabled.is_(True), Schedule.next_run_at <= now)).all()
        for s in due:
            queue.enqueue(db, task_type=s.task_type, params=s.params, project_id=s.project_id,
                          idempotency_key=f"schedule:{s.id}:{now:%Y%m%d%H%M}", triggered_by="schedule")
            s.last_enqueued_at = now
            s.next_run_at = now + timedelta(minutes=s.interval_minutes)
            log.info("schedule.enqueued", schedule_id=str(s.id), task_type=s.task_type)
        db.commit()


def _notify_job_failure(db, job, exc) -> None:
    if job.project_id is None or job.triggered_by == "user":
        return  # user-triggered failures are visible in the UI already; alert on autonomous ones
    try:
        from app.services.notify import notify_project
        notify_project(db, job.project_id, kind="job_failed", severity="warning",
                       title=f"Scheduled task failed: {job.task_type}",
                       body=f"{type(exc).__name__}: {exc}"[:500], link="/settings",
                       dedupe_key=f"job_failed:{job.project_id}:{job.task_type}:{job.scheduled_at:%Y-%m-%d}")
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("notify.job_failure_failed", error=str(e))


def flush_emails() -> None:
    Session = get_sessionmaker()
    with Session() as db:
        from app.services.notify import flush_email_queue
        res = flush_email_queue(db)
        if res["sent"] or res["failed"]:
            log.info("email.flush", **res)


def weekly_digests() -> None:
    Session = get_sessionmaker()
    with Session() as db:
        from app.services.digest import send_weekly_digests
        log.info("digest.run", **send_weekly_digests(db))


def reap_stale_jobs() -> None:
    Session = get_sessionmaker()
    with Session() as db:
        n = queue.reap_stale(db, settings.job_heartbeat_timeout_seconds)
        if n:
            log.warning("jobs.reaped", count=n)


def main() -> None:
    log.info("worker.start", worker_id=WORKER_ID, concurrency=settings.worker_concurrency,
             queue=settings.worker_queue or "(all)", task_types=CLAIM_TYPES or "(all)")
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(enqueue_due_schedules, "interval", seconds=60, id="schedules", max_instances=1)
    scheduler.add_job(reap_stale_jobs, "interval", seconds=120, id="reaper", max_instances=1)
    scheduler.add_job(flush_emails, "interval", seconds=60, id="emails", max_instances=1)
    # Weekly digest: Mondays 08:00 UTC. The dedupe key makes a missed run catch up on the next tick without duplicating.
    scheduler.add_job(weekly_digests, "cron", day_of_week="mon", hour=8, id="digest", max_instances=1)
    scheduler.start()
    threads = [threading.Thread(target=worker_loop, args=(i,), daemon=True, name=f"worker-{i}") for i in range(settings.worker_concurrency)]
    for t in threads:
        t.start()

    def _stop(*_):
        log.info("worker.stopping")
        STOP.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    while not STOP.is_set():
        try:
            with open(HEARTBEAT_FILE, "w") as fh:  # consumed by the container health check
                fh.write(str(time.time()))
        except OSError:
            pass
        time.sleep(5)
    scheduler.shutdown(wait=False)
    for t in threads:
        t.join(timeout=30)
    log.info("worker.stopped")


if __name__ == "__main__":
    main()
