from __future__ import annotations

import uuid
from typing import Any

from app.models import ContentDraft, PlanItem, Project
from app.services.content_studio import generate
from app.tasks.context import TaskContext
from app.services.usage import BudgetExceeded, check_budget
from app.tasks.registry import task


@task("generate_content", "Write an article, social post or video script for a checklist topic")
def generate_content(ctx: TaskContext) -> dict[str, Any]:
    project = ctx.db.get(Project, ctx.project_id)
    if project is None:
        raise ValueError("Brand not found")
    check_budget(ctx.db, project)
    p = ctx.params
    plan_item = ctx.db.get(PlanItem, uuid.UUID(p["plan_item_id"])) if p.get("plan_item_id") else None
    ctx.progress(20, f"Writing: {p['topic'][:60]}")
    result = generate(ctx.db, project, kind=p["kind"], topic=p["topic"], channel=p.get("channel", "blog"),
                      plan_item=plan_item, notes=p.get("notes"), provider_key=p.get("provider_key"), job_id=ctx.job.id)
    draft = ContentDraft(project_id=project.id, plan_item_id=plan_item.id if plan_item else None, kind=p["kind"],
                         channel=p.get("channel", "blog"), topic=p["topic"], title=result["title"], body=result["body"],
                         assets=result["assets"], evidence=result["evidence"], provider_key=result["provider_key"],
                         model=result["model"], created_by=uuid.UUID(p["created_by"]) if p.get("created_by") else None)
    ctx.db.add(draft)
    ctx.db.commit()
    ctx.db.refresh(draft)
    ctx.save_artifact(result["provider_key"], "content_draft", {"context": result["context"], "assets": result["assets"]})
    return {"draft_id": str(draft.id), "kind": draft.kind, "channel": draft.channel, "title": draft.title,
            "provider": draft.provider_key, "model": draft.model, "words": len((draft.body or "").split())}
