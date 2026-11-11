from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal, get_project
from app.core.db import get_db
from app.intelligence.playbook import complete_actions_for_item, mark_complete, plan_summary, undo_complete
from app.intelligence.scorecard import INDEX_LEVERS
from app.models.growth import plan_status_to_action
from app.models import ActionRecord, PlanItem, Project, ProjectMember, User
from app.models.plan import PLAN_STATUSES
from app.queue import get_queue
from app.schemas.common import JobOut

router = APIRouter(prefix="/projects/{project_id}/plan", tags=["plan"])


class StatusIn(BaseModel):
    status: str
    note: str | None = None


class CompleteIn(BaseModel):
    note: str | None = None


class TrackIn(BaseModel):
    title: str | None = None
    note: str | None = None


class AssignIn(BaseModel):
    user_id: uuid.UUID | None = None
    due_date: datetime | None = None


# The scorecard indexes each plan category feeds. Reverse of scorecard.INDEX_LEVERS, so a plan item can
# say which parts of the brand it moves. Labels mirror the Index(...) titles in scorecard.py.
_INDEX_LABELS = {
    "brand_influence": "Brand Influence",
    "brand_competitiveness": "Brand Competitiveness",
    "monetization": "Monetization Readiness",
}


def _affects(category: str) -> list[dict]:
    return [{"key": key, "label": _INDEX_LABELS.get(key, key)}
            for key, cats in INDEX_LEVERS.items() if category in cats]


def _out(i: PlanItem, people: dict[uuid.UUID, dict] | None = None) -> dict:
    now = datetime.now(UTC)
    assignee = (people or {}).get(i.assignee_id) if i.assignee_id else None
    return {
        "assignee_id": str(i.assignee_id) if i.assignee_id else None, "assignee": assignee, "due_date": i.due_date,
        "confidence": i.confidence, "score_breakdown": i.score_breakdown, "origin": i.origin,
        "target_urls": i.target_urls, "target_keywords": i.target_keywords, "history": i.history, "affects": _affects(i.category),"id": str(i.id), "seq": i.seq, "key": i.key, "section": i.section, "cadence": i.cadence, "category": i.category, "title": i.title, "why": i.why,
            "steps": i.steps, "suggestions": i.suggestions, "evidence": i.evidence, "impact": i.impact, "effort": i.effort, "priority": i.priority,
            "status": i.status, "completions": i.completions, "next_due_at": i.next_due_at, "last_done_at": i.last_done_at, "resolved_at": i.resolved_at,
            "source": i.source, "note": i.note, "updated_at": i.updated_at,
            "due": i.section == "routine" and i.status != "skipped" and (i.next_due_at is None or i.next_due_at <= now)}


def _people(db: Session, project_id: uuid.UUID) -> dict[uuid.UUID, dict]:
    rows = db.execute(select(User).join(ProjectMember, ProjectMember.user_id == User.id)
                      .where(ProjectMember.project_id == project_id)).scalars().all()
    return {u.id: {"id": str(u.id), "email": u.email, "name": u.name} for u in rows}


@router.get("")
def get_plan(project: Project = Depends(get_project), assignee_id: uuid.UUID | None = None,
             db: Session = Depends(get_db)):
    stmt = select(PlanItem).where(PlanItem.project_id == project.id).order_by(PlanItem.priority.desc())
    if assignee_id:
        stmt = stmt.where(PlanItem.assignee_id == assignee_id)
    items = db.scalars(stmt).all()
    people = _people(db, project.id)
    cadence_order = {"daily": 0, "weekly": 1, "monthly": 2}
    return {"summary": plan_summary(db, project.id), "members": list(people.values()),
            "setup": [_out(i, people) for i in items if i.section == "setup"],
            "business": [_out(i, people) for i in items if i.section == "business"],
            "fix": [_out(i, people) for i in items if i.section == "fix"],
            "routine": sorted((_out(i, people) for i in items if i.section == "routine"), key=lambda x: (cadence_order.get(x["cadence"], 9), -x["priority"]))}


@router.get("/listings")
def plan_listings(project: Project = Depends(get_project), audience: str | None = None, q: str | None = None,
                  type: str | None = None, db: Session = Depends(get_db)):
    """Recommended places to submit/claim a listing, matched to the project by audience. Subreddits are collapsed
    into a single expandable group. Powers the dedicated page for the "Claim your profile…" plan item."""
    from app.services.destinations import recommend_for_project
    return recommend_for_project(db, project, audience=audience, q=q, want_type=type)


