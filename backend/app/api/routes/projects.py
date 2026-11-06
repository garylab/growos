from __future__ import annotations

import re
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_domain, get_editable_project, get_principal, get_project, visible_projects
from app.core.db import get_db
from app.core.safe_http import UnsafeURLError, validate_url
from app.models import Competitor, Domain, Keyword, Project, ProjectMember
from app.queue import get_queue
from app.services.onboarding import seed_default_schedules
from app.schemas.project import (CompetitorIn, CompetitorOut, CompetitorUpdate, DomainIn, DomainOut, DomainUpdate, KeywordIn, KeywordOut, KeywordUpdate,
                                 ProjectIn, ProjectOut, ProjectUpdate)

router = APIRouter(prefix="/projects", tags=["projects"])


def slugify(v: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", v.lower()).strip("-")[:100] or "project"


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    """Admins see every project; members see only the ones they belong to."""
    return visible_projects(db, principal)


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    slug = slugify(body.name)
    if db.scalar(select(Project).where(Project.slug == slug)):
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"
    p = Project(slug=slug, **body.model_dump())
    db.add(p)
    db.flush()
    if principal.user is not None:  # the creator owns the project
        db.add(ProjectMember(project_id=p.id, user_id=principal.user.id, role="owner"))
    seed_default_schedules(db, p.id)  # the project starts collecting on its own
    db.commit()
    db.refresh(p)
    return p


@router.get("/{project_id}", response_model=ProjectOut)
def get_one(project: Project = Depends(get_project)):
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(body: ProjectUpdate, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(project, k, v)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(project: Project = Depends(get_editable_project), db: Session = Depends(get_db)):
    db.delete(project)
    db.commit()


# ------------------------------------------------------------------ domains
@router.get("/{project_id}/domains", response_model=list[DomainOut])
def list_domains(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return db.scalars(select(Domain).where(Domain.project_id == project.id).order_by(Domain.created_at)).all()


@router.post("/{project_id}/domains", response_model=DomainOut, status_code=201)
def add_domain(body: DomainIn, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        url = validate_url(url)
    except UnsafeURLError as exc:
        raise HTTPException(400, str(exc)) from exc
    parts = urlsplit(url)
    hostname = parts.hostname or ""
    base_url = f"{parts.scheme}://{parts.netloc}{parts.path if parts.path and parts.path != '/' else ''}".rstrip("/") + "/"
    if db.scalar(select(Domain).where(Domain.project_id == project.id, Domain.hostname == hostname)):
        raise HTTPException(409, "Domain already exists for this brand")
    for wu in body.watch_urls:
        try:
            validate_url(wu)
        except UnsafeURLError as exc:
            raise HTTPException(400, f"watch url: {exc}") from exc
    d = Domain(project_id=project.id, hostname=hostname, base_url=base_url, role=body.role, competitor_id=body.competitor_id,
               gsc_property=body.gsc_property, ga4_property=body.ga4_property,
               bing_site_url=body.bing_site_url, watch_urls=body.watch_urls)
    db.add(d)
    db.flush()
    if d.role == "primary":
        # First value without any external setup: crawl the site now, and schedule its recurring jobs.
        get_queue().enqueue(db, task_type="crawl_domain", params={"domain_id": str(d.id)}, project_id=project.id,
                            idempotency_key=f"crawl_domain:{project.id}:{d.id}", triggered_by="system")
        seed_default_schedules(db, project.id)
    db.commit()
    db.refresh(d)
    return d


@router.patch("/{project_id}/domains/{domain_id}", response_model=DomainOut)
def update_domain(body: DomainUpdate, domain: Domain = Depends(get_domain), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    for wu in data.get("watch_urls") or []:
        try:
            validate_url(wu)
        except UnsafeURLError as exc:
            raise HTTPException(400, f"watch url: {exc}") from exc
    for k, v in data.items():
        setattr(domain, k, v)
    db.commit()
    db.refresh(domain)
    return domain


@router.delete("/{project_id}/domains/{domain_id}", status_code=204)
def delete_domain(domain: Domain = Depends(get_domain), db: Session = Depends(get_db)):
    db.delete(domain)
    db.commit()


# ------------------------------------------------------------------ competitors
@router.get("/{project_id}/competitors", response_model=list[CompetitorOut])
def list_competitors(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return db.scalars(select(Competitor).where(Competitor.project_id == project.id).order_by(Competitor.name)).all()


def _attach_website(db: Session, project: Project, competitor: Competitor, website: str) -> None:
    """Register the competitor's site as a competitor domain, unless the project already tracks that host."""
    try:
        url = validate_url(website if website.startswith("http") else "https://" + website)
    except UnsafeURLError as exc:
        raise HTTPException(400, str(exc)) from exc
    parts = urlsplit(url)
    if not db.scalar(select(Domain).where(Domain.project_id == project.id, Domain.hostname == parts.hostname)):
        db.add(Domain(project_id=project.id, hostname=parts.hostname or "", base_url=f"{parts.scheme}://{parts.netloc}/",
                      role="competitor", competitor_id=competitor.id))


@router.post("/{project_id}/competitors", response_model=CompetitorOut, status_code=201)
def add_competitor(body: CompetitorIn, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    c = Competitor(project_id=project.id, name=body.name, aliases=body.aliases, notes=body.notes)
    db.add(c)
    db.flush()
    if body.website:
        _attach_website(db, project, c, body.website)
    db.commit()
    db.refresh(c)
    return c


@router.patch("/{project_id}/competitors/{competitor_id}", response_model=CompetitorOut)
def update_competitor(competitor_id: uuid.UUID, body: CompetitorUpdate, project: Project = Depends(get_project),
                      db: Session = Depends(get_db)):
    c = db.get(Competitor, competitor_id)
    if c is None or c.project_id != project.id:
        raise HTTPException(404, "Competitor not found")
    data = body.model_dump(exclude_unset=True)
    website = data.pop("website", None)
    for field, value in data.items():
        if value is not None:
            setattr(c, field, value)
    if "notes" in data:
        c.notes = data["notes"]      # notes may legitimately be cleared
    if website:
        _attach_website(db, project, c, website)
    db.commit()
    db.refresh(c)
    return c


@router.delete("/{project_id}/competitors/{competitor_id}", status_code=204)
def delete_competitor(competitor_id: uuid.UUID, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    c = db.get(Competitor, competitor_id)
    if c is None or c.project_id != project.id:
        raise HTTPException(404, "Competitor not found")
    db.delete(c)
    db.commit()


# ------------------------------------------------------------------ keywords
@router.get("/{project_id}/keywords", response_model=list[KeywordOut])
def list_keywords(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return db.scalars(select(Keyword).where(Keyword.project_id == project.id).order_by(Keyword.importance.desc(), Keyword.text)).all()


@router.post("/{project_id}/keywords", response_model=list[KeywordOut], status_code=201)
def add_keywords(body: list[KeywordIn], project: Project = Depends(get_project), db: Session = Depends(get_db)):
    created = []
    for kw in body:
        exists = db.scalar(select(Keyword).where(Keyword.project_id == project.id, Keyword.text == kw.text.strip(),
                                                 Keyword.country == kw.country, Keyword.language == kw.language))
        if exists:
            continue
        k = Keyword(project_id=project.id, text=kw.text.strip(), language=kw.language, country=kw.country,
                    importance=kw.importance, tags=kw.tags, source="manual")
        db.add(k)
        created.append(k)
    db.commit()
    for k in created:
        db.refresh(k)
    return created


@router.patch("/{project_id}/keywords/{keyword_id}", response_model=KeywordOut)
def update_keyword(keyword_id: uuid.UUID, body: KeywordUpdate, project: Project = Depends(get_project),
                   db: Session = Depends(get_db)):
    k = db.get(Keyword, keyword_id)
    if k is None or k.project_id != project.id:
        raise HTTPException(404, "Keyword not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(k, field, value)
    db.commit()
    db.refresh(k)
    return k


@router.delete("/{project_id}/keywords/{keyword_id}", status_code=204)
def delete_keyword(keyword_id: uuid.UUID, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    k = db.get(Keyword, keyword_id)
    if k is None or k.project_id != project.id:
        raise HTTPException(404, "Keyword not found")
    db.delete(k)
    db.commit()
