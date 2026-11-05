from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.adapters.base import ProviderError
from app.adapters.google_auth import LOGIN_SCOPE, build_auth_url, exchange_code, fetch_userinfo
from app.api.deps import Principal, get_principal, get_project, require_admin
from app.core.config import get_settings
from app.core.db import get_db
from app.core.ratelimit import RateLimiter
from app.core.security import hash_password, hash_token, needs_rehash, new_session_token, verify_password
from app.models import GoogleLoginState, Project, ProjectMember, User, UserSession
from app.models.user import MEMBER_ROLES, ROLES, USER_ROLES, split_role, unified_role
from app.schemas.auth import (LoginIn, MemberIn, MemberOut, PasswordChange, ProfileUpdate, RoleIn, SessionOut,
                              UserCreate, UserOut, UserUpdate)

router = APIRouter(tags=["auth"])
_login_limiter = RateLimiter(10)  # per client IP per minute — slows credential stuffing
GOOGLE_LOGIN_STATE_TTL = timedelta(minutes=15)


def _google_login_configured() -> bool:
    s = get_settings()
    return bool(s.google_oauth_client_id and s.google_oauth_client_secret)


def _google_login_redirect_uri() -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/api/auth/google/callback"


def _issue_session(db: Session, user: User, request: Request) -> SessionOut:
    token = new_session_token()
    expires = datetime.now(UTC) + timedelta(days=get_settings().session_days)
    db.add(UserSession(token_hash=hash_token(token), user_id=user.id, expires_at=expires,
                       user_agent=(request.headers.get("user-agent") or "")[:300]))
    user.last_login_at = datetime.now(UTC)
    db.execute(delete(UserSession).where(UserSession.expires_at < datetime.now(UTC)))
    db.commit()
    db.refresh(user)
    return SessionOut(token=token, expires_at=expires, user=UserOut.model_validate(user))


