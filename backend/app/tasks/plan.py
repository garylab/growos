from __future__ import annotations

from typing import Any

from app.intelligence.playbook import sync_plan
from app.models import Project
from app.tasks.context import TaskContext
from app.tasks.registry import task


@task("build_growth_plan", "Rebuild the Growth Plan checklist from the latest data")
def build_growth_plan(ctx: TaskContext) -> dict[str, Any]:
    project = ctx.db.get(Project, ctx.project_id)
    if project is None:
        raise ValueError("Brand not found")
    ctx.progress(20, "Reading the latest crawl, search, AI and analytics data")
    plan = sync_plan(ctx.db, project)
    ctx.progress(100, "Checklist rebuilt")
    return plan
