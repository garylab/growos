"""Re-measure outcomes for a project's active actions against the latest first-party data.

Outcome measurement was previously only ever triggered on demand (the action page's "Measure" button), so the
results never refreshed when the daily Search Console / analytics syncs brought in new data. This task re-runs the
same measurement for every active action, and is scheduled daily so the results page stays current on its own.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models import ActionRecord, PlanItem
from app.services.outcomes import measure_action
from app.tasks.context import TaskContext
from app.tasks.registry import task


@task("measure_outcomes", "Re-measure outcomes for active actions against the latest data")
def measure_outcomes(ctx: TaskContext) -> dict[str, Any]:
    actions = ctx.db.scalars(select(ActionRecord).where(
        ActionRecord.project_id == ctx.project_id,
        ActionRecord.status.in_(("in_progress", "done")))).all()
    measured = 0
    for a in actions:
        # Keep the action's targets in step with its plan item, as the on-demand endpoint does, so a measurement
        # always reflects the item's current target pages/keywords rather than a stale snapshot.
        if a.plan_item_id:
            pi = ctx.db.get(PlanItem, a.plan_item_id)
            if pi is not None:
                a.target_urls, a.target_keywords = pi.target_urls, pi.target_keywords
        measure_action(ctx.db, a)   # commits its own measurements
        measured += 1
    ctx.db.commit()
    return {"actions_measured": measured}
