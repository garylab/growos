"""Read-only queries over normalized data, shared by the rule engine, the AI analyst tools and the API."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.models import (AIAnswerMention, AIAnswerObservation, AnalyticsEvent, AuditFinding, BrandMention, Competitor,
                        CompetitorObservation, CrawlRun, Domain, Keyword, PageSnapshot, PerformanceObservation,
                        PromptDefinition, SearchObservation)


def primary_domains(db: Session, project_id: uuid.UUID) -> list[Domain]:
    return db.scalars(select(Domain).where(Domain.project_id == project_id, Domain.role == "primary", Domain.is_active.is_(True))).all()


def latest_crawl_run(db: Session, domain_id: uuid.UUID) -> CrawlRun | None:
    return db.scalar(select(CrawlRun).where(CrawlRun.domain_id == domain_id, CrawlRun.finished_at.isnot(None))
                     .order_by(desc(CrawlRun.finished_at)).limit(1))


def crawl_findings(db: Session, run_id: uuid.UUID, severities: tuple[str, ...] = ("critical", "warning")) -> list[AuditFinding]:
    return db.scalars(select(AuditFinding).where(AuditFinding.crawl_run_id == run_id, AuditFinding.severity.in_(severities))).all()


def gsc_window(days: int = 28) -> tuple[date, date]:
    end = date.today()
    return end - timedelta(days=days + 3), end


def gsc_available(db: Session, domain_id: uuid.UUID) -> bool:
    return db.scalar(select(func.count()).select_from(SearchObservation).where(SearchObservation.domain_id == domain_id)) > 0


def gsc_query_page_rows(db: Session, domain_id: uuid.UUID, days: int = 28, min_impressions: int = 1, limit: int = 2000) -> list[dict[str, Any]]:
    """Aggregated query × page rows over a window (first-party)."""
    start, end = gsc_window(days)
    q = (select(SearchObservation.query, SearchObservation.page, func.sum(SearchObservation.clicks).label("clicks"),
                func.sum(SearchObservation.impressions).label("impressions"),
                (func.sum(SearchObservation.position * SearchObservation.impressions) / func.nullif(func.sum(SearchObservation.impressions), 0)).label("position"),
                func.array_agg(SearchObservation.id).label("ids"))
         .where(SearchObservation.domain_id == domain_id, SearchObservation.date >= start, SearchObservation.date <= end,
                SearchObservation.query != "", SearchObservation.page != "", SearchObservation.country == "", SearchObservation.device == "")
         .group_by(SearchObservation.query, SearchObservation.page)
         .having(func.sum(SearchObservation.impressions) >= min_impressions)
         .order_by(desc("impressions")).limit(limit))
    out = []
    for r in db.execute(q):
        imp = int(r.impressions or 0)
        out.append({"query": r.query, "page": r.page, "clicks": int(r.clicks or 0), "impressions": imp,
                    "ctr": (int(r.clicks or 0) / imp) if imp else 0.0, "position": float(r.position or 0),
                    "ids": [str(i) for i in (r.ids or [])][:20]})
    return out


def gsc_totals(db: Session, domain_id: uuid.UUID, start: date, end: date) -> dict[str, Any]:
    r = db.execute(select(func.sum(SearchObservation.clicks), func.sum(SearchObservation.impressions),
                          func.sum(SearchObservation.position * SearchObservation.impressions) / func.nullif(func.sum(SearchObservation.impressions), 0))
                   .where(SearchObservation.domain_id == domain_id, SearchObservation.date >= start, SearchObservation.date <= end,
                          SearchObservation.query == "", SearchObservation.page != "", SearchObservation.country == "", SearchObservation.device == "")).one()
    clicks, imps, pos = int(r[0] or 0), int(r[1] or 0), float(r[2] or 0)
    return {"clicks": clicks, "impressions": imps, "ctr": (clicks / imps) if imps else 0.0, "position": round(pos, 2),
            "start": start.isoformat(), "end": end.isoformat()}


def gsc_daily(db: Session, domain_id: uuid.UUID, days: int = 90) -> list[dict[str, Any]]:
    start, end = gsc_window(days)
    q = (select(SearchObservation.date, func.sum(SearchObservation.clicks), func.sum(SearchObservation.impressions),
                func.sum(SearchObservation.position * SearchObservation.impressions) / func.nullif(func.sum(SearchObservation.impressions), 0))
         .where(SearchObservation.domain_id == domain_id, SearchObservation.date >= start, SearchObservation.date <= end,
                SearchObservation.query == "", SearchObservation.page != "", SearchObservation.country == "", SearchObservation.device == "")
         .group_by(SearchObservation.date).order_by(SearchObservation.date))
    return [{"date": r[0].isoformat(), "clicks": int(r[1] or 0), "impressions": int(r[2] or 0),
             "ctr": round((int(r[1] or 0) / int(r[2])) if r[2] else 0, 4), "position": round(float(r[3] or 0), 2)} for r in db.execute(q)]


def gsc_top_pages(db: Session, domain_id: uuid.UUID, days: int = 28, limit: int = 20) -> list[dict[str, Any]]:
    start, end = gsc_window(days)
    q = (select(SearchObservation.page, func.sum(SearchObservation.clicks), func.sum(SearchObservation.impressions),
                func.sum(SearchObservation.position * SearchObservation.impressions) / func.nullif(func.sum(SearchObservation.impressions), 0))
         .where(SearchObservation.domain_id == domain_id, SearchObservation.date >= start, SearchObservation.date <= end,
                SearchObservation.query == "", SearchObservation.page != "", SearchObservation.country == "", SearchObservation.device == "")
         .group_by(SearchObservation.page).order_by(desc(func.sum(SearchObservation.clicks))).limit(limit))
    return [{"page": r[0], "clicks": int(r[1] or 0), "impressions": int(r[2] or 0),
             "ctr": round((int(r[1] or 0) / int(r[2])) if r[2] else 0, 4), "position": round(float(r[3] or 0), 2)} for r in db.execute(q)]


def gsc_top_queries(db: Session, domain_id: uuid.UUID, days: int = 28, limit: int = 50) -> list[dict[str, Any]]:
    start, end = gsc_window(days)
    q = (select(SearchObservation.query, func.sum(SearchObservation.clicks), func.sum(SearchObservation.impressions),
                func.sum(SearchObservation.position * SearchObservation.impressions) / func.nullif(func.sum(SearchObservation.impressions), 0))
         .where(SearchObservation.domain_id == domain_id, SearchObservation.date >= start, SearchObservation.date <= end,
                SearchObservation.query != "", SearchObservation.page == "", SearchObservation.country != "")
         .group_by(SearchObservation.query).order_by(desc(func.sum(SearchObservation.impressions))).limit(limit))
    return [{"query": r[0], "clicks": int(r[1] or 0), "impressions": int(r[2] or 0),
             "ctr": round((int(r[1] or 0) / int(r[2])) if r[2] else 0, 4), "position": round(float(r[3] or 0), 2)} for r in db.execute(q)]


# ------------------------------------------------------------------ GEO
def latest_runs(db: Session, project_id: uuid.UUID, n: int = 2) -> list[uuid.UUID]:
    q = (select(AIAnswerObservation.run_id, func.max(AIAnswerObservation.observed_at).label("t"))
         .where(AIAnswerObservation.project_id == project_id).group_by(AIAnswerObservation.run_id).order_by(desc("t")).limit(n))
    return [r[0] for r in db.execute(q)]


def visibility_by_prompt(db: Session, project_id: uuid.UUID, run_id: uuid.UUID) -> list[dict[str, Any]]:
    """Per prompt × provider: samples, brand mention rate, avg position, competitor mention rates, citations."""
    obs = db.scalars(select(AIAnswerObservation).where(AIAnswerObservation.project_id == project_id,
                                                       AIAnswerObservation.run_id == run_id, AIAnswerObservation.error.is_(None))).all()
    prompts = {p.id: p for p in db.scalars(select(PromptDefinition).where(PromptDefinition.project_id == project_id)).all()}
    obs_ids = [o.id for o in obs]
    mentions = db.scalars(select(AIAnswerMention).where(AIAnswerMention.observation_id.in_(obs_ids))).all() if obs_ids else []
    by_obs: dict[uuid.UUID, list[AIAnswerMention]] = {}
    for m in mentions:
        by_obs.setdefault(m.observation_id, []).append(m)
    groups: dict[tuple[uuid.UUID, str], list[AIAnswerObservation]] = {}
    for o in obs:
        groups.setdefault((o.prompt_id, o.provider_key), []).append(o)
    out = []
    for (pid, provider), items in groups.items():
        p = prompts.get(pid)
        n = len(items)
        # A scraped surface can legitimately show no answer at all — Google runs no AI Overview for plenty of
        # queries. That is a measurement, not a failure, but it is not the same as "answered and ignored us", so
        # the two are reported side by side rather than averaged into one rate. Model APIs always answer, so for
        # them `answered` equals `samples` and nothing below changes.
        answered = [o for o in items if (o.answer_text or "").strip()]
        brand_hits = [o for o in items if o.brand_mentioned]
        comp_counts: dict[str, int] = {}
        comp_positions: dict[str, list[int]] = {}
        cited: dict[str, int] = {}
        for o in items:
            for m in by_obs.get(o.id, []):
                if m.entity_type == "competitor":
                    comp_counts[m.entity_name] = comp_counts.get(m.entity_name, 0) + 1
                    if m.position:
                        comp_positions.setdefault(m.entity_name, []).append(m.position)
            for c in o.citations or []:
                if c.get("domain"):
                    cited[c["domain"]] = cited.get(c["domain"], 0) + 1
        out.append({
            "prompt_id": str(pid), "prompt": p.text if p else "", "intent": p.intent if p else None, "topic": p.topic if p else None,
            "provider": provider, "samples": n, "grounded_samples": sum(1 for o in items if o.grounded),
            "answer_shown": len(answered),
            "brand_mention_rate": round(len(brand_hits) / n, 3) if n else 0,
            "brand_mention_rate_when_shown": round(sum(1 for o in answered if o.brand_mentioned) / len(answered), 3) if answered else None,
            "brand_avg_position": round(sum(o.brand_position for o in brand_hits if o.brand_position) / len(brand_hits), 2) if brand_hits and any(o.brand_position for o in brand_hits) else None,
            "own_domain_cited_rate": round(sum(1 for o in items if o.own_domain_cited) / n, 3) if n else 0,
            "competitors": {k: {"rate": round(v / n, 3), "avg_position": round(sum(comp_positions.get(k, [0])) / max(1, len(comp_positions.get(k, []))), 2) if comp_positions.get(k) else None}
                            for k, v in comp_counts.items()},
            "top_cited_domains": sorted(cited.items(), key=lambda kv: -kv[1])[:8],
            "observation_ids": [str(o.id) for o in items],
            "models": sorted({o.model for o in items}),
        })
    return out


def visibility_summary(db: Session, project_id: uuid.UUID, run_id: uuid.UUID | None) -> dict[str, Any]:
    if run_id is None:
        return {"run_id": None, "samples": 0, "brand_mention_rate": None, "competitors": {}, "providers": []}
    rows = visibility_by_prompt(db, project_id, run_id)
    n = sum(r["samples"] for r in rows)
    brand = sum(r["brand_mention_rate"] * r["samples"] for r in rows)
    comps: dict[str, float] = {}
    for r in rows:
        for name, v in r["competitors"].items():
            comps[name] = comps.get(name, 0) + v["rate"] * r["samples"]
    own_cited = sum(r["own_domain_cited_rate"] * r["samples"] for r in rows)
    shown = sum(r["answer_shown"] for r in rows)
    observed_at = db.scalar(select(func.max(AIAnswerObservation.observed_at)).where(AIAnswerObservation.run_id == run_id))
    return {"run_id": str(run_id), "observed_at": observed_at.isoformat() if observed_at else None, "samples": n,
            "prompts": len({r["prompt_id"] for r in rows}), "providers": sorted({r["provider"] for r in rows}),
            "brand_mention_rate": round(brand / n, 3) if n else None,
            "answer_shown_rate": round(shown / n, 3) if n else None,
            "own_domain_cited_rate": round(own_cited / n, 3) if n else None,
            "competitors": {k: round(v / n, 3) for k, v in sorted(comps.items(), key=lambda kv: -kv[1])} if n else {}}


# ------------------------------------------------------------------ brand / competitor / analytics
def recent_mentions(db: Session, project_id: uuid.UUID, days: int = 30, limit: int = 500) -> list[BrandMention]:
    since = datetime.now(UTC) - timedelta(days=days)
    return db.scalars(select(BrandMention).where(BrandMention.project_id == project_id, BrandMention.collected_at >= since)
                      .order_by(desc(BrandMention.published_at)).limit(limit)).all()


def recent_competitor_changes(db: Session, project_id: uuid.UUID, days: int = 30) -> list[CompetitorObservation]:
    since = datetime.now(UTC) - timedelta(days=days)
    return db.scalars(select(CompetitorObservation).where(CompetitorObservation.project_id == project_id,
                                                          CompetitorObservation.changed.is_(True),
                                                          CompetitorObservation.observed_at >= since)
                      .order_by(desc(CompetitorObservation.observed_at))).all()


def gsc_hosts(db: Session, domain_id: uuid.UUID, days: int = 90) -> list[dict[str, Any]]:
    """Distinct hosts appearing in Search Console page URLs (catches staging/subdomain leaks)."""
    start, end = gsc_window(days)
    rows = db.execute(select(SearchObservation.page, func.sum(SearchObservation.clicks), func.sum(SearchObservation.impressions))
                      .where(SearchObservation.domain_id == domain_id, SearchObservation.date >= start, SearchObservation.date <= end,
                             SearchObservation.page != "").group_by(SearchObservation.page)).all()
    hosts: dict[str, dict[str, Any]] = {}
    for page, clicks, imps in rows:
        from urllib.parse import urlsplit
        host = (urlsplit(page).hostname or "").lower()
        if not host:
            continue
        h = hosts.setdefault(host, {"host": host, "pages": 0, "clicks": 0, "impressions": 0, "examples": []})
        h["pages"] += 1
        h["clicks"] += int(clicks or 0)
        h["impressions"] += int(imps or 0)
        if len(h["examples"]) < 3:
            h["examples"].append(page)
    return sorted(hosts.values(), key=lambda x: -x["impressions"])


def gsc_pages(db: Session, domain_id: uuid.UUID, days: int = 90) -> list[dict[str, Any]]:
    """Every page with impressions in the window (not just the top N)."""
    start, end = gsc_window(days)
    rows = db.execute(select(SearchObservation.page, func.sum(SearchObservation.clicks), func.sum(SearchObservation.impressions))
                      .where(SearchObservation.domain_id == domain_id, SearchObservation.date >= start, SearchObservation.date <= end,
                             SearchObservation.page != "").group_by(SearchObservation.page)).all()
    return [{"page": p, "clicks": int(c or 0), "impressions": int(i or 0)} for p, c, i in rows]


# Referrer domains that identify an AI assistant sending traffic. GA4 also labels some of these with the
# "ai-assistant" medium; we accept either signal.
AI_REFERRAL_SOURCES: dict[str, str] = {
    "chatgpt.com": "ChatGPT", "chat.openai.com": "ChatGPT", "openai.com": "ChatGPT",
    "perplexity.ai": "Perplexity", "www.perplexity.ai": "Perplexity",
    "gemini.google.com": "Gemini", "bard.google.com": "Gemini",
    "copilot.microsoft.com": "Microsoft Copilot", "edgeservices.bing.com": "Microsoft Copilot",
    "claude.ai": "Claude", "you.com": "You.com", "poe.com": "Poe", "phind.com": "Phind",
    "meta.ai": "Meta AI", "grok.com": "Grok", "x.ai": "Grok", "deepseek.com": "DeepSeek",
    "chat.mistral.ai": "Mistral", "kagi.com": "Kagi", "andisearch.com": "Andi",
}
AI_MEDIUMS = ("ai-assistant", "ai_assistant", "ai")


def classify_ai_referral(source: str, medium: str) -> str | None:
    """Return the assistant name when a session came from an AI assistant, else None."""
    src = (source or "").lower().strip().removeprefix("www.")
    if src in AI_REFERRAL_SOURCES:
        return AI_REFERRAL_SOURCES[src]
    for host, name in AI_REFERRAL_SOURCES.items():
        if src.endswith("." + host.removeprefix("www.")):
            return name
    if (medium or "").lower().strip() in AI_MEDIUMS and src:
        return src  # unknown assistant, but GA4 says it is one
    return None


def ai_referral_traffic(db: Session, domain_id: uuid.UUID, days: int = 28) -> dict[str, Any]:
    """Sessions that AI assistants sent to the site — the downstream half of AI visibility."""
    today = date.today()
    start, prev_start = today - timedelta(days=days), today - timedelta(days=days * 2)
    rows = db.execute(select(AnalyticsEvent.date, AnalyticsEvent.source, AnalyticsEvent.medium, AnalyticsEvent.landing_page,
                             func.sum(AnalyticsEvent.sessions), func.sum(AnalyticsEvent.conversions), func.sum(AnalyticsEvent.revenue))
                      .where(AnalyticsEvent.domain_id == domain_id, AnalyticsEvent.date >= prev_start)
                      .group_by(AnalyticsEvent.date, AnalyticsEvent.source, AnalyticsEvent.medium, AnalyticsEvent.landing_page)).all()
    if not rows:
        return {"available": False, "reason": "No analytics data yet — connect Google Analytics 4 or import a CSV."}
    cur_total = prev_total = 0
    by_assistant: dict[str, dict[str, Any]] = {}
    daily: dict[str, int] = {}
    pages: dict[str, dict[str, Any]] = {}
    cur_ai = prev_ai = 0
    cur_conv = 0
    for d, source, medium, landing, sessions, conversions, revenue in rows:
        sessions, conversions, revenue = int(sessions or 0), int(conversions or 0), float(revenue or 0)
        current = d >= start
        if current:
            cur_total += sessions
        else:
            prev_total += sessions
        name = classify_ai_referral(source, medium)
        if not name:
            continue
        if current:
            cur_ai += sessions
            cur_conv += conversions
            a = by_assistant.setdefault(name, {"assistant": name, "sessions": 0, "conversions": 0, "revenue": 0.0, "sources": set()})
            a["sessions"] += sessions
            a["conversions"] += conversions
            a["revenue"] += revenue
            a["sources"].add(source or "(direct)")
            daily[d.isoformat()] = daily.get(d.isoformat(), 0) + sessions
            p = pages.setdefault(landing, {"landing_page": landing, "sessions": 0, "conversions": 0})
            p["sessions"] += sessions
            p["conversions"] += conversions
        else:
            prev_ai += sessions
    return {
        "available": True, "days": days,
        "sessions": cur_ai, "previous_sessions": prev_ai, "conversions": cur_conv,
        "total_sessions": cur_total, "previous_total_sessions": prev_total,
        "share_of_sessions": round(cur_ai / cur_total, 4) if cur_total else 0.0,
        "by_assistant": sorted(({**a, "sources": sorted(a["sources"])} for a in by_assistant.values()), key=lambda a: -a["sessions"]),
        "daily": [{"date": k, "sessions": v} for k, v in sorted(daily.items())],
        "landing_pages": sorted(pages.values(), key=lambda p: -p["sessions"])[:25],
        "definitions": {"source": "GA4 session source/medium classified against known AI assistant referrers",
                        "caveat": "Assistants that strip the referrer (or in-app browsers) under-report; treat this as a floor, not a total."},
    }


def analytics_totals(db: Session, domain_id: uuid.UUID, start: date, end: date, landing_pages: list[str] | None = None) -> dict[str, Any]:
    q = select(func.sum(AnalyticsEvent.sessions), func.sum(AnalyticsEvent.users), func.sum(AnalyticsEvent.conversions),
               func.sum(AnalyticsEvent.revenue)).where(AnalyticsEvent.domain_id == domain_id, AnalyticsEvent.date >= start,
                                                       AnalyticsEvent.date <= end)
    if landing_pages:
        q = q.where(AnalyticsEvent.landing_page.in_(landing_pages))
    r = db.execute(q).one()
    sessions, users, conv, rev = int(r[0] or 0), int(r[1] or 0), int(r[2] or 0), float(r[3] or 0)
    return {"sessions": sessions, "users": users, "conversions": conv, "revenue": rev,
            "conversion_rate": (conv / sessions) if sessions else 0.0, "has_data": sessions > 0 or conv > 0}


def analytics_landing_pages(db: Session, domain_id: uuid.UUID, days: int = 28) -> list[dict[str, Any]]:
    start = date.today() - timedelta(days=days)
    q = (select(AnalyticsEvent.landing_page, func.sum(AnalyticsEvent.sessions), func.sum(AnalyticsEvent.conversions), func.array_agg(AnalyticsEvent.id))
         .where(AnalyticsEvent.domain_id == domain_id, AnalyticsEvent.date >= start)
         .group_by(AnalyticsEvent.landing_page).order_by(desc(func.sum(AnalyticsEvent.sessions))).limit(200))
    return [{"landing_page": r[0], "sessions": int(r[1] or 0), "conversions": int(r[2] or 0),
             "conversion_rate": (int(r[2] or 0) / int(r[1])) if r[1] else 0.0, "ids": [str(i) for i in (r[3] or [])][:20]} for r in db.execute(q)]


def latest_performance(db: Session, domain_id: uuid.UUID) -> list[PerformanceObservation]:
    sub = (select(PerformanceObservation.url, PerformanceObservation.strategy, PerformanceObservation.measurement_type,
                  func.max(PerformanceObservation.observed_at).label("t"))
           .where(PerformanceObservation.domain_id == domain_id)
           .group_by(PerformanceObservation.url, PerformanceObservation.strategy, PerformanceObservation.measurement_type).subquery())
    q = select(PerformanceObservation).join(sub, and_(PerformanceObservation.url == sub.c.url, PerformanceObservation.strategy == sub.c.strategy,
                                                    PerformanceObservation.measurement_type == sub.c.measurement_type,
                                                    PerformanceObservation.observed_at == sub.c.t))
    return db.scalars(q).all()


def target_keywords(db: Session, project_id: uuid.UUID) -> list[Keyword]:
    return db.scalars(select(Keyword).where(Keyword.project_id == project_id, Keyword.is_target.is_(True))).all()


def competitors(db: Session, project_id: uuid.UUID) -> list[Competitor]:
    return db.scalars(select(Competitor).where(Competitor.project_id == project_id)).all()


def html_pages(db: Session, run_id: uuid.UUID) -> list[PageSnapshot]:
    return db.scalars(select(PageSnapshot).where(PageSnapshot.crawl_run_id == run_id, PageSnapshot.content_type == "html",
                                                 PageSnapshot.status_code == 200)).all()


