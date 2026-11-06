"""AI visibility sampling: run prompts against every configured AI provider with repeated samples.

Each sample is stored as an AIAnswerObservation (never overwritten) with full provenance: provider, model,
model version reported by the API, locale, request configuration, grounding, citations and latency.
"""
from __future__ import annotations

import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import func, select

from app.adapters.ai.common import AIAnswer
from app.adapters.base import ProviderError
from app.models import AIAnswerMention, AIAnswerObservation, Competitor, Domain, Project, PromptDefinition
from app.services.providers import (ProviderNotConfigured, build_adapter, connection_features,
                                     list_connections_for, record_usage, usage_tokens)
from app.services.text_analysis import extract_mentions
from app.tasks.context import TaskContext
from app.services.usage import BudgetExceeded, check_budget
from app.tasks.registry import task

def can_sample(conn: Any) -> bool:
    """Whether a connection can answer a prompt for us.

    A declared capability rather than a hardcoded list, because the `ai` category now holds two different kinds of
    provider: model APIs (OpenAI, Gemini, …) and scraped consumer surfaces (Google AI Overview, AI Mode, Bing
    Copilot) via SerpApi. Both produce an answer and a citation list, which is all sampling needs. The analyst and
    the content generator keep their own allowlists — they need tool calling, which is a different contract.
    """
    return "answer_sampling" in connection_features(conn)


@task("run_ai_visibility", "Run GEO AI visibility prompts against configured AI providers (repeated samples)")
def run_ai_visibility(ctx: TaskContext) -> dict[str, Any]:
    project = ctx.db.get(Project, ctx.project_id)
    if project is None:
        raise ValueError("Brand not found")
    prompt_ids = [uuid.UUID(p) for p in ctx.params.get("prompt_ids", [])]
    stmt = select(PromptDefinition).where(PromptDefinition.project_id == project.id, PromptDefinition.is_active.is_(True))
    if prompt_ids:
        stmt = stmt.where(PromptDefinition.id.in_(prompt_ids))
    prompts = ctx.db.scalars(stmt).all()
    if not prompts:
        raise ValueError("No active prompts to run. Add prompts under GEO AI Visibility.")
    check_budget(ctx.db, project)

    wanted = set(ctx.params.get("provider_keys") or [])
    connections = [c for c in list_connections_for(ctx.db, project.id, "ai")
                   if can_sample(c) and (not wanted or c.provider_key in wanted)]
    if not connections:
        raise ProviderNotConfigured("No AI provider is configured. Add OpenAI, Gemini or another provider under Integrations.")

    competitors = ctx.db.scalars(select(Competitor).where(Competitor.project_id == project.id)).all()
    comp_lookup = {c.name: c.id for c in competitors}
    own_domains = {d.hostname.lower().removeprefix("www.") for d in
                   ctx.db.scalars(select(Domain).where(Domain.project_id == project.id, Domain.role == "primary")).all()}
    run_id = uuid.uuid4()
    samples_override = ctx.params.get("samples")

    work: list[tuple[PromptDefinition, Any, int]] = []
    adapters = {c.id: build_adapter(c) for c in connections}
    for p in prompts:
        n = int(samples_override or p.samples_per_run or 1)
        for c in connections:
            for i in range(n):
                work.append((p, c, i))
    ctx.log(f"Sampling {len(prompts)} prompt(s) × {len(connections)} provider(s): {len(work)} calls")

    def call(item: tuple[PromptDefinition, Any, int]) -> tuple[Any, AIAnswer | None, Any, str | None]:
        p, c, i = item
        adapter = adapters[c.id]
        try:
            res = adapter.collect({"prompt": p.text, "language": p.language, "country": p.country, "samples": 1})
            return item, adapter.normalize(res), res, None
        except (ProviderError, Exception) as exc:  # noqa: BLE001
            return item, None, None, str(exc)[:1000]

    done = 0
    errors = 0
    saved = 0
    with ThreadPoolExecutor(max_workers=int(ctx.params.get("concurrency", 4))) as pool:
        for (p, c, i), answer, res, err in pool.map(call, work):
            done += 1
            ctx.progress(int(95 * done / len(work)), f"{c.provider_key}: {p.text[:60]} (sample {i + 1})")
            obs = AIAnswerObservation(project_id=project.id, prompt_id=p.id, job_id=ctx.job.id, run_id=run_id,
                                      sample_index=i, provider_key=c.provider_key, connection_id=c.id,
                                      model=answer.model if answer else (c.config.get("model") or "unknown"),
                                      model_version=answer.model_version if answer else None,
                                      language=p.language, country=p.country)
            if err or answer is None:
                errors += 1
                obs.error = err
                obs.request_config = {}
                ctx.db.add(obs)
                ctx.db.commit()
                continue
            artifact = ctx.save_artifact(c.provider_key, "ai_answer", answer.raw, meta={"prompt_id": str(p.id), "sample": i})
            obs.artifact_id = artifact.id
            obs.request_config = answer.request_config
            obs.grounded = answer.grounded
            obs.grounding_type = answer.grounding_type
            obs.answer_text = answer.text
            obs.citations = [{"url": ci.url, "domain": ci.domain, "title": ci.title} for ci in answer.citations]
            obs.own_domain_cited = any(ci.domain in own_domains for ci in answer.citations)
            obs.usage = answer.usage
            obs.latency_ms = answer.latency_ms
            obs.answer_hash = hashlib.sha256(answer.text.encode()).hexdigest()
            mentions = extract_mentions(answer.text, (project.brand_name, project.brand_aliases or []),
                                        [(co.name, co.aliases or []) for co in competitors])
            brand = next((m for m in mentions if m.entity_type == "brand"), None)
            obs.brand_mentioned = brand is not None
            obs.brand_position = brand.position if brand else None
            obs.sentiment = brand.sentiment if brand else None
            ctx.db.add(obs)
            ctx.db.flush()
            for m in mentions:
                ctx.db.add(AIAnswerMention(observation_id=obs.id, project_id=project.id, entity_type=m.entity_type,
                                           entity_name=m.entity_name, competitor_id=comp_lookup.get(m.entity_name),
                                           position=m.position, list_rank=m.list_rank, mention_count=m.mention_count,
                                           sentiment=m.sentiment, context_snippet=m.context_snippet))
            tin, tout = usage_tokens(answer.usage)
            # Model APIs bill tokens; a scraped surface bills whole searches and reports no tokens at all. Recording
            # tokens for the latter would log every AI Overview run as costing nothing.
            searches = int(answer.usage.get("searches") or 0) if not (tin or tout) else 0
            record_usage(ctx.db, project_id=project.id, provider_key=c.provider_key, operation="ai_visibility_sample",
                         connection_id=c.id, job_id=ctx.job.id,
                         units=searches if searches else tin + tout,
                         unit_type="requests" if searches else "tokens",
                         tokens_in=tin, tokens_out=tout, details={"model": answer.model})
            saved += 1
            ctx.db.commit()
    # An AI surface that shows no answer for a prompt is a measurement, not a failure: "Google ran no AI Overview
    # here" is exactly what a GEO report needs to say. It is counted separately so it cannot be read as an error.
    empty = ctx.db.scalar(select(func.count()).select_from(AIAnswerObservation)
                          .where(AIAnswerObservation.run_id == run_id, AIAnswerObservation.error.is_(None),
                                 func.coalesce(AIAnswerObservation.answer_text, "") == "")) or 0
    return {"run_id": str(run_id), "prompts": len(prompts), "providers": [c.provider_key for c in connections],
            "samples_saved": saved, "no_answer_shown": int(empty), "errors": errors}
