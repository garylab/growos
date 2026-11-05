"""Outcome measurement: compare target metrics before vs after an action using first-party/observed data."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import uuid

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from app.intelligence import data as D
from app.models import ActionRecord, AIAnswerObservation, OutcomeMeasurement, SearchObservation


def measure_action(db: Session, action: ActionRecord, window_days: int = 28) -> list[OutcomeMeasurement]:
    """Baseline = window before the action started; comparison = most recent window after it started/completed."""
    anchor = (action.completed_at or action.started_at or action.created_at).date()
    base_end = anchor - timedelta(days=1)
    base_start = base_end - timedelta(days=window_days - 1)
    cmp_end = date.today() - timedelta(days=3)
    cmp_start = max(anchor, cmp_end - timedelta(days=window_days - 1))
    out: list[OutcomeMeasurement] = []
    if cmp_end < cmp_start:
        return out
    # Search Console for target urls/keywords
    domains = D.primary_domains(db, action.project_id)
    for metric in ("clicks", "impressions", "ctr", "position"):
        b = _gsc_metric(db, domains, action, metric, base_start, base_end)
        c = _gsc_metric(db, domains, action, metric, cmp_start, cmp_end)
        if b is None and c is None:
            continue
        out.append(_measurement(action, f"gsc_{metric}", "google_search_console", "first_party", b, c, base_start, base_end, cmp_start, cmp_end,
                                {"target_urls": action.target_urls, "target_keywords": action.target_keywords}))
    # First-party analytics for the target pages (sessions → conversions is where revenue actually shows up)
    for metric in ("sessions", "conversions", "conversion_rate", "revenue"):
        b = _analytics_metric(db, domains, action, metric, base_start, base_end)
        c = _analytics_metric(db, domains, action, metric, cmp_start, cmp_end)
        if b is None and c is None:
            continue
        out.append(_measurement(action, f"ga_{metric}", "analytics", "first_party", b, c, base_start, base_end, cmp_start, cmp_end,
                                {"target_urls": action.target_urls}))

    # AI brand mention rate for target prompts (or all prompts)
    b = _ai_rate(db, action, base_start, base_end)
    c = _ai_rate(db, action, cmp_start, cmp_end)
    if b is not None or c is not None:
        out.append(_measurement(action, "ai_brand_mention_rate", "ai_visibility", "observed", b, c, base_start, base_end, cmp_start, cmp_end,
                                {"target_prompt_ids": action.target_prompt_ids}))
    for m in out:
        db.add(m)
    db.commit()
    return out


def _gsc_metric(db: Session, domains, action: ActionRecord, metric: str, start: date, end: date) -> float | None:
    if not domains:
        return None
    filters = [SearchObservation.domain_id.in_([d.id for d in domains]), SearchObservation.date >= start, SearchObservation.date <= end,
               SearchObservation.country == "", SearchObservation.device == ""]
    if action.target_urls:
        filters += [SearchObservation.page.in_(action.target_urls), SearchObservation.query == ""]
    elif action.target_keywords:
        filters += [SearchObservation.query.in_(action.target_keywords), SearchObservation.page != ""]
    else:
        filters += [SearchObservation.query == "", SearchObservation.page != ""]
    r = db.execute(select(func.sum(SearchObservation.clicks), func.sum(SearchObservation.impressions),
                          func.sum(SearchObservation.position * SearchObservation.impressions)).where(*filters)).one()
    clicks, imps, pos = int(r[0] or 0), int(r[1] or 0), float(r[2] or 0)
    if imps == 0 and clicks == 0:
        return None
    return {"clicks": clicks, "impressions": imps, "ctr": clicks / imps if imps else 0, "position": pos / imps if imps else 0}[metric]


def _analytics_metric(db: Session, domains, action: ActionRecord, metric: str, start: date, end: date) -> float | None:
    """Sessions / conversions / conversion rate / revenue for the action's target pages (or the whole site)."""
    if not domains:
        return None
    totals = {"sessions": 0, "conversions": 0, "revenue": 0.0}
    found = False
    for d in domains:
        t = D.analytics_totals(db, d.id, start, end, action.target_urls or None)
        if t["has_data"]:
            found = True
        totals["sessions"] += t["sessions"]
        totals["conversions"] += t["conversions"]
        totals["revenue"] += t["revenue"]
    if not found:
        return None
    if metric == "conversion_rate":
        return (totals["conversions"] / totals["sessions"]) if totals["sessions"] else 0.0
    return totals[metric]


def _ai_rate(db: Session, action: ActionRecord, start: date, end: date) -> float | None:
    filters = [AIAnswerObservation.project_id == action.project_id, AIAnswerObservation.error.is_(None),
               AIAnswerObservation.observed_at >= datetime.combine(start, datetime.min.time(), tzinfo=UTC),
               AIAnswerObservation.observed_at <= datetime.combine(end, datetime.max.time(), tzinfo=UTC)]
    if action.target_prompt_ids:
        filters.append(AIAnswerObservation.prompt_id.in_([uuid.UUID(p) for p in action.target_prompt_ids]))
    r = db.execute(select(func.count(), func.sum(func.cast(AIAnswerObservation.brand_mentioned, Integer))).where(*filters)).one()
    n = int(r[0] or 0)
    return (int(r[1] or 0) / n) if n else None


def _measurement(action: ActionRecord, key: str, source: str, mtype: str, b: float | None, c: float | None,
                 bs: date, be: date, cs: date, ce: date, details: dict[str, Any]) -> OutcomeMeasurement:
    delta = (c - b) if (b is not None and c is not None) else None
    pct = (delta / b * 100) if (delta is not None and b) else None
    return OutcomeMeasurement(action_id=action.id, project_id=action.project_id, metric_key=key, source=source, measurement_type=mtype,
                              baseline_period={"start": bs.isoformat(), "end": be.isoformat()},
                              comparison_period={"start": cs.isoformat(), "end": ce.isoformat()},
                              baseline_value=b, current_value=c, delta=delta, delta_pct=round(pct, 2) if pct is not None else None, details=details)
