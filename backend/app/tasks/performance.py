"""Lighthouse (PageSpeed Insights) and CrUX measurements for important URLs."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from app.adapters.base import ProviderError
from app.models import Domain, PerformanceObservation, SearchObservation
from app.services.providers import get_adapter, record_usage
from app.tasks.context import TaskContext
from app.tasks.registry import task


def important_urls(ctx: TaskContext, domain: Domain, limit: int) -> list[str]:
    """Home page + top landing pages by clicks (GSC) if available."""
    urls = [domain.base_url]
    rows = ctx.db.execute(select(SearchObservation.page, func.sum(SearchObservation.clicks).label("c"))
                          .where(SearchObservation.domain_id == domain.id, SearchObservation.page != "")
                          .group_by(SearchObservation.page).order_by(func.sum(SearchObservation.clicks).desc()).limit(limit)).all()
    for page, _ in rows:
        if page not in urls:
            urls.append(page)
    return urls[:limit]


@task("measure_performance", "Run Lighthouse (via PageSpeed Insights) on key pages")
def measure_performance(ctx: TaskContext) -> dict[str, Any]:
    domain = ctx.db.get(Domain, uuid.UUID(ctx.params["domain_id"]))
    if domain is None:
        raise ValueError("Domain not found")
    urls = ctx.params.get("urls") or important_urls(ctx, domain, int(ctx.params.get("limit", 5)))
    strategy = ctx.params.get("strategy", "mobile")
    adapter, conn = get_adapter(ctx.db, ctx.project_id, "pagespeed_insights")
    saved, errors = 0, []
    for i, url in enumerate(urls):
        ctx.progress(int(100 * i / max(1, len(urls))), f"Measuring {url}")
        try:
            result = adapter.collect({"url": url, "strategy": strategy})
        except ProviderError as exc:
            errors.append({"url": url, "error": str(exc)})
            ctx.log(f"{url}: {exc}", "warning")
            continue
        artifact = ctx.save_artifact("pagespeed_insights", "lighthouse", result.raw, meta=result.meta)
        for obs in adapter.normalize(result):
            ctx.db.add(PerformanceObservation(project_id=domain.project_id, domain_id=domain.id, job_id=ctx.job.id,
                                              artifact_id=artifact.id, provider_key="pagespeed_insights", url=url,
                                              strategy=strategy, measurement_type=obs["measurement_type"],
                                              tool_version=obs.get("tool_version"), scores=obs["scores"],
                                              metrics=obs["metrics"], audits=obs["audits"]))
            saved += 1
        record_usage(ctx.db, project_id=domain.project_id, provider_key="pagespeed_insights", operation="runPagespeed",
                     job_id=ctx.job.id, connection_id=conn.id if conn else None)
        ctx.db.commit()
    return {"urls": len(urls), "observations": saved, "errors": errors}
