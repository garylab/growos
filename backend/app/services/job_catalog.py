"""Single source of truth for the jobs a user can trigger from the Overview "Run jobs" dialog.

Each entry is tagged `free` (only compute / provider free quota) or `paid` (consumes provider credits or AI tokens),
and is only offered when its prerequisite is met (provider connected, property set, prompts exist). The dialog
defaults free jobs on and paid jobs off, so a careless click never spends credits.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Domain, Project, PromptDefinition
from app.services.providers import list_connections_for
from app.tasks.backlinks import connected_provider as backlinks_provider
from app.tasks.search_data import search_data_connections

FREE, PAID = "free", "paid"


def _primary_domains(db: Session, project: Project) -> list[Domain]:
    return list(db.scalars(select(Domain).where(Domain.project_id == project.id, Domain.role == "primary",
                                                 Domain.is_active.is_(True)).order_by(Domain.created_at)).all())


def build_catalog(db: Session, project: Project) -> list[dict[str, Any]]:
    """Runnable jobs for this project, filtered to what is actually configured."""
    domains = _primary_domains(db, project)
    active_prompts = db.scalar(select(func.count()).select_from(PromptDefinition).where(
        PromptDefinition.project_id == project.id, PromptDefinition.is_active.is_(True))) or 0
    # (task_type, label, cost, scope, available)
    specs = [
        ("crawl_domain", "Website crawl & SEO audit", FREE, "domain", bool(domains)),
        ("measure_performance", "Page speed (Lighthouse / PageSpeed)", FREE, "domain", bool(domains)),
        ("sync_search_console", "Google Search Console", FREE, "domain", any(d.gsc_property for d in domains)),
        ("sync_bing_webmaster", "Bing Webmaster Tools", FREE, "domain", any(d.bing_site_url for d in domains)),
        ("sync_analytics", "Website analytics (GA4)", FREE, "domain", any(d.ga4_property for d in domains)),
        ("build_growth_plan", "Rebuild growth plan", FREE, "project", True),
        ("measure_outcomes", "Re-measure action results", FREE, "project", True),
        ("snapshot_scorecard", "Scorecard snapshot", FREE, "project", True),
        ("run_ai_visibility", "AI visibility sampling (LLM tokens)", PAID, "project",
         bool(list_connections_for(db, project.id, "ai")) and active_prompts > 0),
        ("sync_rankings", "Keyword rankings (SERP credits)", PAID, "project",
         bool(search_data_connections(db, project.id))),
        ("sync_keyword_metrics", "Keyword metrics (credits)", PAID, "project",
         bool(search_data_connections(db, project.id))),
        ("sync_backlinks", "Backlinks (credits)", PAID, "domain",
         backlinks_provider(db, project.id) is not None),
        ("monitor_brand_mentions", "Brand mentions (credits)", PAID, "project",
         bool(list_connections_for(db, project.id, "brand"))),
    ]
    return [{"task_type": t, "label": label, "cost": cost, "scope": scope, "default": cost == FREE}
            for (t, label, cost, scope, available) in specs if available]


def enqueue_selected(db: Session, project: Project, task_types: list[str]) -> list[str]:
    """Enqueue the chosen jobs, expanding domain-scoped ones to each primary domain. Unknown/unavailable keys are
    skipped. An idempotency key per (task, domain) means a double-click will not double-spend on paid providers."""
    from app.queue import get_queue

    catalog = {j["task_type"]: j for j in build_catalog(db, project)}
    domains = _primary_domains(db, project)
    q = get_queue()
    enqueued: list[str] = []
    for t in task_types:
        spec = catalog.get(t)
        if spec is None:
            continue
        if spec["scope"] == "domain":
            for d in domains:
                params: dict[str, Any] = {"domain_id": str(d.id)}
                if t == "sync_search_console":
                    params["days"] = 90
                q.enqueue(db, task_type=t, params=params, project_id=project.id, triggered_by="user",
                          idempotency_key=f"{t}:{project.id}:{d.id}")
                enqueued.append(t)
        else:
            q.enqueue(db, task_type=t, params={}, project_id=project.id, triggered_by="user",
                      idempotency_key=f"{t}:{project.id}")
            enqueued.append(t)
    db.commit()
    return enqueued
