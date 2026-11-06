from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_domain, get_project
from app.core.db import get_db
from app.intelligence import data as D
from app.models import (AuditFinding, Backlink, BacklinkProfileSnapshot, BingSearchObservation, Competitor, CrawlRun, Domain, Keyword, KeywordMetric,
                        PageSnapshot, PerformanceObservation, Project, RankedKeyword, RankObservation, ReferringDomain,
                        SearchObservation)
from app.services.page_inspect import CODE_TO_INSPECTOR, INSPECTORS, inspect_pages
from app.services.render import get_renderer

router = APIRouter(prefix="/projects/{project_id}/seo", tags=["seo"])


def _run_out(r: CrawlRun) -> dict:
    return {"id": str(r.id), "domain_id": str(r.domain_id), "job_id": str(r.job_id) if r.job_id else None, "provider_key": r.provider_key,
            "provider_version": r.provider_version, "started_at": r.started_at, "finished_at": r.finished_at, "total_urls": r.total_urls,
            "html_pages": r.html_pages, "count_by_status": r.count_by_status, "quality_scores": r.quality_scores, "summary": r.summary,
            "stats": r.stats, "findings_count": r.findings_count, "config": r.config}


@router.get("/crawls")
def list_crawls(project: Project = Depends(get_project), domain_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    stmt = select(CrawlRun).where(CrawlRun.project_id == project.id).order_by(desc(CrawlRun.started_at)).limit(50)
    if domain_id:
        stmt = stmt.where(CrawlRun.domain_id == domain_id)
    return [_run_out(r) for r in db.scalars(stmt).all()]


@router.get("/crawls/{run_id}")
def get_crawl(run_id: uuid.UUID, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    run = db.get(CrawlRun, run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(404, "Crawl not found")
    return _run_out(run)


@router.get("/crawls/{run_id}/pages")
def crawl_pages(run_id: uuid.UUID, project: Project = Depends(get_project), content_type: str = "html",
                q: str | None = None, limit: int = Query(200, le=2000), offset: int = 0, db: Session = Depends(get_db)):
    stmt = select(PageSnapshot).where(PageSnapshot.crawl_run_id == run_id, PageSnapshot.project_id == project.id)
    if content_type != "all":
        stmt = stmt.where(PageSnapshot.content_type == content_type)
    if q:
        stmt = stmt.where(PageSnapshot.url.ilike(f"%{q}%"))
    stmt = stmt.order_by(PageSnapshot.seo_score.asc().nulls_last(), PageSnapshot.url).offset(offset).limit(limit)
    pages = db.scalars(stmt).all()
    counts = dict(db.execute(select(AuditFinding.page_snapshot_id, func.count()).where(AuditFinding.crawl_run_id == run_id,
                                                                                      AuditFinding.page_snapshot_id.isnot(None))
                             .group_by(AuditFinding.page_snapshot_id)).all())
    return [{"id": str(p.id), "url": p.url, "path": p.path, "status_code": p.status_code, "content_type": p.content_type,
             "response_time_ms": p.response_time_ms, "size_bytes": p.size_bytes, "title": p.title, "meta_description": p.meta_description,
             "h1": p.h1, "canonical": p.canonical, "indexing": p.indexing, "robots_index": p.robots_index, "headings_count": p.headings_count,
             "headings_errors": p.headings_errors, "seo_score": p.seo_score, "findings": counts.get(p.id, 0)} for p in pages]


@router.get("/crawls/{run_id}/findings")
def crawl_findings(run_id: uuid.UUID, project: Project = Depends(get_project), severity: str | None = None, code: str | None = None,
                   url: str | None = None, limit: int = Query(500, le=5000), db: Session = Depends(get_db)):
    stmt = select(AuditFinding).where(AuditFinding.crawl_run_id == run_id, AuditFinding.project_id == project.id)
    if severity:
        stmt = stmt.where(AuditFinding.severity == severity)
    if code:
        stmt = stmt.where(AuditFinding.code == code)
    if url:
        stmt = stmt.where(AuditFinding.url == url)
    order = {"critical": 0, "warning": 1, "info": 2}
    rows = db.scalars(stmt.limit(limit)).all()
    rows.sort(key=lambda f: (order.get(f.severity, 9), f.code))
    return [{"id": str(f.id), "url": f.url, "code": f.code, "category": f.category, "severity": f.severity, "message": f.message,
             "details": f.details} for f in rows]


@router.get("/crawls/{run_id}/compare/{other_run_id}")
def compare_crawls(run_id: uuid.UUID, other_run_id: uuid.UUID, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Change detection between two crawl snapshots (other = older baseline)."""
    a, b = db.get(CrawlRun, run_id), db.get(CrawlRun, other_run_id)
    if not a or not b or a.project_id != project.id or b.project_id != project.id:
        raise HTTPException(404, "Crawl not found")
    pa = {p.url: p for p in db.scalars(select(PageSnapshot).where(PageSnapshot.crawl_run_id == a.id, PageSnapshot.content_type == "html")).all()}
    pb = {p.url: p for p in db.scalars(select(PageSnapshot).where(PageSnapshot.crawl_run_id == b.id, PageSnapshot.content_type == "html")).all()}
    changed = []
    for url in pa.keys() & pb.keys():
        x, y = pa[url], pb[url]
        diffs = {k: {"before": getattr(y, k), "after": getattr(x, k)} for k in ("title", "meta_description", "h1", "status_code", "seo_score", "robots_index")
                 if getattr(x, k) != getattr(y, k)}
        if diffs:
            changed.append({"url": url, "changes": diffs})
    fa = {(f.code, f.url or "") for f in db.scalars(select(AuditFinding).where(AuditFinding.crawl_run_id == a.id)).all()}
    fb = {(f.code, f.url or "") for f in db.scalars(select(AuditFinding).where(AuditFinding.crawl_run_id == b.id)).all()}
    return {"current": _run_out(a), "baseline": _run_out(b),
            "pages_added": sorted(pa.keys() - pb.keys())[:200], "pages_removed": sorted(pb.keys() - pa.keys())[:200],
            "pages_changed": changed[:300],
            "findings_new": [{"code": c, "url": u} for c, u in sorted(fa - fb)][:300],
            "findings_resolved": [{"code": c, "url": u} for c, u in sorted(fb - fa)][:300],
            "score_delta": {"overall": ((a.quality_scores.get("overall") or {}).get("score") or 0) - ((b.quality_scores.get("overall") or {}).get("score") or 0)}}


@router.get("/crawls/{run_id}/inspectable")
def inspectable(run_id: uuid.UUID, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Which findings of this crawl can be explained page by page."""
    codes = {f.code for f in db.scalars(select(AuditFinding).where(AuditFinding.crawl_run_id == run_id,
                                                                  AuditFinding.project_id == project.id)).all()}
    return {"codes": {c: {"inspector": CODE_TO_INSPECTOR[c], "label": INSPECTORS[CODE_TO_INSPECTOR[c]]["label"]}
                      for c in codes if c in CODE_TO_INSPECTOR},
            "all_inspectors": {k: v["label"] for k, v in INSPECTORS.items()}}


@router.post("/crawls/{run_id}/inspect")
def inspect(run_id: uuid.UUID, code: str | None = None, inspector: str | None = None, limit: int = Query(25, ge=1, le=60),
            project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Fetch the crawled HTML pages again and show exactly where a site-level finding occurs.

    SiteOne reports these as totals only ("434 pages do not support Brotli"); this returns the pages and the element.
    """
    run = db.get(CrawlRun, run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(404, "Crawl not found")
    name = inspector or CODE_TO_INSPECTOR.get(code or "")
    if not name or name not in INSPECTORS:
        raise HTTPException(400, f"No page-level inspector for '{code or inspector}'. Available: {sorted(INSPECTORS)}")
    scoped = [f.url for f in db.scalars(select(AuditFinding).where(AuditFinding.crawl_run_id == run_id, AuditFinding.code == code,
                                                                  AuditFinding.url.isnot(None))).all()] if code else []
    if scoped:
        urls = list(dict.fromkeys(scoped))[:limit]
    else:  # site-level finding: sample the crawled HTML pages, most important first
        clicks = dict(db.execute(select(SearchObservation.page, func.sum(SearchObservation.clicks))
                                 .where(SearchObservation.domain_id == run.domain_id, SearchObservation.page != "")
                                 .group_by(SearchObservation.page)).all())
        pages = db.scalars(select(PageSnapshot).where(PageSnapshot.crawl_run_id == run_id, PageSnapshot.content_type == "html",
                                                      PageSnapshot.status_code == 200)).all()
        pages.sort(key=lambda p: (-(int(clicks.get(p.url, 0) or 0)), p.path.count("/"), p.path))
        urls = [p.url for p in pages[:limit]]
    if not urls:
        raise HTTPException(404, "No pages to inspect for this finding")
    renderer, budget = get_renderer(db, project.id)
    result = inspect_pages(urls, name, renderer, budget)
    result["code"] = code
    result["note"] = ("Checked a sample of the most important pages, re-fetched live — results reflect the site right now, "
                      "not the moment of the crawl.")
    if result.get("pages_skipped_unrendered"):
        result["note"] += (f" {result['pages_skipped_unrendered']} page(s) were skipped because they arrived as an "
                           "empty app shell: their content is built by JavaScript, which this check does not run. "
                           "Connect SerpApi Extract under Integrations → Website crawling to inspect them.")
    elif result.get("pages_rendered"):
        result["note"] += f" {result['pages_rendered']} page(s) needed JavaScript and were rendered via SerpApi Extract."
    return result


@router.get("/crawls/{run_id}/uncacheable")
def uncacheable_assets(run_id: uuid.UUID, project: Project = Depends(get_project), limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    """Static assets the crawl saw without a usable cache lifetime (no refetch needed)."""
    rows = db.scalars(select(PageSnapshot).where(PageSnapshot.crawl_run_id == run_id, PageSnapshot.project_id == project.id,
                                                 PageSnapshot.content_type.in_(("js", "css", "image", "font", "video", "audio")),
                                                 PageSnapshot.status_code == 200).limit(2000)).all()
    bad = [p for p in rows if not (p.cache_lifetime or 0) > 0]
    return {"checked": len(rows), "uncacheable": len(bad),
            "assets": [{"url": p.url, "type": p.content_type, "size_bytes": p.size_bytes,
                        "cache_lifetime": p.cache_lifetime, "cache_flags": p.cache_type_flags} for p in bad[:limit]],
            "note": "Cache lifetime comes from Cache-Control max-age / Expires recorded during the crawl."}


@router.get("/domains/{domain_id}/ai-crawlers")
def ai_crawler_access(domain: Domain = Depends(get_domain), db: Session = Depends(get_db)):
    """Which AI crawlers the site's robots.txt admits, as read during the last completed crawl.

    Served from the crawl rather than re-fetched per request: robots.txt changes rarely, and a page that
    re-reads a customer's site on every view is a fetch we would be making on their behalf without being asked.
    """
    run = D.latest_crawl_run(db, domain.id)
    if run is None:
        return {"available": False, "reason": "No completed site audit yet — run a crawl first."}
    ai = (run.stats or {}).get("ai_crawlers")
    if not ai:
        return {"available": False, "reason": "The last audit predates the AI crawler check — re-run the crawl.",
                "crawl_run_id": str(run.id), "checked_at": run.finished_at}
    return {"available": True, "crawl_run_id": str(run.id), "checked_at": run.finished_at, **ai}


@router.get("/domains/{domain_id}/performance")
def performance(domain: Domain = Depends(get_domain), db: Session = Depends(get_db)):
    rows = db.scalars(select(PerformanceObservation).where(PerformanceObservation.domain_id == domain.id)
                      .order_by(desc(PerformanceObservation.observed_at)).limit(200)).all()
    return [{"id": str(o.id), "url": o.url, "strategy": o.strategy, "measurement_type": o.measurement_type, "tool_version": o.tool_version,
             "scores": o.scores, "metrics": o.metrics, "audits": o.audits[:10], "observed_at": o.observed_at, "provider_key": o.provider_key} for o in rows]


@router.get("/domains/{domain_id}/search")
def search_performance(domain: Domain = Depends(get_domain), days: int = Query(28, ge=7, le=480), db: Session = Depends(get_db)):
    if not D.gsc_available(db, domain.id):
        return {"available": False, "reason": "Search Console not connected or not synced yet", "property": domain.gsc_property}
    start, end = D.gsc_window(days)
    prev_start, prev_end = D.gsc_window(days * 2)[0], start
    totals = D.gsc_totals(db, domain.id, start, end)
    previous = D.gsc_totals(db, domain.id, prev_start, prev_end)
    last_sync = db.scalar(select(func.max(SearchObservation.collected_at)).where(SearchObservation.domain_id == domain.id))
    data_range = db.execute(select(func.min(SearchObservation.date), func.max(SearchObservation.date)).where(SearchObservation.domain_id == domain.id)).one()
    return {"available": True, "property": domain.gsc_property, "last_sync": last_sync,
            "data_range": {"start": data_range[0], "end": data_range[1]},
            "totals": totals, "previous": previous, "daily": D.gsc_daily(db, domain.id, days),
            "top_pages": D.gsc_top_pages(db, domain.id, days, 25), "top_queries": D.gsc_top_queries(db, domain.id, days, 50),
            "query_pages": [{k: v for k, v in r.items() if k != "ids"} for r in D.gsc_query_page_rows(db, domain.id, days, 1, 200)],
            "definitions": {"clicks": "Google Search Console clicks (first-party)", "impressions": "GSC impressions (first-party)",
                            "ctr": "clicks / impressions", "position": "impression-weighted average position"}}


@router.get("/domains/{domain_id}/search/bing")
def bing_search_performance(domain: Domain = Depends(get_domain), days: int = Query(28, ge=7, le=480),
                            db: Session = Depends(get_db)):
    """First-party Bing performance, reported separately from Google rather than summed with it.

    Keeping them apart is the point: a combined "clicks" figure would hide which engine moved, and Bing's query
    and page figures are rolling-window aggregates that cannot be added to a per-day Google series anyway. The
    `aggregate_window` note says so in the response, so a caller cannot mistake one for the other.
    """
    B = BingSearchObservation
    if not db.scalar(select(func.count()).select_from(B).where(B.domain_id == domain.id)):
        return {"available": False, "reason": "Bing Webmaster Tools not connected or not synced yet",
                "site_url": domain.bing_site_url}
    start, end = D.gsc_window(days)
    daily = [{"date": r[0], "clicks": r[1], "impressions": r[2]} for r in db.execute(
        select(B.date, func.sum(B.clicks), func.sum(B.impressions))
        .where(B.domain_id == domain.id, B.dataset == "rank_traffic", B.date >= start, B.date <= end)
        .group_by(B.date).order_by(B.date)).all()]
    totals = {"clicks": sum(d["clicks"] for d in daily), "impressions": sum(d["impressions"] for d in daily)}
    totals["ctr"] = round(totals["clicks"] / totals["impressions"], 6) if totals["impressions"] else 0.0

    def _rows(dataset: str, column, limit: int):
        return [{"key": r[0], "clicks": r[1], "impressions": r[2], "position": round(r[3] or 0, 2)} for r in db.execute(
            select(column, func.sum(B.clicks), func.sum(B.impressions), func.avg(B.position))
            .where(B.domain_id == domain.id, B.dataset == dataset, column != "")
            .group_by(column).order_by(desc(func.sum(B.impressions))).limit(limit)).all()]

    last_sync = db.scalar(select(func.max(B.collected_at)).where(B.domain_id == domain.id))
    aggregate_as_of = db.scalar(select(func.max(B.date)).where(B.domain_id == domain.id, B.dataset != "rank_traffic"))
    return {"available": True, "site_url": domain.bing_site_url, "last_sync": last_sync,
            "totals": totals, "daily": daily,
            "top_queries": _rows("query_stats", B.query, 50), "top_pages": _rows("page_stats", B.page, 25),
            "aggregate_window": {
                "as_of": aggregate_as_of,
                "note": "Bing's API returns query and page figures only as totals over its own rolling window, "
                        "not per day, so they are stamped with the last date Bing reported traffic for. They "
                        "describe a period, not that date, and must not be added to the daily series."},
            "definitions": {"clicks": "Bing Webmaster Tools clicks (first-party)",
                            "impressions": "Bing impressions (first-party)", "ctr": "clicks / impressions",
                            "position": "average of Bing's AvgImpressionPosition"}}


@router.get("/domains/{domain_id}/search/compare")
def search_compare(domain: Domain = Depends(get_domain), start_a: date = Query(...), end_a: date = Query(...),
                   start_b: date = Query(...), end_b: date = Query(...), db: Session = Depends(get_db)):
    return {"a": D.gsc_totals(db, domain.id, start_a, end_a), "b": D.gsc_totals(db, domain.id, start_b, end_b)}


# ------------------------------------------------------------------ backlinks
@router.get("/domains/{domain_id}/backlinks")
def backlinks(domain: Domain = Depends(get_domain), limit: int = Query(500, le=2000), db: Session = Depends(get_db)):
    """Referring domains from the latest snapshot, with the trend and what changed since the previous snapshot."""
    from app.tasks.backlinks import connected_provider

    provider = db.scalar(select(ReferringDomain.provider_key).where(ReferringDomain.domain_id == domain.id)
                         .order_by(desc(ReferringDomain.observed_on)).limit(1))
    if provider is None:
        return {"available": False, "connected_provider": connected_provider(db, domain.project_id),
                "reason": "No backlink data yet. Connect a provider under Integrations → Backlinks, then run a sync."}
    days = db.scalars(select(ReferringDomain.observed_on).where(ReferringDomain.domain_id == domain.id,
                                                                ReferringDomain.provider_key == provider)
                      .group_by(ReferringDomain.observed_on).order_by(desc(ReferringDomain.observed_on)).limit(2)).all()
    latest = days[0]
    rows = db.scalars(select(ReferringDomain).where(ReferringDomain.domain_id == domain.id,
                                                    ReferringDomain.provider_key == provider,
                                                    ReferringDomain.observed_on == latest)
                      .order_by(desc(ReferringDomain.backlinks)).limit(limit)).all()
    previous_hosts: set[str] = set()
    if len(days) > 1:
        previous_hosts = set(db.scalars(select(ReferringDomain.referring_domain)
                                        .where(ReferringDomain.domain_id == domain.id,
                                               ReferringDomain.provider_key == provider,
                                               ReferringDomain.observed_on == days[1])).all())
    current_hosts = {r.referring_domain for r in rows}
    history = db.execute(select(ReferringDomain.observed_on, func.count(), func.sum(ReferringDomain.backlinks))
                         .where(ReferringDomain.domain_id == domain.id, ReferringDomain.provider_key == provider)
                         .group_by(ReferringDomain.observed_on).order_by(ReferringDomain.observed_on)).all()
    profile_history = db.scalars(select(BacklinkProfileSnapshot).where(
        BacklinkProfileSnapshot.domain_id == domain.id, BacklinkProfileSnapshot.provider_key == provider)
        .order_by(BacklinkProfileSnapshot.observed_on)).all()
    total_links = sum(r.backlinks for r in rows)
    dofollow = sum(r.dofollow for r in rows)
    profile = db.scalar(select(BacklinkProfileSnapshot).where(
        BacklinkProfileSnapshot.domain_id == domain.id, BacklinkProfileSnapshot.provider_key == provider,
        BacklinkProfileSnapshot.observed_on == latest))
    rated = [r.domain_rating for r in rows if r.domain_rating is not None]
    return {
        "available": True, "provider": provider, "observed_on": latest.isoformat(),
        "previous_observed_on": days[1].isoformat() if len(days) > 1 else None,
        "totals": {"referring_domains": profile.referring_domains if profile and profile.referring_domains is not None else len(rows),
                   "backlinks": profile.backlinks if profile and profile.backlinks is not None else total_links,
                   "dofollow": profile.dofollow if profile and profile.dofollow is not None else dofollow,
                   "dofollow_share": ((profile.dofollow / profile.backlinks) if profile and profile.dofollow is not None and profile.backlinks else
                                       ((dofollow / total_links) if total_links else 0.0)),
                   "avg_domain_rating": profile.authority_score if profile and profile.authority_score is not None else ((sum(rated) / len(rated)) if rated else None),
                   "gained": len(current_hosts - previous_hosts) if previous_hosts else 0,
                   "lost": len(previous_hosts - current_hosts) if previous_hosts else 0},
        "sample": {"backlinks": profile.sampled_backlinks, "referring_domains": profile.sampled_referring_domains,
                   "note": profile.note} if profile else None,
        "history": ([{"date": p.observed_on.isoformat(), "referring_domains": int(p.referring_domains or 0),
                      "backlinks": int(p.backlinks or 0)} for p in profile_history] if profile_history else
                    [{"date": d.isoformat(), "referring_domains": int(n or 0), "backlinks": int(b or 0)}
                     for d, n, b in history]),
        "domains": [{"referring_domain": r.referring_domain, "backlinks": r.backlinks, "dofollow": r.dofollow,
                     "domain_rating": r.domain_rating, "first_seen": r.first_seen, "last_seen": r.last_seen,
                     "example_url": r.example_url, "is_new": r.referring_domain not in previous_hosts if previous_hosts else False}
                    for r in rows],
        "definitions": {"referring_domains": "Distinct domains linking to the site, as this provider's index sees them",
                        "dofollow_share": "dofollow links / all links",
                        "gained": "Domains present in the latest snapshot but not the previous one"},
    }


@router.get("/domains/{domain_id}/backlinks/links")
def backlink_links(domain: Domain = Depends(get_domain), q: str | None = None, dofollow: bool | None = None,
                   referring_domain: str | None = None, limit: int = Query(500, le=2000),
                   db: Session = Depends(get_db)):
    """Individual links, plus the same links folded by referring domain.

    `links` is the flat list the Backlinks view renders; `groups` is the per-domain roll-up. Both honour the same
    `q`/`dofollow` filters, and `referring_domain` narrows the flat list to a single linking site.
    """
    where = [Backlink.domain_id == domain.id]
    if q:
        like = f"%{q.lower()}%"
        where.append(func.lower(Backlink.referring_domain).like(like)
                     | func.lower(func.coalesce(Backlink.anchor, "")).like(like)
                     | func.lower(Backlink.url_from).like(like))
    if dofollow is not None:
        where.append(Backlink.dofollow.is_(dofollow))

    grouped = db.execute(
        select(Backlink.referring_domain, func.count(), func.count().filter(Backlink.dofollow.is_(True)),
               func.count(func.distinct(Backlink.anchor)), func.max(Backlink.domain_rating),
               func.min(Backlink.first_seen), func.max(Backlink.last_seen))
        .where(*where).group_by(Backlink.referring_domain)
        .order_by(desc(func.count()), Backlink.referring_domain).limit(limit)).all()

    # Most common anchor per domain, so a folded row still shows what the links actually say.
    anchor_counts = db.execute(
        select(Backlink.referring_domain, Backlink.anchor, func.count())
        .where(*where, Backlink.anchor.is_not(None)).group_by(Backlink.referring_domain, Backlink.anchor)
        .order_by(Backlink.referring_domain, desc(func.count()))).all()
    top_anchor: dict[str, str] = {}
    for host, anchor, _n in anchor_counts:
        top_anchor.setdefault(host, anchor)

    # The flat list of individual links, filtered the same way as the groups. Returned for the whole result set,
    # narrowed to one site only when `referring_domain` is given.
    link_where = list(where)
    if referring_domain:
        link_where.append(Backlink.referring_domain == referring_domain)
    rows = db.scalars(select(Backlink).where(*link_where)
                      .order_by(Backlink.domain_rating.desc().nullslast(), Backlink.referring_domain, Backlink.url_from)
                      .limit(limit)).all()
    links = [{"url_from": b.url_from, "url_to": b.url_to, "referring_domain": b.referring_domain,
              "anchor": b.anchor, "page_title": b.page_title, "dofollow": b.dofollow,
              "domain_rating": b.domain_rating, "first_seen": b.first_seen, "last_seen": b.last_seen}
             for b in rows]

    total, follow = db.execute(select(func.count(), func.count().filter(Backlink.dofollow.is_(True)))
                               .where(Backlink.domain_id == domain.id)).one()
    return {
        "available": bool(total),
        "totals": {"links": int(total or 0), "dofollow": int(follow or 0),
                   "nofollow": int((total or 0) - (follow or 0)),
                   "referring_domains": len(grouped),
                   "distinct_anchors": db.scalar(select(func.count(func.distinct(Backlink.anchor)))
                                                 .where(Backlink.domain_id == domain.id)) or 0},
        "groups": [{"referring_domain": host, "links": int(n), "dofollow": int(df), "nofollow": int(n) - int(df),
                    "distinct_anchors": int(anchors), "domain_rating": dr, "first_seen": first, "last_seen": last,
                    "top_anchor": top_anchor.get(host)}
                   for host, n, df, anchors, dr, first, last in grouped],
        "links": links,
        "top_anchors": [{"anchor": a, "links": int(n)} for a, n in db.execute(
            select(Backlink.anchor, func.count()).where(Backlink.domain_id == domain.id, Backlink.anchor.is_not(None))
            .group_by(Backlink.anchor).order_by(desc(func.count())).limit(15)).all()],
    }


# ------------------------------------------------------------------ keyword & SERP data
def _latest_day(db: Session, model, *filters):
    return db.scalar(select(model.observed_on).where(*filters).order_by(desc(model.observed_on)).limit(1))


@router.get("/keyword-metrics")
def keyword_metrics(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Target keywords with the most recent volume/difficulty/CPC, and the change since the previous snapshot."""
    from app.tasks.search_data import connected_provider

    latest = _latest_day(db, KeywordMetric, KeywordMetric.project_id == project.id)
    if latest is None:
        return {"available": False, "connected_provider": connected_provider(db, project.id, "keyword_metrics"),
                "reason": "No keyword data yet. Connect a provider that prices keywords under Integrations → "
                          "Keyword & SERP data, then sync."}
    days = db.scalars(select(KeywordMetric.observed_on).where(KeywordMetric.project_id == project.id)
                      .group_by(KeywordMetric.observed_on).order_by(desc(KeywordMetric.observed_on)).limit(2)).all()
    previous = {k: v for k, v in db.execute(
        select(KeywordMetric.keyword_id, KeywordMetric.search_volume)
        .where(KeywordMetric.project_id == project.id, KeywordMetric.observed_on == days[1])).all()} if len(days) > 1 else {}

    rows = db.execute(select(Keyword, KeywordMetric)
                      .join(KeywordMetric, KeywordMetric.keyword_id == Keyword.id)
                      .where(KeywordMetric.project_id == project.id, KeywordMetric.observed_on == latest)
                      .order_by(KeywordMetric.search_volume.desc().nullslast())).all()
    provider = rows[0][1].provider_key if rows else None
    volumes = [m.search_volume for _k, m in rows if m.search_volume is not None]
    return {
        "available": True, "provider": provider, "observed_on": latest.isoformat(),
        "previous_observed_on": days[1].isoformat() if len(days) > 1 else None,
        "totals": {"keywords": len(rows), "total_volume": sum(volumes),
                   "avg_difficulty": (sum(m.difficulty for _k, m in rows if m.difficulty is not None)
                                      / max(1, sum(1 for _k, m in rows if m.difficulty is not None))) if rows else None,
                   "unpriced": db.scalar(select(func.count()).select_from(Keyword)
                                         .where(Keyword.project_id == project.id, Keyword.is_target.is_(True))) - len(rows)},
        "keywords": [{"id": str(k.id), "text": k.text, "importance": k.importance, "country": k.country,
                      "language": k.language, "search_volume": m.search_volume, "difficulty": m.difficulty,
                      "cpc": m.cpc, "competition": m.competition, "intent": m.intent,
                      "volume_change": (m.search_volume - previous[k.id])
                                       if (k.id in previous and m.search_volume is not None and previous[k.id] is not None) else None}
                     for k, m in rows],
    }


@router.get("/keyword-gap")
def keyword_gap(project: Project = Depends(get_project), only_gaps: bool = True, exclude_branded: bool = True,
                limit: int = Query(500, le=2000), db: Session = Depends(get_db)):
    """Keywords competitors rank for, with your position beside theirs. A gap is where they rank and you do not."""
    from app.tasks.search_data import connected_provider

    latest = _latest_day(db, RankedKeyword, RankedKeyword.project_id == project.id)
    if latest is None:
        return {"available": False, "connected_provider": connected_provider(db, project.id, "ranked_keywords"),
                "reason": "No ranking data yet. Connect a provider that lists what a domain ranks for, then run "
                          "“Sync ranked keywords”."}
    rows = db.scalars(select(RankedKeyword).where(RankedKeyword.project_id == project.id,
                                                  RankedKeyword.observed_on == latest)).all()
    own_hosts = sorted({r.host for r in rows if r.is_own})
    comp_hosts = sorted({r.host for r in rows if not r.is_own})
    mine: dict[str, Any] = {}
    theirs: dict[str, dict[str, Any]] = {}
    volume: dict[str, int | None] = {}
    for r in rows:
        volume.setdefault(r.keyword, r.search_volume)
        if r.search_volume is not None:
            volume[r.keyword] = max(volume[r.keyword] or 0, r.search_volume)
        if r.is_own:
            if r.keyword not in mine or r.position < mine[r.keyword]["position"]:
                mine[r.keyword] = {"position": r.position, "url": r.url}
        else:
            theirs.setdefault(r.keyword, {})[r.host] = r.position

    # A competitor's own brand name is not an opportunity, so it is flagged rather than silently dropped.
    brand_terms = {t.lower() for c in db.scalars(select(Competitor).where(Competitor.project_id == project.id)).all()
                   for t in ([c.name] + list(c.aliases or [])) if t and len(t) > 2}
    brand_terms |= {h.split(".")[0] for h in comp_hosts if len(h.split(".")[0]) > 2}

    def is_branded(kw: str) -> bool:
        words = set(kw.split())
        return any(term in words or (" " in term and term in kw) for term in brand_terms)

    keywords = []
    for kw, by_host in theirs.items():
        my = mine.get(kw)
        if only_gaps and my is not None:
            continue
        branded = is_branded(kw)
        if exclude_branded and branded:
            continue
        keywords.append({"keyword": kw, "search_volume": volume.get(kw), "branded": branded,
                         "your_position": my["position"] if my else None, "your_url": my["url"] if my else None,
                         "competitors": by_host, "best_competitor_position": min(by_host.values()),
                         "competitors_ranking": len(by_host)})
    # Biggest prize first: high volume, and keywords several competitors already win.
    keywords.sort(key=lambda k: (-(k["search_volume"] or 0), k["best_competitor_position"]))
    return {
        "available": True, "observed_on": latest.isoformat(),
        "own_hosts": own_hosts, "competitor_hosts": comp_hosts,
        "totals": {"competitor_keywords": len(theirs), "your_keywords": len(mine),
                   "gaps": sum(1 for k in theirs if k not in mine),
                   "gap_volume": sum(volume.get(k) or 0 for k in theirs if k not in mine),
                   "branded_excluded": sum(1 for k in theirs if k not in mine and is_branded(k)),
                   "shown": len(keywords)},
        "keywords": keywords[:limit],
    }


@router.get("/domains/{domain_id}/rankings")
def rankings(domain: Domain = Depends(get_domain), provider_key: str | None = None, db: Session = Depends(get_db)):
    """Tracked keyword positions on one search engine, with movement since the previous check.

    One engine at a time, deliberately. Positions from different engines are different facts about different
    result pages, so pooling them would double every count and make the average position meaningless. The engines
    that have data are listed in `providers` so the caller can switch; the default is the most recently measured.
    """
    from app.tasks.search_data import connected_provider

    providers = [k for k in db.scalars(
        select(RankObservation.provider_key).where(RankObservation.domain_id == domain.id)
        .group_by(RankObservation.provider_key)
        .order_by(desc(func.max(RankObservation.observed_on)), desc(func.count()))).all()]
    if not providers:
        return {"available": False, "providers": [], "connected_provider": connected_provider(db, domain.project_id, "rank_tracking"),
                "reason": "No rank checks yet. Connect a provider that checks live SERPs (DataForSEO or SerpApi), "
                          "then run “Check rankings”."}
    chosen = provider_key if provider_key in providers else providers[0]

    def engine_rows(prov):
        """Latest-day keyword rows for one engine, plus that engine's previous-day positions for movement."""
        scoped = (RankObservation.domain_id == domain.id, RankObservation.provider_key == prov)
        days = db.scalars(select(RankObservation.observed_on).where(*scoped)
                          .group_by(RankObservation.observed_on)
                          .order_by(desc(RankObservation.observed_on)).limit(2)).all()
        if not days:
            return [], {}, []
        before = {k: p for k, p in db.execute(
            select(RankObservation.keyword_id, RankObservation.position)
            .where(*scoped, RankObservation.observed_on == days[1])).all()} if len(days) > 1 else {}
        rows = db.execute(select(Keyword, RankObservation)
                          .join(RankObservation, RankObservation.keyword_id == Keyword.id)
                          .where(*scoped, RankObservation.observed_on == days[0])
                          .order_by(RankObservation.position.nullslast())).all()
        return days, before, rows

    def serialize(prov, before, rows):
        return [{"id": str(k.id), "engine": prov, "text": k.text, "position": r.position, "url": r.url,
                 "serp_features": r.serp_features,
                 # A keyword that was absent and now ranks has no numeric delta, so it is flagged instead.
                 "change": (before[k.id] - r.position) if (k.id in before and before[k.id] and r.position) else None,
                 "is_new": k.id in before and not before[k.id] and bool(r.position),
                 "lost": k.id in before and bool(before[k.id]) and not r.position}
                for k, r in rows]

    # The table lists every engine's keywords together (each row tagged with its engine), while the summary
    # metrics and the history chart stay scoped to the chosen engine — positions from different engines are
    # different result pages, so pooling their counts or averaging their positions would be meaningless.
    keywords = []
    for prov in providers:
        _d, before, rows = engine_rows(prov)
        keywords.extend(serialize(prov, before, rows))

    days, _before, chosen_rows = engine_rows(chosen)
    ranked = [r for _k, r in chosen_rows if r.position]
    chosen_scoped = (RankObservation.domain_id == domain.id, RankObservation.provider_key == chosen)
    history = db.execute(
        select(RankObservation.observed_on, func.count().filter(RankObservation.position.is_not(None)),
               func.avg(RankObservation.position))
        .where(*chosen_scoped)
        .group_by(RankObservation.observed_on).order_by(RankObservation.observed_on)).all()
    return {
        "available": True, "observed_on": days[0].isoformat(), "provider": chosen, "providers": providers,
        "previous_observed_on": days[1].isoformat() if len(days) > 1 else None,
        "totals": {"checked": len(chosen_rows), "ranking": len(ranked), "absent": len(chosen_rows) - len(ranked),
                   "top_10": sum(1 for r in ranked if r.position <= 10),
                   "avg_position": (sum(r.position for r in ranked) / len(ranked)) if ranked else None},
        "history": [{"date": d.isoformat(), "ranking": int(n or 0), "avg_position": float(a) if a else None}
                    for d, n, a in history],
        "keywords": keywords,
    }
