"""Make a new project productive without manual setup: seed sensible recurring schedules."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Domain, Schedule

# (task_type, interval_minutes, needs a primary domain?). These are the cadence the roadmap recommends.
DEFAULT_SCHEDULES = [
    ("sync_search_console", 1440, True),      # daily
    ("sync_bing_webmaster", 1440, True),      # daily, on a par with Search Console rather than manual-only
    ("sync_analytics", 1440, True),           # daily
    ("crawl_domain", 10080, True),            # weekly
    ("measure_performance", 10080, True),     # weekly
    ("watch_competitor_pages", 10080, False), # weekly
    ("monitor_brand_mentions", 1440, False),  # daily
    ("run_ai_visibility", 10080, False),      # weekly
    ("build_growth_plan", 10080, False),      # weekly (after the week's data lands)
    ("snapshot_scorecard", 1440, False),      # daily, so the scorecard trend lines fill in
]


def seed_default_schedules(db: Session, project_id: uuid.UUID) -> int:
    """Create the standard recurring jobs for a project. Idempotent per (task_type, domain)."""
    existing = {(s.task_type, (s.params or {}).get("domain_id")) for s in
                db.scalars(select(Schedule).where(Schedule.project_id == project_id)).all()}
    domains = db.scalars(select(Domain).where(Domain.project_id == project_id, Domain.role == "primary",
                                              Domain.is_active.is_(True))).all()
    now = datetime.now(UTC)
    made = 0
    for i, (task, interval, per_domain) in enumerate(DEFAULT_SCHEDULES):
        targets = domains if per_domain else [None]
        for d in targets:
            did = str(d.id) if d else None
            if (task, did) in existing:
                continue
            db.add(Schedule(project_id=project_id, task_type=task, params={"domain_id": did} if did else {},
                            interval_minutes=interval, is_enabled=True,
                            # Stagger first runs so a new project does not fire everything at once.
                            next_run_at=now + timedelta(minutes=2 * (i + 1)),
                            label=f"{task} (auto)"))
            made += 1
    return made
