from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import hash_token
from app.models import Domain, Project, ProjectMember, User, UserSession


@dataclass
class Principal:
    """Who is making the request: a signed-in user, or the system token used by scripts and automation."""
    user: User | None = None
    is_system: bool = False

    @property
    def is_admin(self) -> bool:
        return self.is_system or bool(self.user and self.user.is_admin)

    @property
    def id(self) -> uuid.UUID | None:
        return self.user.id if self.user else None

    @property
    def label(self) -> str:
        return self.user.email if self.user else "system"


def _bearer(request: Request) -> str:
    return (request.headers.get("x-auth-token")
            or request.headers.get("authorization", "").removeprefix("Bearer ").strip())


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    settings = get_settings()
    token = _bearer(request)
    if not token:
        raise HTTPException(401, "Not authenticated")
    if settings.app_auth_token and secrets.compare_digest(token, settings.app_auth_token):
        return Principal(is_system=True)
    session = db.get(UserSession, hash_token(token))
    if session is None or session.expires_at < datetime.now(UTC):
        raise HTTPException(401, "Session expired or invalid")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "Account is disabled")
    session.last_seen_at = datetime.now(UTC)
    db.commit()
    return Principal(user=user)


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(403, "Administrator access required")
    return principal


def member_role(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    return db.scalar(select(ProjectMember.role).where(ProjectMember.project_id == project_id,
                                                      ProjectMember.user_id == user_id))


def visible_projects(db: Session, principal: Principal) -> list[Project]:
    stmt = select(Project).order_by(Project.created_at)
    if principal.is_admin:
        return list(db.scalars(stmt).all())
    ids = db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == principal.id)).all()
    return list(db.scalars(stmt.where(Project.id.in_(ids))).all()) if ids else []


def get_project(project_id: uuid.UUID, db: Session = Depends(get_db),
                principal: Principal = Depends(get_principal)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Brand not found")
    if principal.is_admin or (principal.id and member_role(db, project.id, principal.id)):
        return project
    raise HTTPException(403, "You are not a member of this brand")


def get_editable_project(project_id: uuid.UUID, db: Session = Depends(get_db),
                         principal: Principal = Depends(get_principal)) -> Project:
    """Same as get_project but blocks viewers from making changes."""
    project = get_project(project_id, db, principal)
    if not principal.is_admin:
        role = member_role(db, project.id, principal.id) if principal.id else None
        if role == "viewer":
            raise HTTPException(403, "Your role for this brand is read-only")
    return project


def get_domain(project_id: uuid.UUID, domain_id: uuid.UUID, db: Session = Depends(get_db),
               principal: Principal = Depends(get_principal)) -> Domain:
    get_project(project_id, db, principal)
    domain = db.get(Domain, domain_id)
    if domain is None or domain.project_id != project_id:
        raise HTTPException(404, "Domain not found")
    return domain


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown"))