@router.post("/auth/login", response_model=SessionOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    from app.api.deps import client_ip
    if not _login_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many sign-in attempts. Wait a minute and try again.")
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    # Always verify against something so a wrong email and a wrong password take the same time.
    if not verify_password(body.password, user.password_hash if user else None) or not user or not user.is_active:
        raise HTTPException(401, "Incorrect email or password")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    return _issue_session(db, user, request)


# ------------------------------------------------------------------ Sign in with Google
# Both endpoints are public: Google redirects the user's browser here with no session. They are protected by the
# single-use, short-lived `state` token. Google sign-in only signs in an existing, active account whose verified
# email matches — it never creates accounts, so exposing this on a public URL does not allow open self-signup.
@router.get("/auth/google/login")
def google_login_start(db: Session = Depends(get_db)):
    s = get_settings()
    if not _google_login_configured():
        raise HTTPException(404, "Google sign-in is not configured")
    db.execute(delete(GoogleLoginState).where(GoogleLoginState.expires_at < datetime.now(UTC)))
    state = secrets.token_urlsafe(24)
    db.add(GoogleLoginState(state=state, expires_at=datetime.now(UTC) + GOOGLE_LOGIN_STATE_TTL))
    db.commit()
    url = build_auth_url(s.google_oauth_client_id, _google_login_redirect_uri(), state, LOGIN_SCOPE,
                         access_type="online", prompt="select_account")
    return RedirectResponse(url=url, status_code=302)


@router.get("/auth/google/callback")
def google_login_callback(request: Request, state: str = Query(...), code: str | None = None,
                          error: str | None = None, db: Session = Depends(get_db)):
    st = db.get(GoogleLoginState, state)
    if st is not None:
        db.delete(st)  # single use
        db.commit()
    if st is None or st.expires_at < datetime.now(UTC):
        return RedirectResponse(url="/#gauth_error=expired", status_code=302)
    if error or not code:
        return RedirectResponse(url=f"/#gauth_error={error or 'access_denied'}", status_code=302)
    s = get_settings()
    try:
        tokens = exchange_code(s.google_oauth_client_id, s.google_oauth_client_secret, code, _google_login_redirect_uri())
        info = fetch_userinfo(tokens["access_token"])
    except (ProviderError, KeyError):
        return RedirectResponse(url="/#gauth_error=google", status_code=302)
    email = (info.get("email") or "").lower()
    if not email or not info.get("email_verified"):
        return RedirectResponse(url="/#gauth_error=unverified", status_code=302)
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not user.is_active:
        return RedirectResponse(url="/#gauth_error=no_account", status_code=302)
    sub = info.get("sub")
    if sub:
        clash = db.scalar(select(User).where(User.google_sub == sub, User.id != user.id))
        if clash is not None:
            return RedirectResponse(url="/#gauth_error=mismatch", status_code=302)
        user.google_sub = sub  # pin the Google identity to this account
    session = _issue_session(db, user, request)  # commits google_sub too
    return RedirectResponse(url=f"/#gauth={session.token}", status_code=302)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    token = request.headers.get("x-auth-token") or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
        db.commit()


@router.get("/auth/me", response_model=UserOut)
def me(principal: Principal = Depends(get_principal)):
    if principal.user is None:
        raise HTTPException(400, "Signed in with the system token, which is not a user account")
    return principal.user


@router.patch("/auth/me", response_model=UserOut)
def update_me(body: ProfileUpdate, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    """Self-service profile edit. Changing role, email or active status still requires an administrator."""
    if principal.user is None:
        raise HTTPException(400, "Signed in with the system token, which is not a user account")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        principal.user.name = (data["name"] or "").strip() or None
    db.commit()
    db.refresh(principal.user)
    return principal.user


@router.post("/auth/password", status_code=204)
def change_password(body: PasswordChange, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    if principal.user is None:
        raise HTTPException(400, "System token has no password")
    if not verify_password(body.current_password, principal.user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    principal.user.password_hash = hash_password(body.new_password)
    principal.user.must_change_password = False
    # Sign out other sessions after a password change.
    db.execute(delete(UserSession).where(UserSession.user_id == principal.user.id))
    db.commit()


# ------------------------------------------------------------------ admin: users
@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: Principal = Depends(require_admin)):
    return db.scalars(select(User).order_by(User.created_at)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), _: Principal = Depends(require_admin)):
    if body.role in MEMBER_ROLES:          # unified role: owner/editor/viewer implies a non-admin account
        account_role, project_role = "member", body.role
    elif body.role in USER_ROLES:
        account_role, project_role = body.role, body.project_role
    else:
        raise HTTPException(400, f"role must be one of {ROLES}")
    if project_role not in MEMBER_ROLES:
        raise HTTPException(400, f"project_role must be one of {MEMBER_ROLES}")
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "A user with that email already exists")
    try:
        pw = hash_password(body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    user = User(email=body.email.lower(), name=body.name, password_hash=pw, role=account_role,
                must_change_password=body.must_change_password)
    db.add(user)
    db.flush()
    for pid in body.project_ids:
        if db.get(Project, pid):
            db.add(ProjectMember(project_id=pid, user_id=user.id, role=project_role))
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, body: UserUpdate, db: Session = Depends(get_db), principal: Principal = Depends(require_admin)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    data = body.model_dump(exclude_unset=True)
    if "email" in data and data["email"]:
        new_email = data["email"].lower()
        clash = db.scalar(select(User).where(func.lower(User.email) == new_email, User.id != user.id))
        if clash:
            raise HTTPException(409, "Another user already has that email")
        data["email"] = new_email
    if "role" in data and data["role"] not in USER_ROLES:
        raise HTTPException(400, f"role must be one of {USER_ROLES}")
    if data.get("is_active") is False or data.get("role") == "member":
        admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True)))
        if user.is_admin and user.is_active and admins <= 1:
            raise HTTPException(400, "This is the last active administrator")
    if data.pop("password", None):
        user.password_hash = hash_password(body.password)  # type: ignore[arg-type]
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    for k, v in data.items():
        setattr(user, k, v)
    if data.get("is_active") is False:
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: uuid.UUID, db: Session = Depends(get_db), principal: Principal = Depends(require_admin)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if principal.user and principal.user.id == user.id:
        raise HTTPException(400, "You cannot delete your own account")
    admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True)))
    if user.is_admin and admins <= 1:
        raise HTTPException(400, "This is the last active administrator")
    db.delete(user)
    db.commit()


