"""Keyword metrics, ranked keywords (for the competitor gap), rank tracking, discovery and seasonality."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.adapters.registry import provider_features, providers_with_feature
from app.adapters.search_data.common import clean_keyword
from app.models import (Competitor, Domain, Keyword, KeywordMetric, Project, ProviderConnection, RankedKeyword,
                        RankObservation)
from app.services.providers import connection_features, get_adapter, record_usage
from app.tasks.context import TaskContext
from app.tasks.registry import task

# What each job needs from a provider, in the words of the error the user will read. The category is not uniform:
# a keyword database prices keywords and knows a domain's whole footprint but cannot read a live SERP; SerpApi is
# the exact reverse. So every job asks for a feature and the connection is chosen to match.
FEATURE_LABELS = {
    "keyword_metrics": "price keywords (search volume, difficulty, CPC)",
    "ranked_keywords": "list what a domain ranks for",
    "rank_tracking": "check a live SERP position",
    "keyword_discovery": "suggest new keywords",
    "keyword_trends": "chart interest over time",
}


def search_data_connections(db, project_id: uuid.UUID | None) -> list[ProviderConnection]:
    """Enabled search-data connections visible to this project, project-scoped first, then oldest."""
    conns = [c for c in db.scalars(select(ProviderConnection).where(ProviderConnection.category == "search_data")).all()
             if c.project_id in (None, project_id) and c.is_enabled]
    conns.sort(key=lambda c: (c.project_id is None, c.created_at))
    return conns


def connected_provider(db, project_id: uuid.UUID, feature: str | None = None) -> str | None:
    """The search-data provider for this project, or the first one that can do `feature`."""
    for c in search_data_connections(db, project_id):
        if feature is None or feature in connection_features(c):
            return c.provider_key
    return None


def _no_provider(ctx: TaskContext, project_id: uuid.UUID, feature: str) -> None:
    """Raise the most useful error available when nothing connected can do `feature`."""
    label = FEATURE_LABELS.get(feature, feature)
    connected = [c.provider_key for c in search_data_connections(ctx.db, project_id)]
    if connected:
        able = providers_with_feature(feature, category="search_data")
        raise ValueError(f"None of the connected keyword providers ({', '.join(connected)}) can {label}. "
                         f"Providers that can: {', '.join(able)}.")
    raise ValueError("No keyword provider is connected — add one under Integrations → Keyword & SERP data")


def _provider(ctx: TaskContext, project_id: uuid.UUID, feature: str):
    """The single provider for jobs that only make sense once — pricing a keyword list, charting a trend."""
    label = FEATURE_LABELS.get(feature, feature)
    provider = ctx.params.get("provider_key") or connected_provider(ctx.db, project_id, feature)
    if not provider:
        _no_provider(ctx, project_id, feature)
    if feature not in provider_features(provider):
        raise ValueError(f"{provider} cannot {label}")
    return provider, *get_adapter(ctx.db, project_id, provider)


def _providers(ctx: TaskContext, project_id: uuid.UUID, feature: str) -> list[tuple[str, Any, Any]]:
    """Every connected provider that can do `feature`.

    Rank tracking is why this exists alongside `_provider`: a position on Google and a position on Bing are two
    different facts, not two estimates of one, so when both are connected both should be measured and stored under
    their own `provider_key`. Pricing a keyword list is the opposite — doing it twice would just cost twice — so
    that job still takes one provider. `provider_key` or `provider_keys` in the job params narrows the set.
    """
    wanted = {k for k in [ctx.params.get("provider_key"), *(ctx.params.get("provider_keys") or [])] if k}
    keys = list(dict.fromkeys(c.provider_key for c in search_data_connections(ctx.db, project_id)
                              if feature in connection_features(c)))
    if wanted:
        keys = [k for k in keys if k in wanted]
    if not keys:
        _no_provider(ctx, project_id, feature)
    return [(k, *get_adapter(ctx.db, project_id, k)) for k in keys]


def _host(value: str) -> str:
    v = (value or "").strip().lower()
    return ((urlsplit(v).hostname or "") if "://" in v else v.split("/")[0]).removeprefix("www.")[:255]


@task("sync_keyword_metrics", "Fetch search volume, difficulty and CPC for the project's target keywords")
def sync_keyword_metrics(ctx: TaskContext) -> dict[str, Any]:
    project_id = ctx.project_id
    provider, adapter, conn = _provider(ctx, project_id, "keyword_metrics")
    keywords = ctx.db.scalars(select(Keyword).where(Keyword.project_id == project_id,
                                                    Keyword.is_target.is_(True))).all()
    if not keywords:
        return {"provider": provider, "priced": 0, "note": "No target keywords yet — add some under Settings"}
    by_text = {k.text.strip().lower(): k for k in keywords}
    ctx.progress(20, f"Pricing {len(by_text)} keyword(s) with {provider}")
    result = adapter.collect_keyword_metrics({"keywords": list(by_text)})
    ctx.save_artifact(provider, "keyword_metrics", result.raw, meta=result.meta)
    rows = adapter.normalize_keyword_metrics(result)

    today: date = datetime.now(UTC).date()
    values = [{"project_id": project_id, "keyword_id": by_text[r["keyword"]].id, "provider_key": provider,
               "observed_on": today, **{k: v for k, v in r.items() if k != "keyword"}}
              for r in rows if r["keyword"] in by_text]
    for i in range(0, len(values), 500):
        stmt = insert(KeywordMetric).values(values[i:i + 500])
        stmt = stmt.on_conflict_do_update(constraint="uq_keyword_metric_day", set_={
            "search_volume": stmt.excluded.search_volume, "difficulty": stmt.excluded.difficulty,
            "cpc": stmt.excluded.cpc, "competition": stmt.excluded.competition,
            "intent": stmt.excluded.intent, "collected_at": stmt.excluded.collected_at})
        ctx.db.execute(stmt)
    record_usage(ctx.db, project_id=project_id, provider_key=provider, operation="keyword_metrics",
                 job_id=ctx.job.id, connection_id=conn.id if conn else None, units=1)
    ctx.db.commit()
    unmatched = [r["keyword"] for r in rows if r["keyword"] not in by_text][:10]
    return {"provider": provider, "requested": len(by_text), "priced": len(values),
            "unmatched_sample": unmatched, "observed_on": today.isoformat()}


@task("sync_ranked_keywords", "Fetch what your site and your competitors rank for, for the keyword gap")
def sync_ranked_keywords(ctx: TaskContext) -> dict[str, Any]:
    project_id = ctx.project_id
    provider, adapter, conn = _provider(ctx, project_id, "ranked_keywords")
    own = [d for d in ctx.db.scalars(select(Domain).where(Domain.project_id == project_id,
                                                          Domain.role == "primary")).all()]
    comp_hosts = [_host(d.hostname) for d in ctx.db.scalars(
        select(Domain).where(Domain.project_id == project_id, Domain.role == "competitor")).all()]
    targets = [(_host(d.hostname), True) for d in own] + [(h, False) for h in comp_hosts if h]
    # `hosts` re-syncs just a few sites — each host is a separate billed request, so this is the cheap path.
    if wanted := {_host(h) for h in (ctx.params.get("hosts") or []) if h}:
        targets = [t for t in targets if t[0] in wanted]
    if not targets:
        raise ValueError("No websites to analyse — add your site under Settings and competitors under Competitors")

    today: date = datetime.now(UTC).date()
    stored, failures = 0, {}
    for n, (host, is_own) in enumerate(targets, start=1):
        ctx.progress(int(80 * n / len(targets)), f"Ranked keywords for {host}")
        try:
            result = adapter.collect_ranked_keywords({"host": host, "limit": ctx.params.get("limit")})
            ctx.save_artifact(provider, "ranked_keywords", result.raw, meta=result.meta)
            rows = adapter.normalize_ranked_keywords(result)
        except Exception as exc:  # noqa: BLE001 — one bad host must not lose the others
            failures[host] = str(exc)[:200]
            ctx.log(f"Ranked keywords failed for {host}: {exc}", level="warning")
            continue
        values = [{"project_id": project_id, "provider_key": provider, "host": host, "is_own": is_own,
                   "observed_on": today, **r} for r in rows]
        for i in range(0, len(values), 500):
            stmt = insert(RankedKeyword).values(values[i:i + 500])
            stmt = stmt.on_conflict_do_update(constraint="uq_ranked_keyword_day", set_={
                "position": stmt.excluded.position, "url": stmt.excluded.url,
                "search_volume": stmt.excluded.search_volume, "traffic": stmt.excluded.traffic,
                "difficulty": stmt.excluded.difficulty, "is_own": stmt.excluded.is_own,
                "collected_at": stmt.excluded.collected_at})
            ctx.db.execute(stmt)
        stored += len(values)
        record_usage(ctx.db, project_id=project_id, provider_key=provider, operation="ranked_keywords",
                     job_id=ctx.job.id, connection_id=conn.id if conn else None, units=1)
    ctx.db.commit()
    return {"provider": provider, "hosts": len(targets), "keywords_stored": stored,
            "failures": failures or None, "observed_on": today.isoformat()}


@task("sync_rankings", "Check live SERP positions for the project's target keywords")
def sync_rankings(ctx: TaskContext) -> dict[str, Any]:
    """Check each tracked keyword on every connected search engine.

    Every engine runs, because Google and Bing are different questions rather than a second opinion, and each
    engine's rows are keyed by its own `provider_key` so the two are never averaged together. That does mean two
    connections cost twice as many searches as one — `provider_keys` in the job params restricts a run to a subset.
    """
    project_id = ctx.project_id
    providers = _providers(ctx, project_id, "rank_tracking")
    domain = ctx.db.scalar(select(Domain).where(Domain.project_id == project_id, Domain.role == "primary"))
    if domain is None:
        raise ValueError("Add your website under Settings first")
    keywords = ctx.db.scalars(select(Keyword).where(Keyword.project_id == project_id,
                                                    Keyword.is_target.is_(True))
                              .order_by(Keyword.importance.desc())).all()
    cap = int(ctx.params.get("limit") or 50)          # one request per keyword; never run away with the bill
    keywords = keywords[:cap]
    if not keywords:
        return {"providers": [p for p, _a, _c in providers], "checked": 0, "note": "No target keywords yet"}

    host = _host(domain.hostname)
    today: date = datetime.now(UTC).date()
    steps = max(1, len(providers) * len(keywords))
    step = 0
    by_provider: dict[str, Any] = {}
    for provider, adapter, conn in providers:
        # `spent` is what the provider says it actually billed, not how many keywords we asked about: SerpApi
        # charges a second search when Google hides the AI Overview behind a token, and one per result page on
        # Bing, so counting keywords would understate the bill.
        found, checked, spent, failures = 0, 0, 0, {}
        for n, kw in enumerate(keywords, start=1):
            step += 1
            ctx.progress(int(90 * step / steps), f"{provider} {n}/{len(keywords)}: {kw.text}")
            try:
                result = adapter.collect_rank({"keyword": kw.text, "host": host})
                result.meta["host"] = host
                spent += int(result.meta.get("searches") or 1)
                if n <= 3:   # keep a few raw SERPs for debugging without storing one per keyword
                    ctx.save_artifact(provider, "serp", result.raw, meta=result.meta)
                row = adapter.normalize_rank(result)
            except Exception as exc:  # noqa: BLE001
                failures[kw.text] = str(exc)[:200]
                continue
            if row is None:
                continue
            stmt = insert(RankObservation).values([{
                "project_id": project_id, "keyword_id": kw.id, "domain_id": domain.id, "provider_key": provider,
                "observed_on": today, "position": row["position"], "url": row["url"],
                "serp_features": row["serp_features"]}])
            stmt = stmt.on_conflict_do_update(constraint="uq_rank_observation_day", set_={
                "position": stmt.excluded.position, "url": stmt.excluded.url,
                "serp_features": stmt.excluded.serp_features, "collected_at": stmt.excluded.collected_at})
            ctx.db.execute(stmt)
            checked += 1
            found += 1 if row["position"] else 0
        record_usage(ctx.db, project_id=project_id, provider_key=provider, operation="serp",
                     job_id=ctx.job.id, connection_id=conn.id if conn else None, units=max(1, spent or checked))
        ctx.db.commit()
        by_provider[provider] = {"checked": checked, "ranking": found, "absent": checked - found,
                                 "searches_used": spent or None, "failures": failures or None}
    return {"providers": list(by_provider), "keywords": len(keywords), "observed_on": today.isoformat(),
            "by_provider": by_provider,
            "searches_used": sum(v["searches_used"] or 0 for v in by_provider.values()) or None}


@task("discover_keywords", "Find new keyword candidates from autocomplete, People Also Ask and Google Trends")
def discover_keywords(ctx: TaskContext) -> dict[str, Any]:
    """Expand seed keywords into candidates and store them as non-target keywords.

    Candidates land with `is_target=False`, so nothing else picks them up automatically — they are a shortlist for
    the user to promote, and pricing them is a separate, billed job. That ordering is the point: discovery is one
    cheap search per angle, whereas a keyword database charges to price every term you hand it, so the expensive
    provider should only ever see candidates that survived a human glance.
    """
    project_id = ctx.project_id
    provider, adapter, conn = _provider(ctx, project_id, "keyword_discovery")
    project = ctx.db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")

    seeds = [clean_keyword(s) for s in (ctx.params.get("seeds") or [])]
    if not any(seeds):
        seeds = [clean_keyword(k.text) for k in ctx.db.scalars(
            select(Keyword).where(Keyword.project_id == project_id, Keyword.is_target.is_(True))
            .order_by(Keyword.importance.desc())).all()]
    seeds = [s for s in dict.fromkeys(seeds) if s][:int(ctx.params.get("max_seeds") or 10)]
    if not seeds:
        raise ValueError("Nothing to expand — add target keywords under Settings, or pass `seeds`")

    # Every call is a billed search, so the ceiling is explicit rather than a function of how many seeds exist.
    budget = max(1, int(ctx.params.get("max_searches") or 30))
    angles: list[tuple[str, Any]] = [("autocomplete", adapter.collect_suggestions),
                                     ("serp", adapter.collect_serp_ideas)]
    if adapter.config.get("discovery_trends"):
        angles.append(("trends", adapter.collect_trend_queries))

    known = {clean_keyword(t) for t in ctx.db.scalars(select(Keyword.text).where(Keyword.project_id == project_id)).all()}
    ideas: dict[str, dict[str, Any]] = {}
    spent, failures = 0, {}
    for n, seed in enumerate(seeds, start=1):
        for angle, collect in angles:
            if spent >= budget:
                break
            ctx.progress(int(85 * n / len(seeds)), f"{angle}: {seed}")
            try:
                result = collect({"seed": seed})
                spent += int(result.meta.get("searches") or 1)
                rows = adapter.normalize_ideas(result)
            except Exception as exc:  # noqa: BLE001 — one dead angle must not lose the others
                failures[f"{seed} ({angle})"] = str(exc)[:200]
                continue
            for row in rows:
                if row["keyword"] in known:
                    continue
                prev = ideas.get(row["keyword"])
                # Keep the highest score for a term, but remember every angle that produced it — a candidate both
                # autocomplete and Trends surfaced is a stronger signal than one that appeared once.
                if prev is None:
                    ideas[row["keyword"]] = {**row, "seed": seed, "sources": [row["source"]]}
                else:
                    prev["sources"] = sorted(set(prev["sources"] + [row["source"]]))
                    if (row["score"] or 0) > (prev["score"] or 0):
                        prev["score"] = row["score"]

    ranked = sorted(ideas.values(), key=lambda r: (-len(r["sources"]), -(r["score"] or 0), r["keyword"]))
    ctx.save_artifact(provider, "keyword_ideas", ranked,
                      meta={"seeds": seeds, "searches": spent, "angles": [a for a, _f in angles]})
    stored = 0
    if ranked:
        values = [{"project_id": project_id, "text": r["keyword"][:300], "language": project.default_language,
                   "country": project.default_country, "is_target": False, "importance": 2,
                   "source": f"serpapi:{'+'.join(r['sources'])}"[:50],
                   "tags": [f"seed:{r['seed']}"[:60]]} for r in ranked]
        for i in range(0, len(values), 500):
            stmt = insert(Keyword).values(values[i:i + 500]).on_conflict_do_nothing(constraint="uq_keyword")
            stored += ctx.db.execute(stmt).rowcount or 0
    record_usage(ctx.db, project_id=project_id, provider_key=provider, operation="keyword_discovery",
                 job_id=ctx.job.id, connection_id=conn.id if conn else None, units=max(1, spent))
    ctx.db.commit()
    return {"provider": provider, "seeds": seeds, "searches_used": spent, "candidates": len(ranked),
            "stored": stored, "top": [r["keyword"] for r in ranked[:15]], "failures": failures or None,
            "note": "Candidates are saved as non-target keywords. Promote the good ones under Settings, then run "
                    "“Refresh keyword data” to price only those."}


@task("sync_keyword_seasonality", "Chart Google Trends interest over time for your most important keywords")
def sync_keyword_seasonality(ctx: TaskContext) -> dict[str, Any]:
    """Relative interest for up to five keywords — Google compares at most five terms in one request.

    Trends values are relative to the peak of the compared set, never absolute volume, so this is stored as an
    artifact with a direction summary in the job result rather than being written into `keyword_metrics`, where it
    would sit next to real volumes and invite the two being read as the same kind of number.
    """
    project_id = ctx.project_id
    provider, adapter, conn = _provider(ctx, project_id, "keyword_trends")
    wanted = [clean_keyword(k) for k in (ctx.params.get("keywords") or [])]
    if not any(wanted):
        wanted = [clean_keyword(k.text) for k in ctx.db.scalars(
            select(Keyword).where(Keyword.project_id == project_id, Keyword.is_target.is_(True))
            .order_by(Keyword.importance.desc())).all()]
    wanted = [w for w in dict.fromkeys(wanted) if w][:5]
    if not wanted:
        return {"provider": provider, "keywords": 0, "note": "No target keywords yet — add some under Settings"}
    ctx.progress(30, f"Google Trends for {len(wanted)} keyword(s)")
    result = adapter.collect_interest_over_time({"keywords": wanted, "date": ctx.params.get("date")})
    ctx.save_artifact(provider, "keyword_trends", result.raw, meta=result.meta)
    rows = adapter.normalize_interest_over_time(result)
    record_usage(ctx.db, project_id=project_id, provider_key=provider, operation="keyword_trends",
                 job_id=ctx.job.id, connection_id=conn.id if conn else None,
                 units=int(result.meta.get("searches") or 1))
    ctx.db.commit()
    return {"provider": provider, "keywords": wanted, "window": ctx.params.get("date") or "today 12-m",
            "series": [{k: v for k, v in r.items() if k != "points"} for r in rows],
            "note": "Trends numbers are relative to the peak of the compared set, not search volume."}
