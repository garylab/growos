"""Backlink sync: referring domains from whichever backlink provider is connected → ReferringDomain snapshots."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.adapters.backlinks.common import link_hash
from app.adapters.registry import provider_features, providers_with_feature
from app.models import Backlink, BacklinkProfileSnapshot, Domain, ProviderConnection, ReferringDomain
from app.services.providers import connection_features, get_adapter, record_usage
from app.tasks.context import TaskContext
from app.tasks.registry import task

FEATURE = "referring_domains"


def connected_provider(db, project_id: uuid.UUID) -> str | None:
    """The backlink provider this project should use: project-scoped connections win over global ones.

    Chosen by capability rather than by a hardcoded list, so a custom JSON endpoint configured to return referring
    domains is found here without this module having to know it exists.
    """
    conns = [c for c in db.scalars(select(ProviderConnection).where(ProviderConnection.category == "backlinks")).all()
             if c.project_id in (None, project_id) and c.is_enabled]
    conns.sort(key=lambda c: (c.project_id is None, c.created_at))   # project-scoped first
    return next((c.provider_key for c in conns if FEATURE in connection_features(c)), None)


@task("sync_backlinks", "Import referring domains from the connected backlink provider")
def sync_backlinks(ctx: TaskContext) -> dict[str, Any]:
    domain = ctx.db.get(Domain, uuid.UUID(ctx.params["domain_id"]))
    if domain is None:
        raise ValueError("Domain not found")
    provider = ctx.params.get("provider_key") or connected_provider(ctx.db, domain.project_id)
    if not provider:
        raise ValueError("No backlink provider is connected — add one under Integrations → Backlinks")
    if FEATURE not in provider_features(provider):
        raise ValueError(f"{provider} cannot list referring domains. Providers that can: "
                         f"{', '.join(providers_with_feature(FEATURE))}.")
    adapter, conn = get_adapter(ctx.db, domain.project_id, provider)

    ctx.progress(10, f"Asking {provider} for referring domains of {domain.hostname}")
    result = adapter.collect({"target": domain.hostname, "limit": ctx.params.get("limit")})
    ctx.save_artifact(provider, "referring_domains", result.raw, meta=result.meta)
    rows = adapter.normalize(result)
    ctx.progress(60, f"Storing {len(rows)} referring domain(s)")

    today: date = datetime.now(UTC).date()
    if hasattr(adapter, "profile_totals"):
        profile = adapter.profile_totals(result)
        stmt = insert(BacklinkProfileSnapshot).values(project_id=domain.project_id, domain_id=domain.id,
            provider_key=provider, observed_on=today, **profile)
        stmt = stmt.on_conflict_do_update(constraint="uq_backlink_profile_day", set_={
            "authority_score": stmt.excluded.authority_score, "backlinks": stmt.excluded.backlinks,
            "referring_domains": stmt.excluded.referring_domains, "dofollow": stmt.excluded.dofollow,
            "nofollow": stmt.excluded.nofollow, "sampled_backlinks": stmt.excluded.sampled_backlinks,
            "sampled_referring_domains": stmt.excluded.sampled_referring_domains, "note": stmt.excluded.note,
            "collected_at": stmt.excluded.collected_at})
        ctx.db.execute(stmt)
    values = [{"project_id": domain.project_id, "domain_id": domain.id, "provider_key": provider,
               "observed_on": today, **r} for r in rows]
    for i in range(0, len(values), 500):
        stmt = insert(ReferringDomain).values(values[i:i + 500])
        # Re-running the same day refreshes that day's snapshot rather than failing or duplicating it.
        stmt = stmt.on_conflict_do_update(constraint="uq_referring_domain_day", set_={
            "backlinks": stmt.excluded.backlinks, "dofollow": stmt.excluded.dofollow,
            "domain_rating": stmt.excluded.domain_rating, "first_seen": stmt.excluded.first_seen,
            "last_seen": stmt.excluded.last_seen, "example_url": stmt.excluded.example_url,
            "collected_at": stmt.excluded.collected_at})
        ctx.db.execute(stmt)
    record_usage(ctx.db, project_id=domain.project_id, provider_key=provider, operation="referring_domains",
                 job_id=ctx.job.id, connection_id=conn.id if conn else None, units=1)

    # Individual links are a second, pricier call — skipped when the provider cannot do it or the caller opts out.
    links = 0
    link_error = None
    if ctx.params.get("include_links", True) and hasattr(adapter, "collect_links"):
        try:
            ctx.progress(70, "Fetching individual links")
            link_result = adapter.collect_links({"target": domain.hostname, "limit": ctx.params.get("link_limit")})
            ctx.save_artifact(provider, "backlinks", link_result.raw, meta=link_result.meta)
            link_rows = adapter.normalize_links(link_result)
            link_values = [{"project_id": domain.project_id, "domain_id": domain.id, "provider_key": provider,
                            "observed_on": today, "link_hash": link_hash(r), **r} for r in link_rows]
            for i in range(0, len(link_values), 500):
                stmt = insert(Backlink).values(link_values[i:i + 500])
                stmt = stmt.on_conflict_do_update(constraint="uq_backlink_link", set_={
                    "url_to": stmt.excluded.url_to, "anchor": stmt.excluded.anchor,
                    "page_title": stmt.excluded.page_title, "dofollow": stmt.excluded.dofollow,
                    "domain_rating": stmt.excluded.domain_rating, "first_seen": stmt.excluded.first_seen,
                    "last_seen": stmt.excluded.last_seen, "observed_on": stmt.excluded.observed_on,
                    "collected_at": stmt.excluded.collected_at})
                ctx.db.execute(stmt)
            links = len(link_values)
            record_usage(ctx.db, project_id=domain.project_id, provider_key=provider, operation="backlinks",
                         job_id=ctx.job.id, connection_id=conn.id if conn else None, units=1)
        except Exception as exc:  # noqa: BLE001 — referring domains already succeeded; do not throw that away
            link_error = str(exc)[:300]
            ctx.log(f"Individual links unavailable: {link_error}", level="warning")

    ctx.db.commit()
    return {"provider": provider, "referring_domains": len(values), "backlinks": sum(r["backlinks"] for r in rows),
            "links_stored": links, "links_error": link_error,
            "observed_on": today.isoformat(), "target": domain.hostname}
