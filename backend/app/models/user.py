from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

USER_ROLES = ("admin", "member")          # stored on users.role
MEMBER_ROLES = ("owner", "editor", "viewer")  # stored on project_members.role
# The one role vocabulary the UI shows. "admin" is account-wide (every project, manages accounts);
# the other three are per project. The two stored columns above are an implementation detail.
ROLES = ("admin", *MEMBER_ROLES)


def split_role(role: str) -> tuple[str, str | None]:
    """Map a unified role onto the two stored columns: (users.role, project_members.role or None)."""
    return ("admin", None) if role == "admin" else ("member", role)


def unified_role(user_role: str, project_role: str | None) -> str:
    """The single role to show for a person. Account-wide admin outranks any per-project role."""
    return "admin" if user_role == "admin" else (project_role or "viewer")


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person who can sign in. Admins manage users and project membership."""
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Google account subject id, pinned on first "Sign in with Google" so the account cannot be hijacked by email reuse.
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20), default="member", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class ProjectMember(UUIDPrimaryKeyMixin, Base):
    """Which users can see and work on a project."""
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="editor", nullable=False)  # owner | editor | viewer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserSession(Base):
    """Opaque session token (stored hashed) so sessions can be revoked and survive restarts."""
    __tablename__ = "user_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))
