"""Weekly digest: one notification per project member summarising what changed and what to do next.

Pull is how tools get forgotten; this pushes. Everything here reads existing normalized data — no new collection.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.intelligence import data as D
from app.models import BrandMention, CompetitorObservation, PlanItem, Project
from app.services.notify import notify_project


def build_digest(db: Session, project: Project) -> dict[str, Any]:
    pid = project.id
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)
    domains = D.primary_domains(db, pid)

    # search performance delta (first-party)
    search = None
    for d in domains:
        if D.gsc_available(db, d.id):
            start, end = D.gsc_window(7)
            prev = D.gsc_window(14)[0]
            cur = D.gsc_totals(db, d.id, start, end)
            was = D.gsc_totals(db, d.id, prev, start)
            search = {"clicks": cur["clicks"], "clicks_prev": was["clicks"],
                      "impressions": cur["impressions"], "impressions_prev": was["impressions"]}
            break

    # AI visibility delta
    runs = D.latest_runs(db, pid, 2)
    geo = D.visibility_summary(db, pid, runs[0]) if runs else None
    geo_prev = D.visibility_summary(db, pid, runs[1]) if len(runs) > 1 else None

    items = db.scalars(select(PlanItem).where(PlanItem.project_id == pid)).all()
    open_fix = [i for i in items if i.section in ("fix", "setup", "business") and i.status in ("todo", "in_progress")]
    due_routines = [i for i in items if i.section == "routine" and i.status != "skipped"
                    and (i.next_due_at is None or i.next_due_at <= now)]
    top = sorted(open_fix, key=lambda i: -i.priority)[:3]
    new_mentions = db.scalar(select(func.count()).select_from(BrandMention)
                             .where(BrandMention.project_id == pid, BrandMention.collected_at >= week_ago)) or 0
    comp_changes = db.scalar(select(func.count()).select_from(CompetitorObservation)
                             .where(CompetitorObservation.project_id == pid, CompetitorObservation.changed.is_(True),
                                    CompetitorObservation.observed_at >= week_ago)) or 0
    return {
        "search": search, "geo": geo, "geo_prev": geo_prev,
        "open_fixes": len(open_fix), "routines_due": len(due_routines),
        "top_to_do": [{"title": i.title, "priority": i.priority} for i in top],
        "new_mentions": int(new_mentions), "competitor_changes": int(comp_changes),
    }


def _fmt_delta(now: int, prev: int) -> str:
    if prev == 0:
        return f"{now:,}"
    pct = round(100 * (now - prev) / prev)
    arrow = "▲" if pct > 0 else "▼" if pct < 0 else "•"
    return f"{now:,} ({arrow}{abs(pct)}% WoW)"


def digest_text(project: Project, d: dict[str, Any]) -> str:
    lines = [f"Weekly growth summary for {getattr(project, 'brand_name', project.name)}", ""]
    if d["search"]:
        s = d["search"]
        lines += [f"Search clicks: {_fmt_delta(s['clicks'], s['clicks_prev'])}",
                  f"Search impressions: {_fmt_delta(s['impressions'], s['impressions_prev'])}"]
    else:
        lines.append("Search performance: Search Console not connected.")
    if d["geo"] and d["geo"]["brand_mention_rate"] is not None:
        cur = d["geo"]["brand_mention_rate"]
        prev = d["geo_prev"]["brand_mention_rate"] if d["geo_prev"] else None
        delta = f" (was {prev:.0%})" if prev is not None else ""
        lines.append(f"AI mention rate: {cur:.0%}{delta}")
    lines += ["", f"{d['open_fixes']} things to fix · {d['routines_due']} routines due this week"]
    if d["new_mentions"] or d["competitor_changes"]:
        lines.append(f"{d['new_mentions']} new brand mentions · {d['competitor_changes']} competitor page changes")
    if d["top_to_do"]:
        lines += ["", "Top priorities:"] + [f"  {i+1}. {t['title']}" for i, t in enumerate(d["top_to_do"])]
    return "\n".join(lines)


def send_weekly_digests(db: Session) -> dict[str, int]:
    projects = db.scalars(select(Project)).all()
    sent = 0
    for p in projects:
        if (p.settings or {}).get("digest_enabled") is False:
            continue
        d = build_digest(db, p)
        body = digest_text(p, d)
        made = notify_project(db, p.id, kind="digest", severity="info", title=f"Weekly summary — {p.name}",
                              body=body, link="/", data=d,
                              dedupe_key=f"digest:{p.id}:{datetime.now(UTC):%Y-W%V}")
        sent += made
    db.commit()
    return {"projects": len(projects), "notifications": sent}
