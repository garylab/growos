"""Google Search Console sync: query/page/country/device rows per day, upserted as SearchObservation."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from app.adapters.search_performance.gsc import default_window
from app.models import Domain, SearchObservation
from app.services.providers import get_adapter, record_usage
from app.tasks.context import TaskContext
from app.tasks.registry import task


@task("sync_search_console", "Import Search Console performance data (clicks, impressions, CTR, position)")
def sync_search_console(ctx: TaskContext) -> dict[str, Any]:
    domain = ctx.db.get(Domain, uuid.UUID(ctx.params["domain_id"]))
    if domain is None:
        raise ValueError("Domain not found")
    if not domain.gsc_property:
        raise ValueError("This domain has no Search Console property configured (set it under SEO Performance → Settings)")
    adapter, conn = get_adapter(ctx.db, ctx.project_id, "google_search_console")
    days = int(ctx.params.get("days", 28))
    if ctx.params.get("start_date") and ctx.params.get("end_date"):
        start, end = date.fromisoformat(ctx.params["start_date"]), date.fromisoformat(ctx.params["end_date"])
    else:
        start, end = default_window(days)

    total = 0
    dimension_sets = [["date", "query", "page"], ["date", "query", "country", "device"], ["date", "page"]]
    # Chunk by week to respect row limits
    chunks = []
    cur = start
    while cur <= end:
        chunk_end = min(end, cur + timedelta(days=6))
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    steps = len(chunks) * len(dimension_sets)
    step = 0
    for dims in dimension_sets:
        for cs, ce in chunks:
            step += 1
            ctx.progress(int(95 * step / steps), f"{'/'.join(dims)} {cs} → {ce}")
            result = adapter.collect({"property_uri": domain.gsc_property, "start_date": cs, "end_date": ce, "dimensions": dims})
            ctx.save_artifact("google_search_console", "searchanalytics", result.raw, meta=result.meta)
            rows = adapter.normalize(result)
            if rows:
                values = [{"project_id": domain.project_id, "domain_id": domain.id, "job_id": ctx.job.id,
                           "provider_key": "google_search_console", "property_uri": domain.gsc_property, **r} for r in rows]
                # Postgres binds at most 65535 parameters per statement; at 15 columns a single week of
                # query+page data overruns that, so insert in batches well under the limit.
                for i in range(0, len(values), 500):
                    stmt = insert(SearchObservation).values(values[i:i + 500])
                    stmt = stmt.on_conflict_do_update(constraint="uq_search_obs", set_={
                        "clicks": stmt.excluded.clicks, "impressions": stmt.excluded.impressions, "ctr": stmt.excluded.ctr,
                        "position": stmt.excluded.position, "collected_at": stmt.excluded.collected_at, "job_id": stmt.excluded.job_id})
                    ctx.db.execute(stmt)
                total += len(rows)
            record_usage(ctx.db, project_id=domain.project_id, provider_key="google_search_console", operation="searchanalytics.query",
                         job_id=ctx.job.id, connection_id=conn.id if conn else None)
            ctx.db.commit()
    return {"rows": total, "start_date": start.isoformat(), "end_date": end.isoformat(), "property": domain.gsc_property}
