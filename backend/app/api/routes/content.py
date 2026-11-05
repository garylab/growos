from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_editable_project, get_principal, get_project
from app.core.db import get_db
from app.models import ContentDraft, Project
from app.models.content import CHANNELS, CONTENT_KINDS, CONTENT_STATUSES
from app.queue import get_queue
from app.schemas.common import JobOut
from app.services.content_studio import GENERATOR_PROVIDERS
from app.services.providers import list_connections_for

router = APIRouter(prefix="/projects/{project_id}/content", tags=["content"])


class GenerateIn(BaseModel):
    kind: str
    topic: str = Field(min_length=3, max_length=400)
    channel: str = "blog"
    plan_item_id: uuid.UUID | None = None
    notes: str | None = None
    provider_key: str | None = None


class DraftUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    status: str | None = None
    published_url: str | None = None


def _out(d: ContentDraft) -> dict:
    return {"id": str(d.id), "plan_item_id": str(d.plan_item_id) if d.plan_item_id else None, "kind": d.kind,
            "channel": d.channel, "topic": d.topic, "title": d.title, "body": d.body, "assets": d.assets,
            "evidence": d.evidence, "provider_key": d.provider_key, "model": d.model, "status": d.status,
            "published_url": d.published_url, "created_at": d.created_at, "updated_at": d.updated_at}


@router.get("/writers")
def writers(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """AI providers available for writing. Ollama means fully local, open-source generation."""
    conns = [c for c in list_connections_for(db, project.id, "ai") if c.provider_key in GENERATOR_PROVIDERS]
    return {"writers": [{"provider_key": c.provider_key, "display_name": c.display_name, "status": c.status,
                         "model": (c.config or {}).get("analysis_model") or (c.config or {}).get("model"),
                         "local": c.provider_key == "ollama"} for c in conns],
            "kinds": list(CONTENT_KINDS), "channels": list(CHANNELS)}


@router.get("")
def list_drafts(project: Project = Depends(get_project), plan_item_id: uuid.UUID | None = None,
                kind: str | None = None, status: str | None = None, limit: int = Query(100, le=500),
                db: Session = Depends(get_db)):
    stmt = select(ContentDraft).where(ContentDraft.project_id == project.id).order_by(desc(ContentDraft.created_at)).limit(limit)
    if plan_item_id:
        stmt = stmt.where(ContentDraft.plan_item_id == plan_item_id)
    if kind:
        stmt = stmt.where(ContentDraft.kind == kind)
    if status:
        stmt = stmt.where(ContentDraft.status == status)
    return [_out(d) for d in db.scalars(stmt).all()]


@router.post("/generate", response_model=JobOut, status_code=202)
def generate_draft(body: GenerateIn, project: Project = Depends(get_editable_project), db: Session = Depends(get_db),
                   principal: Principal = Depends(get_principal)):
    if body.kind not in CONTENT_KINDS:
        raise HTTPException(400, f"kind must be one of {CONTENT_KINDS}")
    if body.channel not in CHANNELS:
        raise HTTPException(400, f"channel must be one of {CHANNELS}")
    params = {**body.model_dump(mode="json"), "created_by": str(principal.id) if principal.id else None}
    job = get_queue().enqueue(db, task_type="generate_content", params=params, project_id=project.id,
                              priority=30, max_attempts=1)
    db.commit()
    db.refresh(job)
    return job


@router.patch("/{draft_id}")
def update_draft(draft_id: uuid.UUID, body: DraftUpdate, project: Project = Depends(get_editable_project),
                 db: Session = Depends(get_db)):
    d = db.get(ContentDraft, draft_id)
    if d is None or d.project_id != project.id:
        raise HTTPException(404, "Draft not found")
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in CONTENT_STATUSES:
        raise HTTPException(400, f"status must be one of {CONTENT_STATUSES}")
    for k, v in data.items():
        setattr(d, k, v)
    if data.get("status") == "published" and d.published_at is None:
        from datetime import UTC, datetime
        d.published_at = datetime.now(UTC)
    db.commit()
    db.refresh(d)
    return _out(d)


@router.delete("/{draft_id}", status_code=204)
def delete_draft(draft_id: uuid.UUID, project: Project = Depends(get_editable_project), db: Session = Depends(get_db)):
    d = db.get(ContentDraft, draft_id)
    if d is None or d.project_id != project.id:
        raise HTTPException(404, "Draft not found")
    db.delete(d)
    db.commit()
