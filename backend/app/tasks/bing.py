"""Bing Webmaster Tools sync: daily totals plus query and page aggregates, upserted as BingSearchObservation."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from app.adapters.search_performance.bing import DAILY, DATASETS, PAGES, QUERIES, last_reported_date
from app.models import BingSearchObservation, Domain
from app.services.providers import get_adapter, record_usage
from app.tasks.context import TaskContext
from app.tasks.registry import task

PROVIDER = "bing_webmaster"


@task("sync_bing_webmaster", "Import Bing Webmaster Tools performance data (clicks, impressions, position)")
def sync_bing_webmaster(ctx: TaskContext) -> dict[str, Any]:
    domain = ctx.db.get(Domain, uuid.UUID(ctx.params["domain_id"]))
    if domain is None:
        raise ValueError("Domain not found")
    site_url = ctx.params.get("site_url") or domain.bing_site_url
    if not site_url:
        raise ValueError("This domain has no Bing site URL configured. Run the provider's health check to list "
                         "the verified sites, then set the matching one under SEO Performance → Settings.")
    adapter, conn = get_adapter(ctx.db, ctx.project_id, PROVIDER)

    # Daily always runs, and runs first: it is the only dataset with real dates, and its last date is what
    # stamps the undated query/page aggregates. Without it they would be stamped "yesterday" — a date Bing never
    # reported — and would sit alongside the daily series in the wrong place.
    requested = [d for d in (ctx.params.get("datasets") or DATASETS) if d in DATASETS] or list(DATASETS)
    datasets = [DAILY] + [d for d in requested if d != DAILY]

    totals: dict[str, int] = {}
    as_of = None
    for i, dataset in enumerate(datasets):
        ctx.progress(int(90 * i / len(datasets)), f"Bing {dataset}")
        result = adapter.collect({"site_url": site_url, "dataset": dataset})
        ctx.save_artifact(PROVIDER, dataset, result.raw, meta=result.meta)
        if dataset != DAILY and as_of is not None:
            result.meta["as_of"] = as_of.isoformat()
        rows = adapter.normalize(result)
        if dataset == DAILY:
            as_of = last_reported_date(rows)
        totals[dataset] = len(rows)
        if rows:
            values = [{"project_id": domain.project_id, "domain_id": domain.id, "job_id": ctx.job.id,
                       "provider_key": PROVIDER, "site_url": site_url, "dataset": dataset, **r} for r in rows]
            stmt = insert(BingSearchObservation).values(values)
            stmt = stmt.on_conflict_do_update(constraint="uq_bing_search_obs", set_={
                "clicks": stmt.excluded.clicks, "impressions": stmt.excluded.impressions, "ctr": stmt.excluded.ctr,
                "position": stmt.excluded.position, "collected_at": stmt.excluded.collected_at,
                "job_id": stmt.excluded.job_id})
            ctx.db.execute(stmt)
        record_usage(ctx.db, project_id=domain.project_id, provider_key=PROVIDER, operation=dataset,
                     job_id=ctx.job.id, connection_id=conn.id if conn else None)
        ctx.db.commit()
    ctx.progress(100, "Done")
    return {"site_url": site_url, "rows": totals, "as_of": as_of.isoformat() if as_of else None,
            "note": f"Daily rows are per-date. {QUERIES}/{PAGES} rows are Bing's rolling-window aggregates "
                    f"stamped {as_of.isoformat() if as_of else 'n/a'}; Bing's API cannot return them per day."}
