"""Website crawl + technical SEO audit via SiteOne. Produces a CrawlRun with PageSnapshots and AuditFindings."""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.models import AuditFinding, CrawlRun, Domain, PageSnapshot
from app.services.ai_crawlers import fetch_and_analyze
from app.services.page_signals import fetch_signals, serves_brotli, serves_image_format
from app.services.providers import get_adapter, record_usage
from app.services.render import RENDER_PROVIDER, get_renderer
from app.tasks.context import TaskContext
from app.tasks.registry import task


@task("crawl_domain", "Crawl a domain and run the technical SEO audit (SiteOne)", queue="crawler")
def crawl_domain(ctx: TaskContext) -> dict[str, Any]:
    domain = ctx.db.get(Domain, uuid.UUID(ctx.params["domain_id"]))
    if domain is None:
        raise ValueError("Domain not found")
    adapter, conn = get_adapter(ctx.db, ctx.project_id, "siteone")
    request = {"url": domain.base_url, **{k: v for k, v in ctx.params.items() if k in ("max_urls", "max_depth", "max_reqs_per_sec", "workers", "timeout", "ignore_robots_txt")}}
    run = CrawlRun(project_id=domain.project_id, domain_id=domain.id, job_id=ctx.job.id, provider_key="siteone",
                   config={k: v for k, v in request.items()}, started_at=datetime.now(UTC))
    ctx.db.add(run)
    ctx.db.commit()
    ctx.progress(5, f"Crawling {domain.base_url}")

    seen = {"n": 0}

    def on_output(line: str) -> None:
        seen["n"] += 1
        if seen["n"] % 25 == 0:
            ctx.progress(min(70, 5 + seen["n"] // 5), line[:120])

    request["on_output"] = on_output
    result = adapter.collect(request)
    ctx.progress(75, "Crawl finished, normalizing results")
    artifact = ctx.save_artifact("siteone", "crawl", result.raw, meta=result.meta)
    normalized = adapter.normalize(result)

    page_ids: dict[str, uuid.UUID] = {}
    for p in normalized.pages:
        snap = PageSnapshot(crawl_run_id=run.id, project_id=domain.project_id, domain_id=domain.id, url=p.url, path=p.path,
                            status_code=p.status_code, content_type=p.content_type, response_time_ms=p.response_time_ms,
                            size_bytes=p.size_bytes, title=p.title, meta_description=p.meta_description, h1=p.h1,
                            indexing=p.indexing, robots_index=p.robots_index, denied_by_robots_txt=p.denied_by_robots_txt,
                            headings_count=p.headings_count, headings_errors=p.headings_errors,
                            headings_structure=p.headings_structure, canonical=p.canonical, signals=p.signals, cache_type_flags=p.cache_type_flags,
                            cache_lifetime=p.cache_lifetime, og=p.og, seo_score=p.seo_score)
        ctx.db.add(snap)
        ctx.db.flush()
        page_ids[p.url] = snap.id
    counts: Counter[str] = Counter()
    for f in normalized.findings:
        counts[f.severity] += 1
        ctx.db.add(AuditFinding(crawl_run_id=run.id, project_id=domain.project_id, domain_id=domain.id,
                                page_snapshot_id=page_ids.get(f.url or ""), url=f.url, code=f.code, category=f.category,
                                severity=f.severity, message=f.message, details=f.details))
    run.artifact_id = artifact.id
    run.provider_version = normalized.crawler_version
    run.finished_at = datetime.now(UTC)
    run.total_urls = normalized.total_urls
    run.html_pages = normalized.html_pages
    run.count_by_status = normalized.count_by_status
    run.quality_scores = normalized.quality_scores
    run.summary = normalized.summary
    run.stats = normalized.stats
    run.findings_count = dict(counts)
    ctx.db.commit()
    ctx.progress(88, "Checking key pages for contact, schema and social signals")
    signal_pages = _collect_signals(ctx, domain, run.id)

    ctx.progress(95, "Checking which AI crawlers robots.txt allows")
    ai_crawlers = _check_ai_crawlers(ctx, domain, run.id)
    # Reassigned rather than mutated in place: JSONB columns are not change-tracked element by element.
    run.stats = {**(run.stats or {}), "ai_crawlers": ai_crawlers}
    ctx.db.commit()

    record_usage(ctx.db, project_id=domain.project_id, provider_key="siteone", operation="crawl", job_id=ctx.job.id,
                 units=normalized.total_urls, unit_type="urls", connection_id=conn.id if conn else None)
    ctx.db.commit()
    ctx.progress(100, "Done")
    return {"crawl_run_id": str(run.id), "total_urls": run.total_urls, "html_pages": run.html_pages,
            "findings": dict(counts), "overall_score": (normalized.quality_scores.get("overall") or {}).get("score"),
            "signal_pages": signal_pages,
            "ai_crawlers_blocked": sorted({*ai_crawlers.get("blocked_answers", []), *ai_crawlers.get("blocked_search", [])})}


SIGNAL_PAGE_LIMIT = 8


def _collect_signals(ctx: TaskContext, domain: Domain, run_id: uuid.UUID) -> int:
    """Fetch the home page plus a few important pages and store their head/contact/social signals."""
    from sqlalchemy import func, select

    from app.models import PageSnapshot, SearchObservation

    home = ctx.db.scalar(select(PageSnapshot).where(PageSnapshot.crawl_run_id == run_id, PageSnapshot.path == "/"))
    targets: list[PageSnapshot] = [home] if home else []
    top_pages = [r[0] for r in ctx.db.execute(
        select(SearchObservation.page, func.sum(SearchObservation.clicks).label("c"))
        .where(SearchObservation.domain_id == domain.id, SearchObservation.page != "")
        .group_by(SearchObservation.page).order_by(func.sum(SearchObservation.clicks).desc()).limit(20)).all()]
    wanted = {p.rstrip("/") for p in top_pages}
    extra = ctx.db.scalars(select(PageSnapshot).where(PageSnapshot.crawl_run_id == run_id, PageSnapshot.content_type == "html",
                                                      PageSnapshot.status_code == 200)).all()
    for p in extra:
        if len(targets) >= SIGNAL_PAGE_LIMIT:
            break
        if p.path == "/" or any(t.id == p.id for t in targets):
            continue
        if p.url.rstrip("/") in wanted or any(k in p.path.lower() for k in ("pricing", "contact", "about", "plans")):
            targets.append(p)
    # Client-rendered pages arrive as empty shells, so the signals below would all read as missing. If an Extract
    # connection exists, those pages (and only those) are re-fetched through it, up to its own page ceiling.
    renderer, budget = get_renderer(ctx.db, ctx.project_id)
    checked = 0
    rendered = 0
    for p in targets[:SIGNAL_PAGE_LIMIT]:
        sig = fetch_signals(p.url, renderer if rendered < budget else None)
        if sig.get("rendered"):
            rendered += 1
        # Compression and modern image formats are server/CDN-wide properties, so one check on the home page settles
        # them for the domain and lets the plan ignore SiteOne's false positives (its probes do not advertise
        # Accept-Encoding: br, nor negotiate image/webp / image/avif).
        if p.path == "/" and sig.get("checked"):
            sig["serves_brotli"] = serves_brotli(p.url)
            if sig.get("sample_image"):
                sig["serves_webp"] = serves_image_format(sig["sample_image"], "image/webp")
                sig["serves_avif"] = serves_image_format(sig["sample_image"], "image/avif")
        p.signals = sig
        if sig.get("checked"):
            checked += 1
            p.canonical = sig.get("canonical")
            if sig.get("robots"):
                p.indexing = sig["robots"]
            if sig.get("noindex"):
                p.robots_index = False
        ctx.db.commit()
    if rendered:
        record_usage(ctx.db, project_id=ctx.project_id, provider_key=RENDER_PROVIDER, operation="render",
                     job_id=ctx.job.id, units=rendered)
        ctx.db.commit()
    return checked


# How many crawled paths are tested against robots.txt per crawler. A site-wide `Disallow: /` is caught by the
# "/" check alone; this is for the narrower case where the home page is open but the pages that would actually be
# cited — docs, pricing, the blog — sit under a disallowed prefix.
ROBOTS_PATH_SAMPLE = 25


def _check_ai_crawlers(ctx: TaskContext, domain: Domain, run_id: uuid.UUID) -> dict[str, Any]:
    """Read robots.txt and report which AI crawlers it admits. Never fails the crawl."""
    from sqlalchemy import select

    paths = ctx.db.scalars(
        select(PageSnapshot.path).where(PageSnapshot.crawl_run_id == run_id, PageSnapshot.content_type == "html",
                                        PageSnapshot.status_code == 200)
        .order_by(PageSnapshot.path).limit(ROBOTS_PATH_SAMPLE)).all()
    try:
        return fetch_and_analyze(domain.base_url, list(paths))
    except Exception as exc:  # noqa: BLE001 — an advisory check must not lose a completed crawl
        return {"checked": False, "status": "error", "detail": str(exc)[:300]}
