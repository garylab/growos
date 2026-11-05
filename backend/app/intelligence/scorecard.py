"""Brand scorecard: three transparent 0-100 indices plus a revenue model.

Design rules, consistent with the rest of the product:
- Every component states its raw value, its data source and how it was normalised.
- A component with no data is *excluded*, never guessed. Weights of the remaining components are renormalised and the
  card reports `coverage` (how much of the intended model had data) so a high score on thin data is visible as such.
- The money figures are a **model**, not a measurement. They depend on inputs the user supplies (average order value,
  assumed conversion rate, valuation multiple) and are labelled as such everywhere.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.intelligence import data as D
from app.intelligence.scoring import expected_ctr
from app.models import (AnalyticsEvent, CollectionJob, PageSnapshot, PlanItem, Project, RankedKeyword,
                        ReferringDomain, ScorecardSnapshot, SearchObservation)

# Defaults used only when the user has not set project economics. Shown in the UI as assumptions.
# An index built on less than this share of its model is not published as a number: a single component scoring 100
# must never look like an "A". The UI shows what to collect instead.
MIN_COVERAGE = 0.5

# The overall score is a geometric mean, not an average: a weak dimension drags the whole down, because in reality the
# dimensions multiply (no awareness x great conversion = no revenue). If a scored dimension is genuinely 0, the overall
# is 0 — that is the honest answer, not a bug.
def overall_score(scores: list[float]) -> float | None:
    if not scores:
        return None
    prod = 1.0
    for v in scores:
        prod *= min(100.0, max(0.0, v))
    return round(prod ** (1 / len(scores)), 1)

DEFAULT_ECONOMICS = {
    "currency": "USD",
    "average_order_value": None,     # must be supplied for money figures
    "assumed_conversion_rate": 0.02,  # used only when analytics shows no conversions
    "revenue_multiple_low": 3.0,      # indicative SaaS revenue multiples
    "revenue_multiple_high": 6.0,
    "gross_margin": 0.8,
}


# ----------------------------------------------------------------------- normalisation helpers
def saturate(value: float, half: float) -> float:
    """0-100 curve that never exceeds 100; `half` is the value that scores 50."""
    if value <= 0 or half <= 0:
        return 0.0
    # Capped below 100: a saturating signal should never award a perfect score, however large it gets.
    return min(99.9, round(100 * value / (value + half), 1))


def ratio_score(value: float, target: float) -> float:
    """Linear 0-100 where reaching `target` scores 100."""
    if target <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100 * value / target)), 1)


def trend_score(current: float, previous: float, full_swing: float = 0.5) -> float:
    """50 = flat. A relative change of ±full_swing maps to 100 / 0."""
    if previous <= 0:
        return 65.0 if current > 0 else 50.0  # new signal where there was none
    change = (current - previous) / previous
    return round(max(0.0, min(100.0, 50 + 50 * change / full_swing)), 1)


def position_score(position: float) -> float:
    """Average search position → 0-100 (1st ≈ 100, 20th ≈ 0)."""
    if position <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100 * (21 - position) / 20)), 1)


@dataclass
class Component:
    key: str
    label: str
    weight: float
    score: float | None          # None = no data, excluded from the index
    raw: Any = None
    unit: str = ""
    source: str = ""
    formula: str = ""
    note: str = ""

    @property
    def available(self) -> bool:
        return self.score is not None


@dataclass
class Index:
    key: str
    label: str
    question: str
    components: list[Component] = field(default_factory=list)

    def result(self) -> dict[str, Any]:
        usable = [c for c in self.components if c.available]
        total_w = sum(c.weight for c in self.components)
        used_w = sum(c.weight for c in usable)
        raw_score = round(sum((c.score or 0) * c.weight for c in usable) / used_w, 1) if used_w else None
        coverage = round(used_w / total_w, 2) if total_w else 0.0
        enough = coverage >= MIN_COVERAGE and raw_score is not None
        score = raw_score if enough else None
        return {
            "key": self.key, "label": self.label, "question": self.question,
            "score": score, "grade": grade(score), "coverage": coverage,
            "insufficient_data": not enough,
            "provisional_score": raw_score if not enough else None,
            "insufficient_reason": (None if enough else
                                    f"Only {int(coverage * 100)}% of this index has data (at least "
                                    f"{int(MIN_COVERAGE * 100)}% is required). Collect the missing inputs below "
                                    "before reading a score."),
            "confidence": "high" if coverage >= 0.8 else "medium" if coverage >= 0.5 else "low",
            "formula": "Weighted mean of the components that have data; their weights are renormalised to sum to 1.",
            "components": [{"key": c.key, "label": c.label, "weight": round(c.weight / total_w, 3),
                            "weight_used": round(c.weight / used_w, 3) if c.available and used_w else 0.0,
                            "score": c.score, "raw": c.raw, "unit": c.unit, "source": c.source,
                            "formula": c.formula, "note": c.note, "available": c.available}
                           for c in self.components],
            "missing": [c.label for c in self.components if not c.available],
        }


# Which Growth Plan categories move each index. Used to link a score directly to the work that raises it.
INDEX_LEVERS = {
    "brand_influence": ("brand", "ai_visibility", "business", "content"),
    "brand_competitiveness": ("competitors", "ai_visibility", "content", "website"),
    "monetization": ("conversion", "content", "website"),
}


def grade(score: float | None) -> str:
    if score is None:
        return "n/a"
    for cut, g in ((85, "A"), (70, "B"), (55, "C"), (40, "D")):
        if score >= cut:
            return g
    return "E"


# ----------------------------------------------------------------------- data gathering
def _facts(db: Session, project: Project) -> dict[str, Any]:
    f: dict[str, Any] = {"domains": D.primary_domains(db, project.id)}
    domain = f["domains"][0] if f["domains"] else None
    f["domain"] = domain
    if domain is None:
        return f
    f["gsc"] = D.gsc_available(db, domain.id)
    if f["gsc"]:
        start, end = D.gsc_window(28)
        prev_start = D.gsc_window(56)[0]
        f["totals"] = D.gsc_totals(db, domain.id, start, end)
        f["totals_prev"] = D.gsc_totals(db, domain.id, prev_start, start)
        rows = D.gsc_query_page_rows(db, domain.id, 28, 1, 3000)
        terms = [project.brand_name.lower(), *[a.lower() for a in (project.brand_aliases or [])]]
        branded_idx = {n for n, r in enumerate(rows) if any(t and t in r["query"].lower() for t in terms)}
        branded = [r for n, r in enumerate(rows) if n in branded_idx]
        nonbranded = [r for n, r in enumerate(rows) if n not in branded_idx]
        f["branded"] = {"clicks": sum(r["clicks"] for r in branded), "impressions": sum(r["impressions"] for r in branded)}
        f["nonbranded"] = {"clicks": sum(r["clicks"] for r in nonbranded), "impressions": sum(r["impressions"] for r in nonbranded)}
        f["top10_share"] = (len([r for r in rows if 0 < r["position"] <= 10]) / len(rows)) if rows else None
        f["rows"] = rows
        # branded trend needs the previous window too
        prev_rows = _branded_prev(db, domain.id, terms, prev_start, start)
        f["branded_prev"] = prev_rows
    f["run"] = D.latest_crawl_run(db, domain.id)
    f["perf"] = [o for o in D.latest_performance(db, domain.id) if o.measurement_type == "lab"]
    runs = D.latest_runs(db, project.id, 2)
    f["geo"] = D.visibility_summary(db, project.id, runs[0]) if runs else None
    f["geo_prev"] = D.visibility_summary(db, project.id, runs[1]) if len(runs) > 1 else None
    today = date.today()
    f["analytics"] = D.analytics_totals(db, domain.id, today - timedelta(days=28), today)
    f["analytics_prev"] = D.analytics_totals(db, domain.id, today - timedelta(days=56), today - timedelta(days=28))
    f["ai_traffic"] = D.ai_referral_traffic(db, domain.id, 28)
    f["direct"] = _direct_sessions(db, domain.id, today - timedelta(days=28), today)
    f["mentions"] = D.recent_mentions(db, project.id, 30, 500)
    # Distinguish "we looked and found nothing" from "we never looked" — a zero is only meaningful after a run.
    f["mentions_collected"] = bool(db.scalar(
        select(func.count()).select_from(CollectionJob)
        .where(CollectionJob.project_id == project.id, CollectionJob.task_type == "monitor_brand_mentions",
               CollectionJob.status == "succeeded")))
    f["plan"] = db.scalars(select(PlanItem).where(PlanItem.project_id == project.id)).all()
    f["signals"] = _signals(db, f["run"]) if f["run"] else {}
    f["backlinks"] = _backlinks(db, domain.id) if domain else None
    f["keyword_gap"] = _keyword_gap(db, project.id)
    f["keywords"] = D.target_keywords(db, project.id)
    f["competitors"] = D.competitors(db, project.id)
    return f


def _branded_prev(db: Session, domain_id: uuid.UUID, terms: list[str], start: date, end: date) -> dict[str, int]:
    rows = db.execute(select(SearchObservation.query, func.sum(SearchObservation.clicks), func.sum(SearchObservation.impressions))
                      .where(SearchObservation.domain_id == domain_id, SearchObservation.date >= start, SearchObservation.date < end,
                             SearchObservation.query != "", SearchObservation.page != "", SearchObservation.country == "",
                             SearchObservation.device == "").group_by(SearchObservation.query)).all()
    clicks = imps = 0
    for q, c, i in rows:
        if any(t and t in (q or "").lower() for t in terms):
            clicks += int(c or 0)
            imps += int(i or 0)
    return {"clicks": clicks, "impressions": imps}


def _backlinks(db: Session, domain_id: uuid.UUID) -> dict[str, Any] | None:
    """Latest referring-domain snapshot for the domain, plus the previous one so the trend can be scored."""
    days = db.scalars(select(ReferringDomain.observed_on).where(ReferringDomain.domain_id == domain_id)
                      .group_by(ReferringDomain.observed_on).order_by(desc(ReferringDomain.observed_on)).limit(2)).all()
    if not days:
        return None

    def snapshot(day):
        n, links, follow = db.execute(
            select(func.count(), func.sum(ReferringDomain.backlinks), func.sum(ReferringDomain.dofollow))
            .where(ReferringDomain.domain_id == domain_id, ReferringDomain.observed_on == day)).one()
        return {"referring_domains": int(n or 0), "backlinks": int(links or 0), "dofollow": int(follow or 0)}

    cur = snapshot(days[0])
    cur["observed_on"] = days[0].isoformat()
    cur["previous"] = snapshot(days[1])["referring_domains"] if len(days) > 1 else None
    cur["provider"] = db.scalar(select(ReferringDomain.provider_key)
                                .where(ReferringDomain.domain_id == domain_id,
                                       ReferringDomain.observed_on == days[0]).limit(1))
    return cur


def _keyword_gap(db: Session, project_id: uuid.UUID) -> dict[str, Any] | None:
    """Share of the keywords competitors rank for that we also rank for, weighted by search volume."""
    latest = db.scalar(select(RankedKeyword.observed_on).where(RankedKeyword.project_id == project_id)
                       .order_by(desc(RankedKeyword.observed_on)).limit(1))
    if latest is None:
        return None
    rows = db.scalars(select(RankedKeyword).where(RankedKeyword.project_id == project_id,
                                                  RankedKeyword.observed_on == latest)).all()
    mine = {r.keyword for r in rows if r.is_own}
    theirs = {r.keyword for r in rows if not r.is_own}
    if not theirs:
        return None
    volume = {}
    for r in rows:
        volume[r.keyword] = max(volume.get(r.keyword) or 0, r.search_volume or 0)
    contested = theirs
    overlap = contested & mine
    their_volume = sum(volume.get(k, 0) for k in contested) or 1
    return {"observed_on": latest.isoformat(),
            "competitor_keywords": len(contested), "you_also_rank": len(overlap), "gaps": len(contested - mine),
            "gap_volume": sum(volume.get(k, 0) for k in contested - mine),
            "coverage": len(overlap) / len(contested),
            "volume_coverage": sum(volume.get(k, 0) for k in overlap) / their_volume,
            "hosts": sorted({r.host for r in rows if not r.is_own})}


def _direct_sessions(db: Session, domain_id: uuid.UUID, start: date, end: date) -> int:
    return int(db.scalar(select(func.sum(AnalyticsEvent.sessions)).where(
        AnalyticsEvent.domain_id == domain_id, AnalyticsEvent.date >= start, AnalyticsEvent.date <= end,
        AnalyticsEvent.source.in_(("", "(direct)", "direct")))) or 0)


def _signals(db: Session, run) -> dict[str, Any]:
    page = db.scalar(select(PageSnapshot).where(PageSnapshot.crawl_run_id == run.id, PageSnapshot.path == "/"))
    sig = (page.signals or {}) if page else {}
    return sig if sig.get("checked") else {}


# ----------------------------------------------------------------------- the three indices
def brand_influence(project: Project, f: dict[str, Any]) -> Index:
    """How well known is the brand? Awareness-side signals only."""
    idx = Index("brand_influence", "Brand Influence", "Do people and machines already know this brand?")
    br = f.get("branded")
    idx.components.append(Component(
        "branded_demand", "Branded search demand", 0.30,
        saturate(br["impressions"], 800) if br else None, br["impressions"] if br else None, "impressions / 28d",
        "Google Search Console", "saturate(branded impressions, half=800)",
        "How many people search for your name is the classic proxy for awareness. 800 impressions scores 50." if br else ""))
    idx.components.append(Component(
        "branded_trend", "Branded demand trend", 0.12,
        trend_score(br["impressions"], f["branded_prev"]["impressions"]) if br and f.get("branded_prev") else None,
        {"now": br["impressions"], "previous": f["branded_prev"]["impressions"]} if br and f.get("branded_prev") else None,
        "impressions", "Google Search Console", "50 + 50 x change / 0.5 (50 = flat)",
        "Whether awareness is rising or falling matters more than its absolute level."))
    an, ai = f.get("analytics"), f.get("ai_traffic") or {}
    if an and an["sessions"]:
        own = (f.get("direct") or 0) + (ai.get("sessions") or 0)
        share = own / an["sessions"]
        note = "People who arrive without searching a generic term already know the brand."
        if share > 0.6:
            note += (" Caution: a direct share of {:.0%} usually means incomplete source tracking — email, in-app "
                     "clicks and QR codes all land in 'direct', so this component may be overstated.".format(share))
        idx.components.append(Component(
            "unprompted_traffic", "Direct & AI-assistant visits", 0.18,
            ratio_score(share, 0.40), {"share": round(share, 4), "direct": f.get("direct"), "ai": ai.get("sessions")},
            "share of sessions", "Analytics", "(direct + AI-assistant sessions) / all sessions, 40% scores 100", note))
    else:
        idx.components.append(Component("unprompted_traffic", "Direct & AI-assistant visits", 0.18, None,
                                        None, "share of sessions", "Analytics",
                                        "(direct + AI-assistant sessions) / all sessions"))
    ms = [m for m in f.get("mentions", []) if m.entity_type == "brand"]
    pos = sum(1 for m in ms if m.sentiment == "positive")
    neg = sum(1 for m in ms if m.sentiment == "negative")
    tone = 1.0 + 0.3 * ((pos - neg) / len(ms)) if ms else 1.0
    idx.components.append(Component(
        "public_mentions", "Public mentions", 0.12,
        round(min(100.0, saturate(len(ms), 15) * tone), 1) if f.get("mentions_collected") else None,
        {"count": len(ms), "positive": pos, "negative": neg}, "mentions / 30d", "Hacker News, Bluesky, RSS",
        "saturate(mentions, half=15) x sentiment factor (0.7-1.3)",
        "Counts only the sources you have connected, so it is a floor rather than the true web-wide volume."))
    bl = f.get("backlinks")
    idx.components.append(Component(
        "referring_domains", "Referring domains", 0.15,
        # 150 referring domains scores 50; a growing profile is worth up to a 15% bonus, capped at 100.
        round(min(100.0, saturate(bl["referring_domains"], 150) * _refdom_trend(bl)), 1) if bl else None,
        bl, "domains", _backlink_source(f),
        "saturate(referring domains, half=150) x growth factor (0.85-1.15)",
        "Distinct sites linking to you, as your connected backlink index sees it. Indexes disagree, so compare this "
        "against your own history rather than against a competitor's number from another tool." if bl else
        "Connect a backlink provider under Integrations to score this."))
    sig = f.get("signals") or {}
    if sig:
        have = [bool(sig.get("has_logo")), bool(sig.get("has_organization_schema")), bool(sig.get("social_links")),
                bool(sig.get("og_title") and sig.get("og_image")), bool(sig.get("own_domain_emails"))]
        idx.components.append(Component(
            "brand_assets", "Brand identity completeness", 0.15,
            round(100 * sum(have) / len(have), 1), {"logo": have[0], "schema": have[1], "social": have[2],
                                                    "link_preview": have[3], "own_domain_email": have[4]},
            "checks passed", "Page signals", "checks passed / 5 x 100",
            "Logo, Organization structured data, social profiles, link-preview tags, email on your own domain."))
    else:
        idx.components.append(Component("brand_assets", "Brand identity completeness", 0.15, None,
                                        None, "checks passed", "Page signals", "checks passed / 5 x 100"))
    return idx


def _refdom_trend(bl: dict[str, Any]) -> float:
    """Growth factor from the previous snapshot: 1.0 when flat or unknown, 0.85-1.15 at the extremes."""
    now, before = bl.get("referring_domains") or 0, bl.get("previous")
    if not before:
        return 1.0
    return max(0.85, min(1.15, 1.0 + 0.5 * (now - before) / before))


def _backlink_source(f: dict[str, Any]) -> str:
    return (f.get("backlinks") or {}).get("provider") or "Connected backlink provider"


def brand_competitiveness(project: Project, f: dict[str, Any]) -> Index:
    """Can the brand win against the alternatives people are also considering?"""
    idx = Index("brand_competitiveness", "Brand Competitiveness",
                "Against the alternatives, how strong is this brand's position?")
    geo = f.get("geo")
    if geo and geo.get("brand_mention_rate") is not None:
        brand_rate = geo["brand_mention_rate"] or 0
        comp_sum = sum(geo.get("competitors", {}).values())
        sov = brand_rate / (brand_rate + comp_sum) if (brand_rate + comp_sum) > 0 else 0
        idx.components.append(Component(
            "ai_share_of_voice", "Share of voice in AI answers", 0.22, round(sov * 100, 1),
            {"brand": brand_rate, "competitors": geo.get("competitors", {})}, "share", "AI visibility run",
            "brand mention rate / (brand mention rate + sum of competitor mention rates)",
            "Your share of the AI recommendation (the only place AI model knowledge is scored, to avoid double counting)."))
        idx.components.append(Component(
            "own_citation", "Your site cited by AI", 0.10,
            round((geo.get("own_domain_cited_rate") or 0) * 100, 1), geo.get("own_domain_cited_rate"), "rate",
            "AI visibility run", "own-domain citation rate x 100",
            "When AI cites your own site rather than a third party, you control the narrative."))
    else:
        idx.components += [Component("ai_share_of_voice", "Share of voice in AI answers", 0.22, None,
                                     None, "share", "AI visibility run", "brand / (brand + competitors)"),
                           Component("own_citation", "Your site cited by AI", 0.10, None, None,
                                     "rate", "AI visibility run", "own-domain citation rate x 100")]
    nb, tot = f.get("nonbranded"), f.get("totals")
    idx.components.append(Component(
        "nonbrand_search", "Non-branded search capture", 0.22,
        saturate(nb["clicks"], 150) if nb else None, nb["clicks"] if nb else None, "clicks / 28d",
        "Google Search Console", "saturate(non-branded clicks, half=150)",
        "Clicks you win without using your own name are the demand actually taken from competitors."))
    idx.components.append(Component(
        "ranking_quality", "Ranking quality", 0.10,
        round(0.5 * position_score(tot["position"]) + 0.5 * (f["top10_share"] * 100), 1)
        if tot and f.get("top10_share") is not None else None,
        {"avg_position": tot["position"] if tot else None, "top10_share": f.get("top10_share")}, "",
        "Google Search Console", "0.5 x position score + 0.5 x share of rows in the top 10 x 100",
        "Average position 1 scores about 100; position 20 scores about 0."))
    gap = f.get("keyword_gap")
    idx.components.append(Component(
        "keyword_overlap", "Keyword overlap with competitors", 0.15,
        # Volume-weighted, so matching them on terms nobody searches for does not flatter the score.
        round(100 * (0.4 * gap["coverage"] + 0.6 * gap["volume_coverage"]), 1) if gap else None,
        gap, "share of contested keywords", "Keyword provider",
        "100 x (0.4 x share of competitor keywords you also rank for + 0.6 x the same weighted by search volume)",
        ("The only component here measured against competitors rather than against yourself."
         if gap else "Connect a keyword provider and run “Sync ranked keywords” to score this.")))
    run, perf = f.get("run"), f.get("perf") or []
    if run:
        site = (run.quality_scores.get("overall") or {}).get("score")
        lh = [p.scores.get("performance") for p in perf if p.scores.get("performance") is not None]
        parts = [s for s in [(site * 10) if site is not None else None,
                             (sum(lh) / len(lh)) if lh else None] if s is not None]
        idx.components.append(Component(
            "site_quality", "Website quality", 0.15,
            round(sum(parts) / len(parts), 1) if parts else None,
            {"siteone_score": site, "lighthouse_performance": round(sum(lh) / len(lh), 1) if lh else None}, "",
            "SiteOne crawl + Lighthouse", "mean of (SiteOne overall x 10) and the Lighthouse performance score",
            "Weak technical foundations waste whatever traffic you win."))
    else:
        idx.components.append(Component("site_quality", "Website quality", 0.15, None, None, "",
                                        "SiteOne crawl + Lighthouse", "mean of (SiteOne x 10) and Lighthouse"))
    kws, comps = f.get("keywords") or [], f.get("competitors") or []
    if kws or comps:
        rows = f.get("rows") or []
        seen = " ".join(r["query"].lower() for r in rows)
        covered = sum(1 for k in kws if k.text.lower() in seen)
        pages = [t.lower() for t in (f.get("page_titles") or [])]
        vs_pages = sum(1 for c in comps if any(c.name.lower() in t for t in pages))
        parts = []
        if kws:
            parts.append(100 * covered / len(kws))
        if comps:
            parts.append(100 * vs_pages / len(comps))
        idx.components.append(Component(
            "content_coverage", "Content coverage", 0.13, round(sum(parts) / len(parts), 1),
            {"target_keywords": len(kws), "covered": covered, "competitors": len(comps), "comparison_pages": vs_pages},
            "", "Target keywords + crawl",
            "mean of (target keywords already earning impressions) and (competitors with a comparison page)",
            "Comparison searches are exactly what buyers run while choosing."))
    else:
        idx.components.append(Component("content_coverage", "Content coverage", 0.13, None, None, "",
                                        "Target keywords + crawl",
                                        "mean of target-keyword coverage and competitor comparison-page coverage",
                                        "Add target keywords under Settings and competitors under Competitors first."))
    return idx


def monetization(project: Project, f: dict[str, Any], econ: dict[str, Any]) -> Index:
    """Can the attention be turned into money? Scores the machine, not the brand."""
    idx = Index("monetization", "Monetization Readiness", "Is this traffic set up to become revenue?")
    an, prev = f.get("analytics"), f.get("analytics_prev")
    if an and an["sessions"]:
        idx.components.append(Component(
            "conversion_rate", "Conversion rate", 0.40, ratio_score(an["conversion_rate"], 0.03)
            if an["conversions"] > 0 else None,
            round(an["conversion_rate"], 4) if an["conversions"] > 0 else 0, "rate", "Analytics",
            "conversion rate / 3% x 100 (3% scores 100)",
            "3% is taken as a commonly good level; adjust to your own industry." if an["conversions"] > 0
            else "No conversion / key event is recorded in your analytics yet, so this cannot be measured."))
    else:
        idx.components.append(Component("conversion_rate", "Conversion rate", 0.40, None, None, "rate",
                                        "Analytics", "conversion rate / 3% x 100"))
    plan = f.get("plan") or []
    readiness_keys = ("business:journey_gaps", "business:email_capture", "signal:contact", "signal:whatsapp")
    blockers = [p for p in plan if p.source in readiness_keys and p.status in ("todo", "in_progress")]
    tracking = [p for p in plan if p.source in ("signal:analytics", "analytics:no_conversion_event")
                and p.status in ("todo", "in_progress")]
    # Only meaningful once a crawl has produced the business/fix checks; an empty plan means "unknown", not "perfect".
    if plan and f.get("run") and any(p.section in ("business", "fix") for p in plan):
        checks = 4 - len({p.source for p in blockers}) - (1 if tracking else 0)
        idx.components.append(Component(
            "conversion_readiness", "Conversion setup", 0.25,
            round(100 * max(0, checks) / 4, 1),
            {"open_blockers": [p.title for p in blockers + tracking]}, "checks passed", "Growth plan",
            "(4 - open conversion checks) / 4 x 100",
            "Pricing and contact route, email capture, customer-journey gaps, conversion tracking."))
    else:
        idx.components.append(Component(
            "conversion_readiness", "Conversion setup", 0.25, None, None, "checks passed",
            "Growth plan", "(4 - open conversion checks) / 4 x 100",
            "Run a website audit first; until then the conversion path is unknown."))
    tot, tot_prev = f.get("totals"), f.get("totals_prev")
    parts = []
    if tot and tot_prev:
        parts.append(trend_score(tot["clicks"], tot_prev["clicks"]))
    if an and prev and prev["sessions"]:
        parts.append(trend_score(an["sessions"], prev["sessions"]))
    idx.components.append(Component(
        "momentum", "Growth momentum", 0.15, round(sum(parts) / len(parts), 1) if parts else None,
        {"search_clicks": [tot_prev["clicks"], tot["clicks"]] if tot and tot_prev else None,
         "sessions": [prev["sessions"], an["sessions"]] if an and prev else None},
        "", "Search Console + Analytics",
        "mean of the period-over-period trend scores for search clicks and sessions (50 = flat)"))
    if tot:
        idx.components.append(Component(
            "demand_captured", "Demand captured", 0.20, ratio_score(tot["ctr"], expected_ctr(tot["position"])),
            {"ctr": round(tot["ctr"], 4), "expected_ctr_at_position": expected_ctr(tot["position"]),
             "avg_position": tot["position"]}, "",
            "Google Search Console", "actual CTR / expected CTR at that position x 100",
            "How much of the click-through a page at your position normally earns. Deep positions have a low "
            "expectation, so a high score here does not mean good rankings — that is Ranking quality."))
    else:
        idx.components.append(Component("demand_captured", "Demand captured", 0.20, None, None, "",
                                        "Google Search Console", "actual CTR / expected CTR x 100"))
    return idx


# ----------------------------------------------------------------------- revenue model
def revenue_model(f: dict[str, Any], econ: dict[str, Any]) -> dict[str, Any]:
    """Annualised revenue run-rate and achievable potential. A model with stated inputs, not a measurement."""
    an, tot = f.get("analytics"), f.get("totals")
    aov = econ.get("average_order_value")
    cr_actual = an["conversion_rate"] if an and an["conversions"] > 0 else None
    cr = cr_actual if cr_actual else econ.get("assumed_conversion_rate")
    periods = 365 / 28  # 28-day windows per year
    sessions = an["sessions"] if an and an["sessions"] else (tot["clicks"] if tot else 0)
    basis = "analytics sessions" if an and an["sessions"] else ("search clicks" if tot else None)

    upside_clicks = 0.0
    detail = []
    if f.get("rows"):
        for r in f["rows"]:
            if 0 < r["position"] <= 10:
                gap = max(0.0, expected_ctr(r["position"]) - r["ctr"]) * r["impressions"]
                upside_clicks += gap
            elif 10 < r["position"] <= 20:
                upside_clicks += max(0.0, expected_ctr(5) - r["ctr"]) * r["impressions"] * 0.3  # 30% chance of reaching top 5
        detail.append("Clicks you already have impressions for but do not win: better titles and descriptions, "
                      "plus page-two rankings moved to page one (discounted to a 30% success rate)")

    def money(units: float) -> float | None:
        return round(units * (cr or 0) * aov * periods, 2) if aov else None

    current = money(sessions)
    potential = money(sessions + upside_clicks)
    low, high = econ.get("revenue_multiple_low"), econ.get("revenue_multiple_high")
    return {
        "currency": econ.get("currency", "USD"),
        "inputs": {"average_order_value": aov, "conversion_rate": cr, "conversion_rate_source":
                   "measured in analytics" if cr_actual else "assumption — set a key event in GA4 to measure it",
                   "sessions_28d": sessions, "basis": basis,
                   "revenue_multiple": [low, high], "gross_margin": econ.get("gross_margin")},
        "formula": "annual revenue = sessions per 28 days x conversion rate x average order value x (365 / 28)",
        "current_run_rate": current,
        "achievable": potential,
        "upside": round((potential - current), 2) if (current is not None and potential is not None) else None,
        "upside_sessions_28d": round(upside_clicks, 1),
        "upside_sources": detail,
        "indicative_valuation": ({"low": round(current * low, 2), "high": round(current * high, 2),
                                  "basis": "current annual run rate x revenue multiple"} if current and low and high else None),
        "caveats": [
            "This is a model output, not a measurement: change any input and the result changes.",
            "It covers organic search and connected analytics only — not ads, outbound sales or word of mouth.",
            ("No average order value is set, so no monetary figure is produced." if not aov
             else "Average order value and conversion rate are the inputs you supplied."),
            "The valuation range is indicative only; real value depends on growth, margin, retention and the market.",
        ],
    }


# ----------------------------------------------------------------------- entry point
def build_scorecard(db: Session, project: Project) -> dict[str, Any]:
    econ = {**DEFAULT_ECONOMICS, **((project.settings or {}).get("economics") or {})}
    f = _facts(db, project)
    if f.get("run"):
        f["page_titles"] = [p.title or "" for p in D.html_pages(db, f["run"].id)] + \
                           [p.path for p in D.html_pages(db, f["run"].id)]
    indices = [brand_influence(project, f), brand_competitiveness(project, f), monetization(project, f, econ)]
    results = [i.result() for i in indices]
    scored = [r["score"] for r in results if r["score"] is not None]  # provisional scores never reach the overall
    overall = overall_score(scored)
    weakest = min((r for r in results if r["score"] is not None), key=lambda r: r["score"], default=None)
    revenue = revenue_model(f, econ)
    _record_snapshot(db, project.id, overall, results, revenue.get("current_run_rate"))
    prev, series = _history(db, project.id)
    # attach deltas + levers to each index
    levers = _levers(db, project.id)
    for r in results:
        r["delta"] = _delta(r["score"], (prev.get("scores") or {}).get(r["key"]) if prev else None)
        r["previous_score"] = (prev.get("scores") or {}).get(r["key"]) if prev else None
        r["levers"] = levers.get(r["key"], [])
    return {
        "project": {"id": str(project.id), "name": project.name, "brand": project.brand_name},
        "generated_at": date.today().isoformat(),
        "overall": {"score": overall, "grade": grade(overall), "label": "Growth Score",
                    "formula": "Geometric mean of the scored indices (weakest-link): a low dimension pulls the whole down.",
                    # How much of the whole intended model has data, so the headline can say what the three index
                    # cards already say. The mean of the index coverages rather than a re-weighting of every
                    # component: the overall treats the three indices equally, so its coverage has to as well.
                    "coverage": round(sum(r["coverage"] for r in results) / len(results), 2) if results else 0.0,
                    "indices_counted": len(scored), "indices_total": len(results),
                    "weakest_link": ({"key": weakest["key"], "label": weakest["label"], "score": weakest["score"]}
                                     if weakest and len(scored) > 1 else None),
                    "delta": _delta(overall, prev.get("overall") if prev else None),
                    "previous_score": prev.get("overall") if prev else None},
        "indices": results,
        "history": series,
        "revenue": revenue,
        "economics": econ,
        "data_sources": {
            "search_console": bool(f.get("gsc")), "analytics": bool(f.get("analytics", {}).get("sessions")),
            "ai_visibility": bool(f.get("geo")), "crawl": bool(f.get("run")),
            "mentions": bool(f.get("mentions")), "competitors": len(f.get("competitors") or []),
        },
        "how_to_read": {
            "scale": "0-100. A is 85+, B is 70+, C is 55+, D is 40+, below that is E.",
            "missing_data": "Components without data are excluded and shown in coverage; nothing is filled in by guessing.",
            "min_coverage": f"An index with less than {int(MIN_COVERAGE * 100)}% coverage publishes no score, only the "
                            "inputs it still needs.",
            "not_a_benchmark": "Compare these against your own history, not against other companies.",
            "scope": "This scorecard measures customer ACQUISITION (getting found, chosen and converted). It does not "
                     "measure retention or lifetime value — a business with strong acquisition but weak retention can "
                     "still score well here while leaking customers.",
        },
    }


def _delta(now: float | None, before: float | None) -> float | None:
    if now is None or before is None:
        return None
    return round(now - before, 1)


def _record_snapshot(db: Session, project_id: uuid.UUID, overall: float | None, results: list[dict[str, Any]],
                     run_rate: float | None) -> None:
    """Persist one snapshot per project per day so the scorecard can draw trend lines. Idempotent by day."""
    from datetime import date as _date
    today = _date.today()
    existing = db.scalar(select(ScorecardSnapshot).where(ScorecardSnapshot.project_id == project_id,
                                                         ScorecardSnapshot.day == today))
    scores = {r["key"]: r["score"] for r in results}
    coverage = {r["key"]: r["coverage"] for r in results}
    if existing is None:
        db.add(ScorecardSnapshot(project_id=project_id, day=today, overall=overall, scores=scores,
                                 coverage=coverage, revenue_run_rate=run_rate))
    else:
        existing.overall, existing.scores, existing.coverage, existing.revenue_run_rate = overall, scores, coverage, run_rate
    db.commit()


def _history(db: Session, project_id: uuid.UUID, days: int = 90) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Return (previous snapshot before today, time series for the chart)."""
    from datetime import date as _date
    rows = db.scalars(select(ScorecardSnapshot).where(ScorecardSnapshot.project_id == project_id)
                      .order_by(ScorecardSnapshot.day.asc())).all()
    today = _date.today()
    prior = [r for r in rows if r.day < today]
    prev = ({"overall": prior[-1].overall, "scores": prior[-1].scores} if prior else None)
    series = [{"date": r.day.isoformat(), "overall": r.overall, **(r.scores or {})} for r in rows[-days:]]
    return prev, series


def _levers(db: Session, project_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    """Top open plan items that would raise each index, so a score links straight to the work."""
    items = db.scalars(select(PlanItem).where(PlanItem.project_id == project_id, PlanItem.section != "routine",
                                              PlanItem.status.in_(("todo", "in_progress")))
                       .order_by(PlanItem.priority.desc())).all()
    out: dict[str, list[dict[str, Any]]] = {}
    for key, cats in INDEX_LEVERS.items():
        picks = [i for i in items if i.category in cats][:2]
        out[key] = [{"id": str(i.id), "title": i.title, "priority": i.priority, "category": i.category} for i in picks]
    return out