# ------------------------------------------------------------------ project membership
@router.get("/projects/{project_id}/members", response_model=list[MemberOut])
def list_members(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    rows = db.execute(select(ProjectMember, User).join(User, User.id == ProjectMember.user_id)
                      .where(ProjectMember.project_id == project.id).order_by(User.email)).all()
    return [MemberOut(user_id=u.id, email=u.email, name=u.name, role=m.role, user_role=u.role,
                      effective_role=unified_role(u.role, m.role), is_active=u.is_active,
                      added_at=m.created_at) for m, u in rows]


@router.post("/projects/{project_id}/members", response_model=MemberOut, status_code=201)
def add_member(body: MemberIn, project: Project = Depends(get_project), db: Session = Depends(get_db),
               principal: Principal = Depends(get_principal)):
    from app.api.deps import member_role
    if not (principal.is_admin or member_role(db, project.id, principal.id) == "owner"):
        raise HTTPException(403, "Only an administrator or the project owner can add members")
    if body.role not in MEMBER_ROLES:
        raise HTTPException(400, f"role must be one of {MEMBER_ROLES}")
    user = db.get(User, body.user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    existing = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id))
    if existing:
        existing.role = body.role
        member = existing
    else:
        member = ProjectMember(project_id=project.id, user_id=user.id, role=body.role)
        db.add(member)
    db.commit()
    db.refresh(member)
    return MemberOut(user_id=user.id, email=user.email, name=user.name, role=member.role, user_role=user.role,
                     effective_role=unified_role(user.role, member.role), is_active=user.is_active,
                     added_at=member.created_at)


@router.put("/projects/{project_id}/members/{user_id}/role", response_model=MemberOut)
def set_member_role(user_id: uuid.UUID, body: RoleIn, project: Project = Depends(get_project),
                    db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    """Set a person's single role: admin (account-wide) or owner/editor/viewer on this project.

    One endpoint for both stored columns so the UI never has to make two calls that can half-fail.
    """
    from app.api.deps import member_role
    if body.role not in ROLES:
        raise HTTPException(400, f"role must be one of {ROLES}")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if principal.user is not None and principal.user.id == user.id:
        raise HTTPException(400, "You cannot change your own role")
    is_owner = bool(principal.id) and member_role(db, project.id, principal.id) == "owner"
    if not (principal.is_admin or is_owner):
        raise HTTPException(403, "Only an administrator or the project owner can change roles")
    account_role, project_role = split_role(body.role)
    # Granting or removing account-wide admin is an administrator's call, never a project owner's.
    if not principal.is_admin and (body.role == "admin" or user.is_admin):
        raise HTTPException(403, "Only an administrator can grant or remove administrator access")
    if user.is_admin and account_role != "admin" and user.is_active:
        admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True)))
        if admins <= 1:
            raise HTTPException(400, "This is the last active administrator")
    user.role = account_role
    member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id,
                                                   ProjectMember.user_id == user.id))
    if member is None:
        # Promoting someone who is not on this project yet still needs a row so they show up in the list.
        member = ProjectMember(project_id=project.id, user_id=user.id, role=project_role or "editor")
        db.add(member)
    elif project_role:
        member.role = project_role  # admins keep their previous project role, so demoting restores it
    db.commit()
    db.refresh(member)
    db.refresh(user)
    return MemberOut(user_id=user.id, email=user.email, name=user.name, role=member.role, user_role=user.role,
                     effective_role=unified_role(user.role, member.role), is_active=user.is_active,
                     added_at=member.created_at)


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
def remove_member(user_id: uuid.UUID, project: Project = Depends(get_project), db: Session = Depends(get_db),
                  principal: Principal = Depends(get_principal)):
    from app.api.deps import member_role
    if not (principal.is_admin or member_role(db, project.id, principal.id) == "owner"):
        raise HTTPException(403, "Only an administrator or the project owner can remove members")
    db.execute(delete(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user_id))
    db.commit()
