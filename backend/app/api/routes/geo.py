from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import get_project
from app.core.db import get_db
from app.intelligence import data as D
from app.models import AIAnswerMention, AIAnswerObservation, Project, PromptDefinition
from app.queue import get_queue
from app.schemas.common import JobOut
from app.schemas.geo import MentionOut, ObservationOut, PromptIn, PromptOut, PromptUpdate, RunPromptsIn

router = APIRouter(prefix="/projects/{project_id}/geo", tags=["geo"])

METHODOLOGY = {
    "sampling": "Each prompt is sent N times (samples_per_run) to each configured provider through its public API.",
    "mention_rate": "Share of samples in which the entity name or an alias appears (case-insensitive, whole word).",
    "position": "Order of first appearance among tracked entities; list_rank is the rank inside a numbered/bulleted list when present.",
    "grounded": "Whether the provider used a search tool (OpenAI web_search, Gemini Google Search, Perplexity). Non-grounded answers reflect model knowledge only.",
    "caveat": "API responses do not exactly reproduce consumer ChatGPT, Gemini or Perplexity experiences. One answer is not a ranking; compare rates over repeated samples and time.",
}


@router.get("/prompts", response_model=list[PromptOut])
def list_prompts(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return db.scalars(select(PromptDefinition).where(PromptDefinition.project_id == project.id).order_by(PromptDefinition.created_at)).all()


@router.post("/prompts", response_model=list[PromptOut], status_code=201)
def create_prompts(body: list[PromptIn], project: Project = Depends(get_project), db: Session = Depends(get_db)):
    rows = [PromptDefinition(project_id=project.id, **p.model_dump()) for p in body]
    db.add_all(rows)
    db.commit()
    for r in rows:
        db.refresh(r)
    return rows


@router.patch("/prompts/{prompt_id}", response_model=PromptOut)
def update_prompt(prompt_id: uuid.UUID, body: PromptUpdate, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    p = db.get(PromptDefinition, prompt_id)
    if p is None or p.project_id != project.id:
        raise HTTPException(404, "Prompt not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/prompts/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: uuid.UUID, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    p = db.get(PromptDefinition, prompt_id)
    if p is None or p.project_id != project.id:
        raise HTTPException(404, "Prompt not found")
    db.delete(p)
    db.commit()


@router.post("/run", response_model=JobOut, status_code=202)
def run_prompts(body: RunPromptsIn, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    params = {"prompt_ids": [str(p) for p in body.prompt_ids], "provider_keys": body.provider_keys}
    if body.samples:
        params["samples"] = body.samples
    job = get_queue().enqueue(db, task_type="run_ai_visibility", params=params, project_id=project.id,
                              idempotency_key=f"run_ai_visibility:{project.id}", max_attempts=1)
    db.commit()
    db.refresh(job)
    return job


@router.get("/runs")
def list_runs(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    runs = D.latest_runs(db, project.id, 30)
    return [D.visibility_summary(db, project.id, r) for r in runs]


@router.get("/visibility")
def visibility(project: Project = Depends(get_project), run_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    runs = D.latest_runs(db, project.id, 2)
    current = run_id or (runs[0] if runs else None)
    previous = runs[1] if len(runs) > 1 and current == runs[0] else None
    return {"summary": D.visibility_summary(db, project.id, current), "previous": D.visibility_summary(db, project.id, previous) if previous else None,
            "by_prompt": D.visibility_by_prompt(db, project.id, current) if current else [], "methodology": METHODOLOGY}


@router.get("/observations", response_model=list[ObservationOut])
def observations(project: Project = Depends(get_project), prompt_id: uuid.UUID | None = None, run_id: uuid.UUID | None = None,
                 provider_key: str | None = None, limit: int = Query(100, le=1000), db: Session = Depends(get_db)):
    stmt = select(AIAnswerObservation).where(AIAnswerObservation.project_id == project.id).order_by(desc(AIAnswerObservation.observed_at)).limit(limit)
    if prompt_id:
        stmt = stmt.where(AIAnswerObservation.prompt_id == prompt_id)
    if run_id:
        stmt = stmt.where(AIAnswerObservation.run_id == run_id)
    if provider_key:
        stmt = stmt.where(AIAnswerObservation.provider_key == provider_key)
    obs = db.scalars(stmt).all()
    ids = [o.id for o in obs]
    mentions = db.scalars(select(AIAnswerMention).where(AIAnswerMention.observation_id.in_(ids))).all() if ids else []
    by_obs: dict[uuid.UUID, list[MentionOut]] = {}
    for m in mentions:
        by_obs.setdefault(m.observation_id, []).append(MentionOut.model_validate(m))
    out = []
    for o in obs:
        item = ObservationOut.model_validate(o)
        item.mentions = sorted(by_obs.get(o.id, []), key=lambda m: m.position or 99)
        out.append(item)
    return out


@router.get("/ai-traffic")
def ai_traffic(project: Project = Depends(get_project), days: int = Query(28, ge=7, le=365), db: Session = Depends(get_db)):
    """Visits that AI assistants actually sent — the downstream half of AI visibility."""
    out = []
    for d in D.primary_domains(db, project.id):
        out.append({"domain_id": str(d.id), "hostname": d.hostname, **D.ai_referral_traffic(db, d.id, days)})
    runs = D.latest_runs(db, project.id, 1)
    return {"domains": out, "visibility": D.visibility_summary(db, project.id, runs[0]) if runs else None,
            "methodology": {"how": "GA4 session source/medium matched against known AI assistant referrers, plus GA4's own ai-assistant medium.",
                            "caveat": "Assistants that hide the referrer are not counted, so this is a lower bound.",
                            "link": "Compare it with the mention rates above: visibility is the cause, these sessions are the effect."}}


@router.get("/citations")
def citations(project: Project = Depends(get_project), run_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    """Which domains influence AI answers (citation counts across the run)."""
    runs = D.latest_runs(db, project.id, 1)
    current = run_id or (runs[0] if runs else None)
    if not current:
        return {"run_id": None, "domains": []}
    obs = db.scalars(select(AIAnswerObservation).where(AIAnswerObservation.project_id == project.id, AIAnswerObservation.run_id == current)).all()
    counts: dict[str, dict] = {}
    for o in obs:
        for c in o.citations or []:
            d = c.get("domain")
            if not d:
                continue
            entry = counts.setdefault(d, {"domain": d, "citations": 0, "answers": set(), "providers": set(), "sample_urls": []})
            entry["citations"] += 1
            entry["answers"].add(str(o.id))
            entry["providers"].add(o.provider_key)
            if len(entry["sample_urls"]) < 3 and c.get("url") not in entry["sample_urls"]:
                entry["sample_urls"].append(c.get("url"))
    rows = sorted(({**v, "answers": len(v["answers"]), "providers": sorted(v["providers"])} for v in counts.values()), key=lambda r: -r["citations"])
    return {"run_id": str(current), "total_answers": len(obs), "domains": rows[:100]}
