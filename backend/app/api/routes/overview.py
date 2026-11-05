from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_project
from app.core.db import get_db
from app.intelligence import data as D
from datetime import date, timedelta

from app.models import ActionRecord, AnalyticsEvent, BrandMention, CollectionJob, OutcomeMeasurement, PlanItem, Project, ProviderConnection
from app.services.providers import list_connections_for

router = APIRouter(prefix="/projects/{project_id}/overview", tags=["overview"])


@router.get("")
def overview(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    domains = D.primary_domains(db, project.id)
    # --- SEO
    seo = []
    for d in domains:
        run = D.latest_crawl_run(db, d.id)
        start, end = D.gsc_window(28)
        prev_start = D.gsc_window(56)[0]
        gsc = D.gsc_available(db, d.id)
        seo.append({"domain_id": str(d.id), "hostname": d.hostname, "gsc_property": d.gsc_property,
                    "crawl": {"run_id": str(run.id), "finished_at": run.finished_at, "overall_score": (run.quality_scores.get("overall") or {}).get("score"),
                              "categories": {c["code"]: c["score"] for c in run.quality_scores.get("categories", [])},
                              "findings_count": run.findings_count, "html_pages": run.html_pages, "total_urls": run.total_urls} if run else None,
                    "search": {"available": True, "totals": D.gsc_totals(db, d.id, start, end), "previous": D.gsc_totals(db, d.id, prev_start, start),
                               "daily": D.gsc_daily(db, d.id, 90)} if gsc else {"available": False},
                    "analytics": _analytics_block(db, d.id)})
    # --- GEO
    runs = D.latest_runs(db, project.id, 2)
    geo = {"current": D.visibility_summary(db, project.id, runs[0]) if runs else None,
           "previous": D.visibility_summary(db, project.id, runs[1]) if len(runs) > 1 else None,
           "runs_history": [D.visibility_summary(db, project.id, r) for r in D.latest_runs(db, project.id, 12)],
           "ai_traffic": (D.ai_referral_traffic(db, domains[0].id, 28) if domains else {"available": False})}
    # --- Brand
    mention_rows = db.execute(select(BrandMention.entity_type, BrandMention.sentiment, func.count()).where(BrandMention.project_id == project.id)
                              .group_by(BrandMention.entity_type, BrandMention.sentiment)).all()
    brand = {"mentions": {f"{t}_{s}": n for t, s, n in mention_rows}, "total": sum(n for _, _, n in mention_rows),
             "with_intent": db.scalar(select(func.count()).select_from(BrandMention).where(BrandMention.project_id == project.id, BrandMention.intent != "none")) or 0}
    # --- Opportunities & actions
    opps = db.scalars(select(PlanItem).where(PlanItem.project_id == project.id, PlanItem.section != "routine",
                                             PlanItem.status.in_(("todo", "in_progress")))
                      .order_by(desc(PlanItem.priority)).limit(7)).all()
    opp_counts = dict(db.execute(select(PlanItem.status, func.count()).where(PlanItem.project_id == project.id).group_by(PlanItem.status)).all())
    actions = db.scalars(select(ActionRecord).where(ActionRecord.project_id == project.id).order_by(desc(ActionRecord.updated_at)).limit(5)).all()
    action_counts = dict(db.execute(select(ActionRecord.status, func.count()).where(ActionRecord.project_id == project.id).group_by(ActionRecord.status)).all())
    outcomes = db.scalars(select(OutcomeMeasurement).where(OutcomeMeasurement.project_id == project.id).order_by(desc(OutcomeMeasurement.measured_at)).limit(10)).all()
    # --- Integrations / jobs
    conns = [c for c in db.scalars(select(ProviderConnection)).all() if c.project_id in (None, project.id)]
    ai_conns = list_connections_for(db, project.id, "ai")
    recent_jobs = db.scalars(select(CollectionJob).where(CollectionJob.project_id == project.id).order_by(desc(CollectionJob.created_at)).limit(8)).all()
    return {
        "project": {"id": str(project.id), "name": project.name, "brand_name": project.brand_name},
        "seo": seo, "geo": geo, "brand": brand,
        "opportunities": {"counts": opp_counts, "top": [{"id": str(o.id), "title": o.title, "module": o.category,
                                                           "priority_score": o.priority, "impact_score": o.impact,
                                                           "confidence": o.confidence, "effort": o.effort,
                                                           "recommended_action": (o.steps or [""])[0], "status": o.status} for o in opps]},
        "actions": {"counts": action_counts, "recent": [{"id": str(a.id), "title": a.title, "status": a.status, "updated_at": a.updated_at} for a in actions],
                    "outcomes": [{"action_id": str(o.action_id), "metric_key": o.metric_key, "baseline_value": o.baseline_value, "current_value": o.current_value,
                                  "delta_pct": o.delta_pct, "measured_at": o.measured_at} for o in outcomes]},
        "integrations": {"configured": [{"provider_key": c.provider_key, "status": c.status, "category": c.category} for c in conns],
                         "ai_providers": [c.provider_key for c in ai_conns],
                         "search_console": any(c.provider_key == "google_search_console" and c.status == "healthy" for c in conns)},
        "recent_jobs": [{"id": str(j.id), "task_type": j.task_type, "status": j.status, "progress": j.progress, "created_at": j.created_at,
                         "finished_at": j.finished_at, "error": j.error} for j in recent_jobs],
    }


def _analytics_block(db: Session, domain_id) -> dict:
    today = date.today()
    def totals(start: date, end: date) -> dict:
        r = db.execute(select(func.sum(AnalyticsEvent.sessions), func.sum(AnalyticsEvent.conversions), func.sum(AnalyticsEvent.revenue),
                              func.sum(AnalyticsEvent.engaged_sessions), func.sum(AnalyticsEvent.engagement_time_sec))
                       .where(AnalyticsEvent.domain_id == domain_id, AnalyticsEvent.date >= start, AnalyticsEvent.date < end)).one()
        s, c = int(r[0] or 0), int(r[1] or 0)
        return {"sessions": s, "conversions": c, "revenue": float(r[2] or 0), "conversion_rate": (c / s) if s else 0.0,
                # GA4's "average engagement time per session".
                "avg_engagement_seconds": (float(r[4] or 0) / s) if s else 0.0,
                "engagement_rate": (int(r[3] or 0) / s) if s else 0.0}
    cur = totals(today - timedelta(days=28), today)
    if cur["sessions"] == 0 and not db.scalar(select(func.count()).select_from(AnalyticsEvent).where(AnalyticsEvent.domain_id == domain_id)):
        return {"available": False}
    return {"available": True, "totals": cur, "previous": totals(today - timedelta(days=56), today - timedelta(days=28))}
