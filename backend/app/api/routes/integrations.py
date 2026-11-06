from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.adapters.base import ProviderError
from app.adapters.registry import ADAPTERS, CATEGORIES, PLANNED_ADAPTERS, get_adapter_class
from app.adapters.google_auth import build_auth_url, exchange_code
from app.core.config import get_settings
from app.core.db import get_db
from app.core.secrets import decrypt_credentials
from app.models import CrawlRun, OAuthState, Project, ProviderConnection
from app.schemas.integrations import ConnectionIn, ConnectionOut, ConnectionTestIn, ConnectionUpdate
from app.services.providers import (GOOGLE_PROVIDERS, build_adapter, build_connectionless_adapter, credential_preview,
                                     env_credentials, env_credential_vars, google_client_credentials, run_health_check,
                                     upsert_credentials)

router = APIRouter(prefix="/integrations", tags=["integrations"])
# Google redirects the user's browser here, so this endpoint cannot require a session. It is protected instead by the
# one-time `state` token: random, stored hashed-by-value in the database, single use and valid for 15 minutes.
public_router = APIRouter(prefix="/integrations", tags=["integrations"])
OAUTH_STATE_TTL = timedelta(minutes=15)


def _out(conn: ProviderConnection) -> ConnectionOut:
    o = ConnectionOut.model_validate(conn)
    o.credential_preview = credential_preview(conn)
    return o


@router.get("/providers")
def list_providers():
    """Every provider, plus which of its credentials this deployment already supplies from the environment.

    `env_credentials` is deployment state, not a property of the adapter, so it is attached here rather than in
    `describe()`: the same build reports different values depending on what the operator put in the environment.
    """
    providers = []
    for cls in ADAPTERS.values():
        providers.append({**cls.describe(), "env_credentials": env_credential_vars(cls.key)})
    return {"categories": CATEGORIES, "providers": providers, "planned": PLANNED_ADAPTERS}