@router.post("/items/{item_id}/track", status_code=201)
def track_result(item_id: uuid.UUID, body: TrackIn, project: Project = Depends(get_project),
                 db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    """Start measuring this item: creates an action carrying its target pages and keywords.

    Completing a checklist item records that you did it; this records whether it worked."""
    i = db.get(PlanItem, item_id)
    if i is None or i.project_id != project.id:
        raise HTTPException(404, "Plan item not found")
    existing = db.scalar(select(ActionRecord).where(ActionRecord.plan_item_id == i.id))
    if existing:
        return {"id": str(existing.id), "title": existing.title, "status": existing.status, "already_tracked": True}
    # Seed the action status from the plan item via the single shared mapping; tracking a not-yet-started item
    # means you are working on it now, so a "planned" result starts in progress instead.
    status = plan_status_to_action(i.status)
    if status == "planned":
        status = "in_progress"
    now = datetime.now(UTC)
    action = ActionRecord(project_id=project.id, plan_item_id=i.id, plan_item_key=i.key, title=(body.title or i.title)[:300],
                          description=i.why, status=status,
                          started_at=now if status in ("in_progress", "done") else None,
                          completed_at=now if status == "done" else None,
                          owner=(principal.user.email if principal.user else None),
                          target_urls=i.target_urls or [], target_keywords=i.target_keywords or [], notes=body.note)
    db.add(action)
    i.history = [*(i.history or []), {"at": datetime.now(UTC).isoformat(), "event": "tracking_started",
                                      "actor": principal.label}][-50:]
    db.commit()
    db.refresh(action)
    return {"id": str(action.id), "title": action.title, "status": action.status, "already_tracked": False,
            "target_urls": action.target_urls, "target_keywords": action.target_keywords}


@router.post("/items/{item_id}/assign")
def assign(item_id: uuid.UUID, body: AssignIn, project: Project = Depends(get_project), db: Session = Depends(get_db),
           principal: Principal = Depends(get_principal)):
    """Give a checklist item an owner. Admins and project owners can assign anyone; others can only claim it."""
    from app.api.deps import member_role
    i = db.get(PlanItem, item_id)
    if i is None or i.project_id != project.id:
        raise HTTPException(404, "Plan item not found")
    role = member_role(db, project.id, principal.id) if principal.id else None
    can_assign_others = principal.is_admin or role == "owner"
    if body.user_id is not None:
        if not can_assign_others and body.user_id != principal.id:
            raise HTTPException(403, "You can only assign items to yourself")
        if body.user_id not in _people(db, project.id):
            raise HTTPException(400, "That user is not a member of this brand")
    elif not can_assign_others and i.assignee_id not in (None, principal.id):
        raise HTTPException(403, "Only the assignee, an owner or an administrator can unassign this item")
    i.assignee_id = body.user_id
    i.due_date = body.due_date
    db.commit()
    db.refresh(i)
    return _out(i, _people(db, project.id))


@router.post("/generate", response_model=JobOut, status_code=202)
def generate(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    job = get_queue().enqueue(db, task_type="build_growth_plan", params={}, project_id=project.id, idempotency_key=f"build_growth_plan:{project.id}", priority=40)
    db.commit()
    db.refresh(job)
    return job


@router.post("/items/{item_id}/status")
def set_status(item_id: uuid.UUID, body: StatusIn, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    i = db.get(PlanItem, item_id)
    if i is None or i.project_id != project.id:
        raise HTTPException(404, "Plan item not found")
    if body.status not in PLAN_STATUSES:
        raise HTTPException(400, f"status must be one of {PLAN_STATUSES}")
    i.status = body.status
    if body.note is not None:
        i.note = body.note
    if body.status == "done" and i.cadence == "once":
        i.last_done_at = datetime.now(UTC)
        complete_actions_for_item(db, i)
    db.commit()
    db.refresh(i)
    return _out(i)


@router.post("/items/{item_id}/uncomplete")
def uncomplete(item_id: uuid.UUID, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Undo the last completion: drops the newest log entry and puts the item back on the list."""
    i = db.get(PlanItem, item_id)
    if i is None or i.project_id != project.id:
        raise HTTPException(404, "Plan item not found")
    if not undo_complete(i):
        raise HTTPException(400, "Nothing to undo on this item")
    db.commit()
    db.refresh(i)
    return _out(i)


@router.post("/items/{item_id}/complete")
def complete(item_id: uuid.UUID, body: CompleteIn, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Log one completion of a routine (or mark a one-time item done)."""
    i = db.get(PlanItem, item_id)
    if i is None or i.project_id != project.id:
        raise HTTPException(404, "Plan item not found")
    mark_complete(i, body.note)
    if i.status == "done":
        complete_actions_for_item(db, i)
    db.commit()
    db.refresh(i)
    return _out(i)
