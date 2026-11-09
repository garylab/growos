from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import desc, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.deps import get_domain, get_project
from app.core.db import get_db
from app.models import ActionRecord, AnalyticsEvent, Domain, OutcomeMeasurement, PlanItem, Project
from app.models.growth import ACTION_STATUSES
from app.schemas.growth import ActionIn, ActionOut, ActionUpdate, OutcomeOut
from app.services.outcomes import measure_action

# This router is the "Results" feature in the UI (menu item "Results", route /results). The model is named
# ActionRecord and the API path is /actions for historical reasons; the two names refer to the same thing.
router = APIRouter(prefix="/projects/{project_id}", tags=["actions"])


def _plan_items_for(db: Session, project_id, actions: list[ActionRecord]) -> dict:
    """Resolve each action's current plan item, by id and — if the id was orphaned by a plan regeneration — by the
    stored plan_item_key. Returns {action_id: PlanItem}. This keeps a tracked result pointing at the live plan item
    even after the playbook rebuilds the plan, and lets the result read its target pages/keywords from one source."""
    ids = {a.plan_item_id for a in actions if a.plan_item_id}
    keys = {a.plan_item_key for a in actions if a.plan_item_key}
    if not ids and not keys:
        return {}
    conds = []
    if ids:
        conds.append(PlanItem.id.in_(ids))
    if keys:
        conds.append(PlanItem.key.in_(keys))
    items = db.scalars(select(PlanItem).where(PlanItem.project_id == project_id, or_(*conds))).all()
    by_id = {i.id: i for i in items}
    by_key = {i.key: i for i in items}
    out = {}
    for a in actions:
        pi = (by_id.get(a.plan_item_id) if a.plan_item_id else None) or (by_key.get(a.plan_item_key) if a.plan_item_key else None)
        if pi is not None:
            out[a.id] = pi
    return out


@router.get("/actions", response_model=list[ActionOut])
def list_actions(project: Project = Depends(get_project), status: str | None = None, db: Session = Depends(get_db)):
    stmt = select(ActionRecord).where(ActionRecord.project_id == project.id).order_by(desc(ActionRecord.created_at))
    if status:
        stmt = stmt.where(ActionRecord.status == status)
    actions = list(db.scalars(stmt).all())
    plan = _plan_items_for(db, project.id, actions)
    # A linked result reads its target pages/keywords from the live plan item (single source of truth), so they
    # cannot drift from the plan; the stored snapshot is only the fallback for manual or orphaned results.
    out = []
    for a in actions:
        view = ActionOut.model_validate(a)
        pi = plan.get(a.id)
        if pi is not None:
            view.plan_item_id = pi.id
            view.target_urls = pi.target_urls
            view.target_keywords = pi.target_keywords
        out.append(view)
    return out


