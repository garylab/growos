from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.core.db import get_db
from app.models import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _out(n: Notification) -> dict:
    return {"id": str(n.id), "project_id": str(n.project_id) if n.project_id else None, "kind": n.kind,
            "severity": n.severity, "title": n.title, "body": n.body, "link": n.link, "data": n.data,
            "created_at": n.created_at, "read_at": n.read_at}


@router.get("")
def list_notifications(unread_only: bool = False, limit: int = Query(50, le=200),
                       db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    if principal.user is None:
        return {"unread": 0, "items": []}
    stmt = select(Notification).where(Notification.user_id == principal.id).order_by(Notification.created_at.desc()).limit(limit)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    items = db.scalars(stmt).all()
    unread = db.scalar(select(__import__("sqlalchemy").func.count()).select_from(Notification)
                       .where(Notification.user_id == principal.id, Notification.read_at.is_(None))) or 0
    return {"unread": int(unread), "items": [_out(n) for n in items]}


@router.post("/{notification_id}/read")
def mark_read(notification_id: uuid.UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != principal.id:
        raise HTTPException(404, "Notification not found")
    n.read_at = n.read_at or datetime.now(UTC)
    db.commit()
    return _out(n)


@router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    if principal.user is None:
        return {"updated": 0}
    res = db.execute(update(Notification).where(Notification.user_id == principal.id, Notification.read_at.is_(None))
                     .values(read_at=datetime.now(UTC)))
    db.commit()
    return {"updated": res.rowcount or 0}
