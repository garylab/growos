from __future__ import annotations

from typing import Any

from app.intelligence.scorecard import build_scorecard
from app.models import Project
from app.tasks.context import TaskContext
from app.tasks.registry import task


@task("snapshot_scorecard", "Record today's brand scorecard so the trend lines keep filling")
def snapshot_scorecard(ctx: TaskContext) -> dict[str, Any]:
    project = ctx.db.get(Project, ctx.project_id)
    if project is None:
        raise ValueError("Brand not found")
    card = build_scorecard(ctx.db, project)  # build_scorecard records the daily snapshot as a side effect
    return {"overall": card["overall"]["score"], "indices": {i["key"]: i["score"] for i in card["indices"]}}