@router.get("/actions/linked")
def linked_plan_items(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Which checklist items already have a tracked result, so the plan can show it. Resolves by plan_item_id, and
    by plan_item_key when a regeneration orphaned the id, so the 'measuring' badge survives a plan rebuild."""
    actions = list(db.scalars(select(ActionRecord).where(
        ActionRecord.project_id == project.id,
        or_(ActionRecord.plan_item_id.isnot(None), ActionRecord.plan_item_key.isnot(None)))).all())
    plan = _plan_items_for(db, project.id, actions)
    out = {}
    for a in actions:
        pi = plan.get(a.id)
        if pi is not None:
            out[str(pi.id)] = {"action_id": str(a.id), "status": a.status}
    return out


@router.post("/actions", response_model=ActionOut, status_code=201)
def create_action(body: ActionIn, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    if body.status not in ACTION_STATUSES:
        raise HTTPException(400, f"status must be one of {ACTION_STATUSES}")
    a = ActionRecord(project_id=project.id, **body.model_dump())
    if a.plan_item_id:  # record the stable key so the link survives plan regeneration
        pi = db.get(PlanItem, a.plan_item_id)
        if pi is not None and pi.project_id == project.id:
            a.plan_item_key = pi.key
    if a.status == "in_progress":
        a.started_at = datetime.now(UTC)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.patch("/actions/{action_id}", response_model=ActionOut)
def update_action(action_id: uuid.UUID, body: ActionUpdate, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    a = db.get(ActionRecord, action_id)
    if a is None or a.project_id != project.id:
        raise HTTPException(404, "Action not found")
    data = body.model_dump(exclude_unset=True)
    if "status" in data:
        if data["status"] not in ACTION_STATUSES:
            raise HTTPException(400, f"status must be one of {ACTION_STATUSES}")
        if data["status"] == "in_progress" and not a.started_at:
            a.started_at = datetime.now(UTC)
        if data["status"] == "done" and not a.completed_at:
            a.completed_at = datetime.now(UTC)
    for k, v in data.items():
        setattr(a, k, v)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/actions/{action_id}", status_code=204)
def delete_action(action_id: uuid.UUID, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    a = db.get(ActionRecord, action_id)
    if a is None or a.project_id != project.id:
        raise HTTPException(404, "Action not found")
    db.delete(a)
    db.commit()


@router.post("/actions/{action_id}/measure", response_model=list[OutcomeOut])
def measure(action_id: uuid.UUID, window_days: int = Query(28, ge=7, le=90), project: Project = Depends(get_project), db: Session = Depends(get_db)):
    a = db.get(ActionRecord, action_id)
    if a is None or a.project_id != project.id:
        raise HTTPException(404, "Action not found")
    # Measure against the live plan item's targets when linked, and refresh the stored snapshot so it stays current.
    pi = _plan_items_for(db, project.id, [a]).get(a.id)
    if pi is not None:
        a.target_urls, a.target_keywords = pi.target_urls, pi.target_keywords
    return measure_action(db, a, window_days)


@router.get("/actions/{action_id}/outcomes", response_model=list[OutcomeOut])
def outcomes(action_id: uuid.UUID, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return db.scalars(select(OutcomeMeasurement).where(OutcomeMeasurement.action_id == action_id).order_by(desc(OutcomeMeasurement.measured_at))).all()


@router.post("/domains/{domain_id}/analytics/import")
async def import_analytics(domain: Domain = Depends(get_domain), file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import daily landing-page analytics as CSV with columns: date, landing_page, sessions, conversions[, users, revenue, source, medium]."""
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    required = {"date", "landing_page", "sessions"}
    if not reader.fieldnames or not required.issubset({f.strip().lower() for f in reader.fieldnames}):
        raise HTTPException(400, f"CSV must contain columns {sorted(required)}")
    rows = []
    for r in reader:
        r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
        try:
            rows.append({"project_id": domain.project_id, "domain_id": domain.id, "provider_key": "csv_import",
                         "date": date.fromisoformat(r["date"][:10]), "landing_page": r["landing_page"][:2000],
                         "source": r.get("source", "")[:120], "medium": r.get("medium", "")[:120],
                         "sessions": int(float(r.get("sessions") or 0)), "users": int(float(r.get("users") or 0)),
                         "conversions": int(float(r.get("conversions") or 0)), "revenue": float(r.get("revenue") or 0),
                         "engaged_sessions": int(float(r.get("engaged_sessions") or 0)),
                         "engagement_time_sec": float(r.get("engagement_time_sec") or 0)})
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, f"Bad row {r}: {exc}") from exc
    if not rows:
        raise HTTPException(400, "No rows found")
    for i in range(0, len(rows), 500):
        stmt = insert(AnalyticsEvent).values(rows[i:i + 500])
        stmt = stmt.on_conflict_do_update(constraint="uq_analytics_event", set_={"sessions": stmt.excluded.sessions, "users": stmt.excluded.users,
                                                                                "conversions": stmt.excluded.conversions, "revenue": stmt.excluded.revenue,
                                                                                "engaged_sessions": stmt.excluded.engaged_sessions,
                                                                                "engagement_time_sec": stmt.excluded.engagement_time_sec,
                                                                                "collected_at": stmt.excluded.collected_at})
        db.execute(stmt)
    db.commit()
    return {"imported": len(rows)}


