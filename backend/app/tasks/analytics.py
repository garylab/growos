"""Google Analytics 4 sync: daily landing-page sessions/users/conversions/revenue → AnalyticsEvent (first-party)."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from app.adapters.analytics.ga4 import default_window
from app.models import AnalyticsEvent, Domain
from app.services.providers import get_adapter, record_usage
from app.tasks.context import TaskContext
from app.tasks.registry import task


@task("sync_analytics", "Import Google Analytics 4 landing-page sessions, conversions and revenue")
def sync_analytics(ctx: TaskContext) -> dict[str, Any]:
    domain = ctx.db.get(Domain, uuid.UUID(ctx.params["domain_id"]))
    if domain is None:
        raise ValueError("Domain not found")
    if not domain.ga4_property:
        raise ValueError("This domain has no GA4 property configured (set it under Actions & Results → Website analytics)")
    adapter, conn = get_adapter(ctx.db, ctx.project_id, "google_analytics_4")
    days = int(ctx.params.get("days", 28))
    if ctx.params.get("start_date") and ctx.params.get("end_date"):
        start, end = date.fromisoformat(ctx.params["start_date"]), date.fromisoformat(ctx.params["end_date"])
    else:
        start, end = default_window(days)
    ctx.progress(10, f"Querying GA4 {domain.ga4_property} {start} → {end}")
    result = adapter.collect({"property_id": domain.ga4_property, "start_date": start, "end_date": end})
    ctx.save_artifact("google_analytics_4", "ga4_runreport", result.raw, meta=result.meta)
    rows = adapter.normalize(result)
    ctx.progress(60, f"Storing {len(rows)} rows")
    base = domain.base_url.rstrip("/")
    values = []
    for r in rows:
        lp = r["landing_page"]
        landing = lp if lp.startswith("http") else (base + lp if lp.startswith("/") else f"{base}/{lp}")
        values.append({"project_id": domain.project_id, "domain_id": domain.id, "provider_key": "google_analytics_4",
                       **r, "landing_page": landing[:2000]})
    for i in range(0, len(values), 500):
        stmt = insert(AnalyticsEvent).values(values[i:i + 500])
        stmt = stmt.on_conflict_do_update(constraint="uq_analytics_event", set_={
            "sessions": stmt.excluded.sessions, "users": stmt.excluded.users, "conversions": stmt.excluded.conversions,
            "revenue": stmt.excluded.revenue, "engaged_sessions": stmt.excluded.engaged_sessions,
            "engagement_time_sec": stmt.excluded.engagement_time_sec,
            "provider_key": stmt.excluded.provider_key, "collected_at": stmt.excluded.collected_at})
        ctx.db.execute(stmt)
    record_usage(ctx.db, project_id=domain.project_id, provider_key="google_analytics_4", operation="runReport",
                 job_id=ctx.job.id, connection_id=conn.id if conn else None, units=max(1, len(rows) // 100_000 + 1))
    ctx.db.commit()
    return {"rows": len(values), "start_date": start.isoformat(), "end_date": end.isoformat(), "property": domain.ga4_property,
            "conversion_metric": result.meta["conversion_metric"]}
