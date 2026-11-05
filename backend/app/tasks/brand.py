"""Brand & competitor mention monitoring across authorized sources (RSS, Hacker News, Bluesky)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.adapters.base import ProviderError
from app.models import BrandMention, Competitor, Project
from app.services.providers import (build_adapter, build_connectionless_adapter, connection_features,
                                     list_connections_for, record_usage)
from app.services.text_analysis import DEFAULT_TOPICS, classify_topics, detect_intent, extract_mentions
from app.tasks.context import TaskContext
from app.tasks.registry import task

CONNECTIONLESS_SOURCES = ("hackernews", "bluesky")


@task("monitor_brand_mentions", "Collect brand and competitor mentions from configured sources")
def monitor_brand_mentions(ctx: TaskContext) -> dict[str, Any]:
    project = ctx.db.get(Project, ctx.project_id)
    if project is None:
        raise ValueError("Project not found")
    competitors = ctx.db.scalars(select(Competitor).where(Competitor.project_id == project.id)).all()
    comp_lookup = {c.name: c.id for c in competitors}
    queries = [project.brand_name, *[a for a in (project.brand_aliases or []) if len(a) > 2]] + [c.name for c in competitors]
    queries = list(dict.fromkeys(q for q in queries if q))
    topics = {**DEFAULT_TOPICS, **(project.settings or {}).get("topics", {})}

    sources: list[tuple[str, Any, Any]] = []
    wanted = set(ctx.params.get("provider_keys") or [])
    for key in CONNECTIONLESS_SOURCES:
        if not wanted or key in wanted:
            sources.append((key, build_connectionless_adapter(key), None))
    for conn in list_connections_for(ctx.db, project.id, "brand"):
        # Any brand provider that declares it finds mentions takes part, so adding a source is registering an
        # adapter rather than also remembering to extend a list here.
        if "mentions" not in connection_features(conn) or (wanted and conn.provider_key not in wanted):
            continue
        if conn.provider_key in CONNECTIONLESS_SOURCES:
            # a configured connection (e.g. Bluesky with app password) replaces the keyless default
            sources = [s for s in sources if s[0] != conn.provider_key] + [(conn.provider_key, build_adapter(conn), conn)]
        else:
            sources.append((conn.provider_key, build_adapter(conn), conn))

    inserted = 0
    scanned = 0
    errors: list[dict[str, str]] = []
    for idx, (key, adapter, conn) in enumerate(sources):
        ctx.progress(int(90 * idx / max(1, len(sources))), f"Collecting from {key}")
        try:
            result = adapter.collect({"queries": queries})
        except ProviderError as exc:
            errors.append({"source": key, "error": str(exc)})
            ctx.log(f"{key}: {exc}", "warning")
            continue
        artifact = ctx.save_artifact(key, "brand_mentions", result.raw, meta=result.meta)
        items = adapter.normalize(result)
        scanned += len(items)
        for it in items:
            text = " ".join(x for x in (it.get("title"), it.get("content")) if x)
            mentions = extract_mentions(text, (project.brand_name, project.brand_aliases or []),
                                        [(c.name, c.aliases or []) for c in competitors])
            for m in mentions:
                row = {"project_id": project.id, "job_id": ctx.job.id, "artifact_id": artifact.id, "provider_key": key,
                       "source_id": it["source_id"][:500], "source_url": it.get("source_url"), "source_name": it.get("source_name"),
                       "title": it.get("title"), "content_excerpt": (m.context_snippet or it.get("content") or "")[:1500],
                       "author": it.get("author"), "published_at": it.get("published_at"), "entity_type": m.entity_type,
                       "entity_name": m.entity_name, "competitor_id": comp_lookup.get(m.entity_name), "sentiment": m.sentiment,
                       "sentiment_method": "lexicon", "topics": classify_topics(text, topics), "intent": detect_intent(text),
                       "engagement": it.get("engagement") or {}, "language": it.get("language")}
                stmt = insert(BrandMention).values(**row).on_conflict_do_nothing(constraint="uq_brand_mention")
                inserted += ctx.db.execute(stmt).rowcount or 0
        # Most sources run one request per tracked query, but not all: TikTok Discover reads the pages it was
        # configured with and ignores the queries entirely, so the adapter's own count wins where it reports one.
        record_usage(ctx.db, project_id=project.id, provider_key=key, operation="search", job_id=ctx.job.id,
                     connection_id=conn.id if conn else None,
                     units=int(result.meta.get("searches") or len(queries)))
        ctx.db.commit()
    return {"sources": [s[0] for s in sources], "queries": queries, "items_scanned": scanned, "new_mentions": inserted, "errors": errors}