@router.get("/domains/{domain_id}/analytics")
def analytics_summary(domain: Domain = Depends(get_domain), days: int = Query(28, ge=7, le=365), db: Session = Depends(get_db)):
    """First-party analytics per landing page (GA4 sync or CSV import) with totals and previous-period comparison."""
    from datetime import timedelta
    from sqlalchemy import func
    from app.intelligence import data as D
    start = date.today() - timedelta(days=days)
    prev_start = start - timedelta(days=days)
    base = select(func.sum(AnalyticsEvent.sessions), func.sum(AnalyticsEvent.users), func.sum(AnalyticsEvent.conversions),
                  func.sum(AnalyticsEvent.revenue), func.sum(AnalyticsEvent.engaged_sessions),
                  func.sum(AnalyticsEvent.engagement_time_sec)).where(AnalyticsEvent.domain_id == domain.id)
    cur = db.execute(base.where(AnalyticsEvent.date >= start)).one()
    prev = db.execute(base.where(AnalyticsEvent.date >= prev_start, AnalyticsEvent.date < start)).one()
    tot = lambda r: {"sessions": int(r[0] or 0), "users": int(r[1] or 0), "conversions": int(r[2] or 0), "revenue": float(r[3] or 0),  # noqa: E731
                     "conversion_rate": (int(r[2] or 0) / int(r[0])) if r[0] else 0.0,
                     "engaged_sessions": int(r[4] or 0),
                     # GA4's "average engagement time per session": total engaged seconds / sessions.
                     "avg_engagement_seconds": (float(r[5] or 0) / int(r[0])) if r[0] else 0.0,
                     "engagement_rate": (int(r[4] or 0) / int(r[0])) if r[0] else 0.0}
    last = db.execute(select(func.max(AnalyticsEvent.collected_at), func.min(AnalyticsEvent.date), func.max(AnalyticsEvent.date),
                             func.array_agg(func.distinct(AnalyticsEvent.provider_key))).where(AnalyticsEvent.domain_id == domain.id)).one()
    if not last[0]:
        return {"available": False, "ga4_property": domain.ga4_property, "reason": "No analytics data yet — connect Google Analytics 4 and sync, or import a CSV."}
    daily = db.execute(select(AnalyticsEvent.date, func.sum(AnalyticsEvent.sessions), func.sum(AnalyticsEvent.conversions))
                       .where(AnalyticsEvent.domain_id == domain.id, AnalyticsEvent.date >= start).group_by(AnalyticsEvent.date).order_by(AnalyticsEvent.date)).all()
    sources = db.execute(select(AnalyticsEvent.source, AnalyticsEvent.medium, func.sum(AnalyticsEvent.sessions), func.sum(AnalyticsEvent.conversions))
                         .where(AnalyticsEvent.domain_id == domain.id, AnalyticsEvent.date >= start).group_by(AnalyticsEvent.source, AnalyticsEvent.medium)
                         .order_by(desc(func.sum(AnalyticsEvent.sessions))).limit(25)).all()
    return {"available": True, "ga4_property": domain.ga4_property, "last_sync": last[0], "data_range": {"start": last[1], "end": last[2]},
            "providers": list(last[3] or []), "totals": tot(cur), "previous": tot(prev),
            "daily": [{"date": d.isoformat(), "sessions": int(s or 0), "conversions": int(c or 0)} for d, s, c in daily],
            "landing_pages": [{k: v for k, v in r.items() if k != "ids"} for r in D.analytics_landing_pages(db, domain.id, days)],
            "sources": [{"source": s or "(direct)", "medium": m or "(none)", "sessions": int(ss or 0), "conversions": int(c or 0)} for s, m, ss, c in sources],
            "definitions": {"sessions": "GA4 sessions by landing page (first-party)", "conversions": "GA4 key events (or legacy conversions)",
                            "conversion_rate": "conversions / sessions", "revenue": "GA4 totalRevenue",
                            "avg_engagement_seconds": "GA4 userEngagementDuration / sessions — average engagement time per session",
                            "engagement_rate": "GA4 engagedSessions / sessions"}}
