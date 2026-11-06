from __future__ import annotations

from typing import Any

from app.intelligence.analyst import run_analysis
from app.models import Project
from app.tasks.context import TaskContext
from app.services.usage import BudgetExceeded, check_budget
from app.tasks.registry import task


@task("ai_analysis", "Let the AI analyst review normalized data and record evidence-backed opportunities")
def ai_analysis(ctx: TaskContext) -> dict[str, Any]:
    project = ctx.db.get(Project, ctx.project_id)
    if project is None:
        raise ValueError("Brand not found")
    check_budget(ctx.db, project)
    result = run_analysis(ctx.db, project, focus=ctx.params.get("focus"), job_id=ctx.job.id, on_progress=ctx.progress)
    ctx.save_artifact(result["provider"], "ai_analysis_transcript", result["transcript"])
    result.pop("transcript", None)
    return result
