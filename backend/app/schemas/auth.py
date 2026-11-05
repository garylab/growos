from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    name: str | None
    role: str
    is_active: bool
    last_login_at: datetime | None
    must_change_password: bool
    created_at: datetime


class SessionOut(BaseModel):
    token: str
    expires_at: datetime
    user: UserOut


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str | None = None
    role: str = "member"
    must_change_password: bool = False
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    project_role: str = "editor"


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)
    must_change_password: bool | None = None


class ProfileUpdate(BaseModel):
    """What a signed-in person may change about their own account. Role and status are deliberately absent."""
    name: str | None = Field(default=None, max_length=200)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


class MemberIn(BaseModel):
    user_id: uuid.UUID
    role: str = "editor"


class RoleIn(BaseModel):
    """One unified role: admin | owner | editor | viewer."""
    role: str


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str | None
    role: str          # stored per-project role (owner | editor | viewer)
    user_role: str     # stored account role (admin | member)
    effective_role: str  # the single role the UI shows
    is_active: bool
    added_at: datetime
