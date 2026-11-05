"""GrowOS API."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import client_ip
from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.ratelimit import RateLimiter
from app.services.providers import ProviderNotConfigured

settings = get_settings()
configure_logging(settings.log_level, json_output=settings.app_env != "development")
log = get_logger("api")

@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap_admin()
    yield


app = FastAPI(title="GrowOS API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json",
              redoc_url=None, lifespan=lifespan)
if settings.cors_origin_list:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["*"], allow_headers=["*"])

_limiter = RateLimiter(settings.api_rate_limit_per_minute)
PUBLIC_PATHS = ("/api/health", "/api/meta", "/api/integrations/google/oauth/callback", "/api/docs", "/api/openapi.json")


def bootstrap_admin() -> None:
    """Create the first administrator from ADMIN_EMAIL/ADMIN_PASSWORD when no users exist yet."""
    from sqlalchemy import func, select

    from app.core.db import session_scope
    from app.core.security import hash_password
    from app.models import User
    if not (settings.admin_email and settings.admin_password):
        return
    try:
        with session_scope() as db:
            if db.scalar(select(func.count()).select_from(User)):
                return
            db.add(User(email=settings.admin_email.lower(), name="Administrator",
                        password_hash=hash_password(settings.admin_password), role="admin"))
            log.info("admin.bootstrapped", email=settings.admin_email)
    except Exception as exc:  # noqa: BLE001 — never block startup on this
        log.error("admin.bootstrap_failed", error=str(exc))


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    path = request.url.path
    if (path.startswith("/api") and not path.startswith(PUBLIC_PATHS)
            and request.method in ("POST", "PATCH", "PUT", "DELETE")
            and not _limiter.allow(client_ip(request))):
        return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
    return await call_next(request)


@app.exception_handler(ProviderNotConfigured)
async def provider_not_configured(_: Request, exc: ProviderNotConfigured):
    return JSONResponse({"detail": str(exc), "code": "provider_not_configured"}, status_code=409)


@app.get("/api/meta")
def meta():
    """Tells the UI which sign-in mode to show. Never leaks whether a specific account exists."""
    from sqlalchemy import func, select

    from app.core.db import session_scope
    from app.models import User
    try:
        with session_scope() as db:
            users_exist = bool(db.scalar(select(func.count()).select_from(User)))
    except Exception:  # noqa: BLE001 — database not ready yet
        users_exist = False
    return {"name": "GrowOS", "version": app.version, "auth_required": True,
            "auth_mode": "users" if users_exist else "token", "users_exist": users_exist,
            "google_login_enabled": bool(settings.google_oauth_client_id and settings.google_oauth_client_secret)}


app.include_router(api_router)
