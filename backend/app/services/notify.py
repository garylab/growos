"""Notifications: recorded in-app always, emailed when SMTP is configured.

Email failures never block the work that raised the notification — the record persists and can be retried.
"""
from __future__ import annotations

import smtplib
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models import Notification, ProjectMember, User

log = get_logger("notify")


def notify(db: Session, *, title: str, kind: str, user_id: uuid.UUID | None = None, project_id: uuid.UUID | None = None,
           body: str | None = None, severity: str = "info", link: str | None = None, data: dict[str, Any] | None = None,
           dedupe_key: str | None = None, email: bool = True) -> Notification | None:
    """Create one notification. If dedupe_key matches an unread one for the same user, skip (returns None)."""
    if dedupe_key:
        existing = db.scalar(select(Notification).where(Notification.dedupe_key == dedupe_key,
                                                        Notification.user_id == user_id, Notification.read_at.is_(None)))
        if existing is not None:
            return None
    n = Notification(user_id=user_id, project_id=project_id, kind=kind, severity=severity, title=title[:300],
                     body=body, link=link, data=data or {}, dedupe_key=dedupe_key,
                     email_pending=bool(email and user_id is not None))
    db.add(n)
    db.flush()
    return n


def notify_project(db: Session, project_id: uuid.UUID, *, roles: tuple[str, ...] = ("owner", "editor"), admins: bool = True,
                   **kwargs: Any) -> int:
    """Notify every member of a project (and optionally all admins). Returns how many notifications were created."""
    recipients: set[uuid.UUID] = set(db.scalars(
        select(ProjectMember.user_id).where(ProjectMember.project_id == project_id, ProjectMember.role.in_(roles))).all())
    if admins:
        recipients |= set(db.scalars(select(User.id).where(User.role == "admin", User.is_active.is_(True))).all())
    made = 0
    for uid in recipients:
        key = kwargs.get("dedupe_key")
        per_user = {**kwargs, "dedupe_key": f"{key}:{uid}" if key else None}
        if notify(db, user_id=uid, project_id=project_id, **per_user) is not None:
            made += 1
    return made


# ----------------------------------------------------------------------- email delivery
def _send_email(to: str, subject: str, text: str, html: str | None = None) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("GrowOS", s.smtp_from))
    msg["To"] = to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as server:
        if s.smtp_starttls:
            server.starttls()
        if s.smtp_user:
            server.login(s.smtp_user, s.smtp_password)
        server.send_message(msg)


def flush_email_queue(db: Session, limit: int = 100) -> dict[str, int]:
    """Send any notifications marked email_pending. Called by the worker; a no-op when SMTP is not configured."""
    s = get_settings()
    pending = db.scalars(select(Notification).where(Notification.email_pending.is_(True)).limit(limit)).all()
    if not pending:
        return {"sent": 0, "skipped": 0, "failed": 0}
    if not s.email_enabled:
        for n in pending:  # nothing to send to; stop trying but keep the in-app record
            n.email_pending = False
        db.commit()
        return {"sent": 0, "skipped": len(pending), "failed": 0}
    emails = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_([n.user_id for n in pending if n.user_id]))).all()}
    sent = failed = 0
    for n in pending:
        to = emails.get(n.user_id)
        if not to:
            n.email_pending = False
            continue
        try:
            _send_email(to, f"[GrowOS] {n.title}", (n.body or n.title) + (f"\n\n{s_public_url(n.link)}" if n.link else ""),
                        _html_email(n))
            n.emailed_at = datetime.now(UTC)
            n.email_pending = False
            sent += 1
        except Exception as exc:  # noqa: BLE001 — leave email_pending=True to retry next cycle
            log.warning("email.failed", notification_id=str(n.id), error=str(exc))
            failed += 1
    db.commit()
    return {"sent": sent, "skipped": 0, "failed": failed}


def s_public_url(link: str | None) -> str:
    if not link:
        return ""
    base = get_settings().public_base_url.rstrip("/")
    return link if link.startswith("http") else f"{base}{link}"


def _html_email(n: Notification) -> str:
    link = s_public_url(n.link)
    cta = f'<p><a href="{link}" style="color:#2563eb">Open in GrowOS</a></p>' if link else ""
    body = (n.body or "").replace("\n", "<br>")
    return (f'<div style="font-family:system-ui,sans-serif;max-width:640px">'
            f'<h2 style="margin:0 0 8px">{n.title}</h2><div style="color:#334155">{body}</div>{cta}'
            f'<hr style="border:none;border-top:1px solid #e2e8f0;margin:16px 0">'
            f'<p style="color:#94a3b8;font-size:12px">GrowOS — customer acquisition intelligence</p></div>')