@router.get("/connections", response_model=list[ConnectionOut])
def list_connections(project_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    stmt = select(ProviderConnection).order_by(ProviderConnection.category, ProviderConnection.created_at)
    conns = db.scalars(stmt).all()
    return [_out(c) for c in conns if project_id is None or c.project_id in (None, project_id)]


@router.post("/connections", response_model=ConnectionOut, status_code=201)
def create_connection(body: ConnectionIn, db: Session = Depends(get_db)):
    try:
        cls = get_adapter_class(body.provider_key)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    allowed_cred_keys = {f.key for f in cls.credential_fields}
    creds = {k: v for k, v in body.credentials.items() if k in allowed_cred_keys}
    from_env = env_credential_vars(cls.key)
    missing = [f.key for f in cls.credential_fields
               if f.required and not creds.get(f.key) and f.key not in from_env]
    if missing:
        raise HTTPException(400, f"Missing required credentials: {', '.join(missing)}")
    # The category comes from the config, not the class: a custom endpoint is filed under the job it was set up
    # for, which is what decides who collects from it.
    conn = ProviderConnection(project_id=body.project_id, provider_key=cls.key,
                              category=cls.category_for_config(body.config or {}),
                              display_name=body.display_name or cls.display_name, config=body.config or {})
    upsert_credentials(conn, creds)
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return _out(conn)


@router.patch("/connections/{connection_id}", response_model=ConnectionOut)
def update_connection(connection_id: uuid.UUID, body: ConnectionUpdate, db: Session = Depends(get_db)):
    conn = db.get(ProviderConnection, connection_id)
    if conn is None:
        raise HTTPException(404, "Connection not found")
    if body.display_name is not None:
        conn.display_name = body.display_name
    if body.config is not None:
        conn.config = {**(conn.config or {}), **body.config}
        # Changing what the endpoint returns moves the connection to the matching category, and so hands it to a
        # different collection task. Re-derived here rather than left stale on the row.
        conn.category = get_adapter_class(conn.provider_key).category_for_config(conn.config)
        conn.status = "unverified"
    if body.is_enabled is not None:
        conn.is_enabled = body.is_enabled
    if "project_id" in body.model_fields_set:
        if body.project_id is not None and db.get(Project, body.project_id) is None:
            raise HTTPException(404, "Brand not found")
        conn.project_id = body.project_id
    if body.credentials:
        cls = get_adapter_class(conn.provider_key)
        allowed = {f.key for f in cls.credential_fields}
        upsert_credentials(conn, {k: v for k, v in body.credentials.items() if k in allowed})
        conn.status = "unverified"
    db.commit()
    db.refresh(conn)
    return _out(conn)


@router.delete("/connections/{connection_id}", status_code=204)
def delete_connection(connection_id: uuid.UUID, db: Session = Depends(get_db)):
    conn = db.get(ProviderConnection, connection_id)
    if conn is None:
        raise HTTPException(404, "Connection not found")
    db.delete(conn)
    db.commit()


@router.post("/connections/{connection_id}/check")
def check_connection(connection_id: uuid.UUID, db: Session = Depends(get_db)):
    conn = db.get(ProviderConnection, connection_id)
    if conn is None:
        raise HTTPException(404, "Connection not found")
    return run_health_check(db, conn)


@router.post("/providers/{provider_key}/check")
def check_connectionless(provider_key: str, db: Session = Depends(get_db)):
    """Health check for bundled/public providers that need no stored credentials.

    One provider cannot answer for itself here: the crawler binary ships only in the crawl worker's image, so the
    API has nothing to execute. Rather than report a working deployment as broken, the last crawl that actually
    ran is used as the evidence — which is a better check anyway, since it proves the path end to end.
    """
    try:
        cls = get_adapter_class(provider_key)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    if cls.requires_connection:
        raise HTTPException(400, "This provider requires a configured connection")
    adapter = build_connectionless_adapter(provider_key)
    if provider_key == "siteone" and not adapter.installed():  # type: ignore[attr-defined]
        return _last_crawl_evidence(db)
    res = adapter.health_check()
    return {"ok": res.ok, "message": res.message, "details": res.details}


@router.post("/providers/{provider_key}/test")
def test_provider_configuration(provider_key: str, body: ConnectionTestIn, db: Session = Depends(get_db)):
    """Test credentials and config from the Add/Edit form without saving a temporary connection."""
    try:
        cls = get_adapter_class(provider_key)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    stored_credentials: dict[str, Any] = {}
    stored_config: dict[str, Any] = {}
    conn: ProviderConnection | None = None
    if body.connection_id is not None:
        conn = db.get(ProviderConnection, body.connection_id)
        if conn is None or conn.provider_key != provider_key:
            raise HTTPException(404, "Connection not found")
        stored_credentials = decrypt_credentials(conn.credentials_encrypted)
        stored_config = conn.config or {}
    allowed = {field.key for field in cls.credential_fields}
    entered = {key: value for key, value in body.credentials.items() if key in allowed and value not in (None, "")}
    credentials = {**env_credentials(provider_key), **stored_credentials, **entered}
    if provider_key in GOOGLE_PROVIDERS:
        credentials = {**credentials, **{key: value for key, value in google_client_credentials(credentials).items() if value}}
    try:
        result = cls(credentials=credentials, config={**stored_config, **body.config}).health_check()
        # A test of the currently saved values is the connection's health check, so persist its outcome. Tests with
        # unsaved credential/config edits stay provisional: saving those edits resets the row to unverified and the
        # user can test the newly saved connection once, without us silently saving form input from a Test action.
        testing_saved_values = conn is not None and not entered and body.config == stored_config
        if testing_saved_values:
            conn.status = "healthy" if result.ok else "error"
            conn.last_error = None if result.ok else result.message[:2000]
            conn.last_checked_at = datetime.now(UTC)
            db.commit()
        return {"ok": result.ok, "message": result.message, "details": result.details}
    except Exception as exc:  # noqa: BLE001 — a failed pre-save check is returned as a result, not a server error
        return {"ok": False, "message": str(exc), "details": {}}


def _last_crawl_evidence(db: Session) -> dict[str, Any]:
    """What the most recent crawl proves about the out-of-process crawler."""
    run = db.scalars(select(CrawlRun).where(CrawlRun.finished_at.isnot(None))
                     .order_by(CrawlRun.started_at.desc()).limit(1)).first()
    if run is None:
        return {"ok": False, "details": {},
                "message": "Crawling runs in the crawler service and no crawl has completed yet — run “Run crawl & "
                           "audit” on a website to verify it."}
    age = datetime.now(UTC) - run.started_at
    return {"ok": True,
            "message": f"Runs in the crawler service · SiteOne {run.provider_version or 'unknown'} · last crawl "
                       f"{run.total_urls} URL(s), {age.days}d ago",
            "details": {"provider_version": run.provider_version, "total_urls": run.total_urls,
                        "last_crawl": run.started_at.isoformat()}}


# ------------------------------------------------------------------ Google Search Console helpers
@router.get("/connections/{connection_id}/gsc/sites")
def gsc_sites(connection_id: uuid.UUID, db: Session = Depends(get_db)):
    conn = db.get(ProviderConnection, connection_id)
    if conn is None or conn.provider_key != "google_search_console":
        raise HTTPException(404, "Search Console connection not found")
    try:
        return build_adapter(conn).list_sites()  # type: ignore[attr-defined]
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from exc


def _google_conn(db: Session, connection_id: uuid.UUID) -> ProviderConnection:
    conn = db.get(ProviderConnection, connection_id)
    if conn is None or conn.provider_key not in GOOGLE_PROVIDERS:
        raise HTTPException(404, "Google connection not found")
    return conn


def _redirect_uri() -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/api/integrations/google/oauth/callback"


@router.get("/google/status")
def google_status():
    """Whether the app-level Google OAuth client is configured (enables one-click Connect)."""
    s = get_settings()
    return {"configured": bool(s.google_oauth_client_id and s.google_oauth_client_secret), "redirect_uri": _redirect_uri(),
            "client_id": s.google_oauth_client_id, "api_key_configured": bool(s.google_api_key)}


def _start_oauth(db: Session, conn: ProviderConnection, project_id: uuid.UUID | None) -> dict[str, str]:
    creds = google_client_credentials(decrypt_credentials(conn.credentials_encrypted))
    if not creds["client_id"] or not creds["client_secret"]:
        raise HTTPException(400, "No Google OAuth client configured. Set GOOGLE_OAUTH_CLIENT_ID/SECRET in .env (one-time) "
                                 "or enter a client ID and secret on this connection.")
    now = datetime.now(UTC)
    db.execute(delete(OAuthState).where(OAuthState.expires_at < now))  # housekeeping
    state = secrets.token_urlsafe(24)
    db.add(OAuthState(state=state, provider_key=conn.provider_key, connection_id=conn.id, project_id=project_id,
                      expires_at=now + OAUTH_STATE_TTL))
    db.commit()
    scope = getattr(get_adapter_class(conn.provider_key), "oauth_scope")
    return {"auth_url": build_auth_url(creds["client_id"], _redirect_uri(), state, scope), "redirect_uri": _redirect_uri()}


@router.get("/google/connect")
def google_connect(provider_key: str = Query(...), project_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    """One-click connect: creates (or reuses) a connection for the Google provider and returns the consent URL."""
    if provider_key not in GOOGLE_PROVIDERS:
        raise HTTPException(400, "Not a Google provider")
    cls = get_adapter_class(provider_key)
    conn = db.scalar(select(ProviderConnection).where(ProviderConnection.provider_key == provider_key,
                                                      ProviderConnection.project_id == project_id))
    if conn is None:
        conn = ProviderConnection(project_id=project_id, provider_key=provider_key, category=cls.category,
                                  display_name=cls.display_name, config={"auth_mode": "oauth"}, status="unverified")
        db.add(conn)
        db.commit()
        db.refresh(conn)
    return _start_oauth(db, conn, project_id)


@router.get("/connections/{connection_id}/google/oauth/start")
def google_oauth_start(connection_id: uuid.UUID, db: Session = Depends(get_db)):
    conn = _google_conn(db, connection_id)
    return _start_oauth(db, conn, conn.project_id)


# Backwards-compatible alias
@router.get("/connections/{connection_id}/gsc/oauth/start")
def gsc_oauth_start(connection_id: uuid.UUID, db: Session = Depends(get_db)):
    return google_oauth_start(connection_id, db)


@public_router.get("/google/oauth/callback")
def google_oauth_callback(code: str | None = None, state: str = Query(...), error: str | None = None, db: Session = Depends(get_db)):
    st = db.get(OAuthState, state)
    if st is not None:
        db.delete(st)  # single use
        db.commit()
    if st is None or st.expires_at < datetime.now(UTC):
        raise HTTPException(400, "Invalid or expired OAuth state. Click Connect again.")
    conn = db.get(ProviderConnection, st.connection_id)
    if conn is None:
        raise HTTPException(404, "Connection not found")
    if error or not code:
        return RedirectResponse(url=f"/integrations?error={error or 'access_denied'}", status_code=302)
    creds = google_client_credentials(decrypt_credentials(conn.credentials_encrypted))
    try:
        token = exchange_code(creds["client_id"], creds["client_secret"], code, _redirect_uri())
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not token.get("refresh_token"):
        raise HTTPException(400, "Google did not return a refresh token; remove the app's access in your Google account and retry.")
    upsert_credentials(conn, {"refresh_token": token["refresh_token"]})
    conn.config = {**(conn.config or {}), "auth_mode": "oauth"}
    db.commit()
    result = run_health_check(db, conn)
    matched = _auto_match_properties(db, conn, st.project_id) if result["ok"] else []
    qs = f"connected={conn.provider_key}" + (f"&matched={len(matched)}" if matched else "")
    return RedirectResponse(url=f"/integrations?{qs}", status_code=302)


def _auto_match_properties(db: Session, conn: ProviderConnection, project_id: uuid.UUID | None) -> list[str]:
    """After connecting, fill gsc_property / ga4_property on the project's primary domains when a match is unambiguous."""
    from app.models import Domain
    stmt = select(Domain).where(Domain.role == "primary", Domain.is_active.is_(True))
    if project_id:
        stmt = stmt.where(Domain.project_id == project_id)
    domains = db.scalars(stmt).all()
    adapter = build_adapter(conn)
    matched: list[str] = []
    try:
        if conn.provider_key == "google_search_console":
            sites = [s.get("siteUrl", "") for s in adapter.list_sites()]  # type: ignore[attr-defined]
            for d in domains:
                if d.gsc_property:
                    continue
                host = d.hostname.removeprefix("www.")
                candidates = [s for s in sites if s == f"sc-domain:{host}" or s.rstrip("/").lower() in (d.base_url.rstrip("/").lower(), f"https://{d.hostname}", f"http://{d.hostname}", f"https://www.{host}", f"https://{host}")]
                if candidates:
                    d.gsc_property = sorted(candidates, key=lambda s: 0 if s.startswith("sc-domain:") else 1)[0]
                    matched.append(d.hostname)
        elif conn.provider_key == "google_analytics_4":
            streams = adapter.list_web_streams()  # type: ignore[attr-defined]
            for d in domains:
                if d.ga4_property:
                    continue
                host = d.hostname.removeprefix("www.")
                props = {s["property"] for s in streams if (s.get("host") or "").removeprefix("www.") == host}
                if len(props) == 1:
                    d.ga4_property = props.pop().removeprefix("properties/")
                    matched.append(d.hostname)
    except Exception:  # noqa: BLE001 — matching is best-effort
        db.rollback()
        return []
    db.commit()
    return matched


@router.get("/connections/{connection_id}/ga4/properties")
def ga4_properties(connection_id: uuid.UUID, db: Session = Depends(get_db)):
    conn = db.get(ProviderConnection, connection_id)
    if conn is None or conn.provider_key != "google_analytics_4":
        raise HTTPException(404, "Google Analytics connection not found")
    try:
        return build_adapter(conn).list_properties()  # type: ignore[attr-defined]
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from exc
