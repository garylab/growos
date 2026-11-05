from __future__ import annotations


from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_project
from app.core.db import get_db
from app.models import BrandMention, Competitor, CompetitorObservation, Project

router = APIRouter(prefix="/projects/{project_id}/brand", tags=["brand"])


@router.get("/mentions")
def mentions(project: Project = Depends(get_project), entity_type: str | None = None, entity_name: str | None = None,
             intent: str | None = None, sentiment: str | None = None, provider_key: str | None = None,
             limit: int = Query(100, le=1000), db: Session = Depends(get_db)):
    stmt = select(BrandMention).where(BrandMention.project_id == project.id).order_by(desc(BrandMention.published_at).nulls_last()).limit(limit)
    for col, val in ((BrandMention.entity_type, entity_type), (BrandMention.entity_name, entity_name), (BrandMention.intent, intent),
                     (BrandMention.sentiment, sentiment), (BrandMention.provider_key, provider_key)):
        if val:
            stmt = stmt.where(col == val)
    rows = db.scalars(stmt).all()
    return [{"id": str(m.id), "provider_key": m.provider_key, "source_url": m.source_url, "source_name": m.source_name, "title": m.title,
             "content_excerpt": m.content_excerpt, "author": m.author, "published_at": m.published_at, "entity_type": m.entity_type,
             "entity_name": m.entity_name, "sentiment": m.sentiment, "sentiment_method": m.sentiment_method, "topics": m.topics,
             "intent": m.intent, "engagement": m.engagement, "collected_at": m.collected_at} for m in rows]


@router.get("/summary")
def summary(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    rows = db.execute(select(BrandMention.entity_name, BrandMention.entity_type, BrandMention.sentiment, func.count())
                      .where(BrandMention.project_id == project.id).group_by(BrandMention.entity_name, BrandMention.entity_type, BrandMention.sentiment)).all()
    by_entity: dict[str, dict] = {}
    for name, etype, sent, n in rows:
        e = by_entity.setdefault(name, {"entity_name": name, "entity_type": etype, "total": 0, "positive": 0, "neutral": 0, "negative": 0})
        e["total"] += n
        e[sent] = e.get(sent, 0) + n
    intents = dict(db.execute(select(BrandMention.intent, func.count()).where(BrandMention.project_id == project.id).group_by(BrandMention.intent)).all())
    sources = dict(db.execute(select(BrandMention.provider_key, func.count()).where(BrandMention.project_id == project.id).group_by(BrandMention.provider_key)).all())
    last = db.scalar(select(func.max(BrandMention.collected_at)).where(BrandMention.project_id == project.id))
    return {"entities": sorted(by_entity.values(), key=lambda e: -e["total"]), "intents": intents, "sources": sources, "last_collected_at": last,
            "definitions": {"sentiment": "Lexicon-based polarity of the sentence around the mention (coarse signal).",
                            "intent": "Keyword heuristics: question, recommendation_request, purchase_intent, complaint."}}


@router.get("/competitor-changes")
def competitor_changes(project: Project = Depends(get_project), only_changed: bool = True, limit: int = Query(100, le=1000), db: Session = Depends(get_db)):
    comps = {c.id: c.name for c in db.scalars(select(Competitor).where(Competitor.project_id == project.id)).all()}
    stmt = select(CompetitorObservation).where(CompetitorObservation.project_id == project.id).order_by(desc(CompetitorObservation.observed_at)).limit(limit)
    if only_changed:
        stmt = stmt.where(CompetitorObservation.changed.is_(True))
    rows = db.scalars(stmt).all()
    return [{"id": str(o.id), "competitor": comps.get(o.competitor_id), "url": o.url, "status_code": o.status_code, "title": o.title,
             "changed": o.changed, "change_ratio": o.change_ratio, "diff_summary": o.diff_summary, "observed_at": o.observed_at,
             "previous_observation_id": str(o.previous_observation_id) if o.previous_observation_id else None} for o in rows]


@router.get("/watched")
def watched(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Latest observation per watched URL."""
    sub = (select(CompetitorObservation.url, func.max(CompetitorObservation.observed_at).label("t"))
           .where(CompetitorObservation.project_id == project.id).group_by(CompetitorObservation.url).subquery())
    rows = db.scalars(select(CompetitorObservation).join(sub, (CompetitorObservation.url == sub.c.url) & (CompetitorObservation.observed_at == sub.c.t))).all()
    comps = {c.id: c.name for c in db.scalars(select(Competitor).where(Competitor.project_id == project.id)).all()}
    return [{"url": o.url, "competitor": comps.get(o.competitor_id), "last_observed_at": o.observed_at, "status_code": o.status_code,
             "changed_last_time": o.changed, "title": o.title} for o in rows]


