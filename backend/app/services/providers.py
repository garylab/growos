"""Resolve provider connections into adapter instances; health checks; usage recording."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import ProviderAdapter
from app.adapters.registry import get_adapter_class
from app.core.config import get_settings
from app.core.secrets import decrypt_credentials, encrypt_credentials, mask_secret
from app.models import ProviderConnection, ProviderUsage


class ProviderNotConfigured(RuntimeError):
    """Raised when a job needs a provider that has not been configured. Never substituted with mock data."""


GOOGLE_PROVIDERS = ("google_search_console", "google_analytics_4")

# Credentials an operator may supply from the environment instead of typing them into the UI, as
# provider key -> {credential field: env var}. Useful when the same key serves several providers, when secrets are
# managed outside the app (.env, a secrets mount, CI), or simply to avoid pasting a key into a browser.
#
# The environment is a *fallback*: a value stored on the connection always wins, so one project can override the
# deployment-wide key. Connections are still required — they carry the per-connection config (which AI surface,
# which SERP engine, which render device) and are what the collection tasks enumerate — but with the key in the
# environment, creating one is just naming it and saving.
ENV_CREDENTIALS: dict[str, dict[str, str]] = {
    "pagespeed_insights": {"api_key": "GOOGLE_API_KEY"},
    "crux": {"api_key": "GOOGLE_API_KEY"},
    "gemini": {"api_key": "GEMINI_API_KEY"},
    "bing_webmaster": {"api_key": "BING_API_KEY"},
    "serpapi_serp": {"api_key": "SERPAPI_API_KEY"},
    "serpapi_ai": {"api_key": "SERPAPI_API_KEY"},
    "serpapi_extract": {"api_key": "SERPAPI_API_KEY"},
    "serpapi_bing": {"api_key": "SERPAPI_API_KEY"},
    "serpapi_youtube": {"api_key": "SERPAPI_API_KEY"},
    "serpapi_tiktok": {"api_key": "SERPAPI_API_KEY"},
    "apify_semrush_backlinks": {"apify_token": "APIFY_API_TOKEN"},
    "apify_linkedin_posts": {"apify_token": "APIFY_API_TOKEN"},
}


def env_credential_vars(provider_key: str) -> dict[str, str]:
    """{credential field: env var} for the fields this deployment actually has a value for."""
    s = get_settings()
    return {field: var for field, var in ENV_CREDENTIALS.get(provider_key, {}).items()
            if getattr(s, var.lower(), "")}


def env_credentials(provider_key: str) -> dict[str, str]:
    """{credential field: value} supplied by the environment for this provider."""
    s = get_settings()
    return {field: getattr(s, var.lower()) for field, var in env_credential_vars(provider_key).items()}


def google_client_credentials(stored: dict[str, Any] | None = None) -> dict[str, str]:
    """OAuth client id/secret: per-connection values win, otherwise the app-level client from the environment."""
    stored = stored or {}
    s = get_settings()
    return {"client_id": stored.get("client_id") or s.google_oauth_client_id,
            "client_secret": stored.get("client_secret") or s.google_oauth_client_secret}


def build_adapter(conn: ProviderConnection) -> ProviderAdapter:
    cls = get_adapter_class(conn.provider_key)
    creds = decrypt_credentials(conn.credentials_encrypted)
    if conn.provider_key in GOOGLE_PROVIDERS:
        creds = {**creds, **{k: v for k, v in google_client_credentials(creds).items() if v}}
    # Environment values fill only the fields the connection left empty.
    creds = {**env_credentials(conn.provider_key), **{k: v for k, v in creds.items() if v}}
    return cls(credentials=creds, config=conn.config or {})


def build_connectionless_adapter(provider_key: str, config: dict[str, Any] | None = None) -> ProviderAdapter:
    cls = get_adapter_class(provider_key)
    return cls(credentials=dict(env_credentials(provider_key)), config=config or {})


def connection_features(conn: ProviderConnection) -> set[str]:
    """What this particular connection can do.

    Read from the connection's own config rather than from the class, because a provider that is a blank slate is
    whatever it was pointed at: one custom JSON endpoint returns mentions, another returns referring domains, and
    only the saved config says which. `get_capabilities()` already takes `self.config` into account, so this just
    stops throwing that config away. Credentials are not needed and not decrypted.

    `ProviderAdapter.declared_features()` remains the class-level answer — everything the provider could do — and
    is what the Integrations page lists and what error messages suggest.
    """
    try:
        cls = get_adapter_class(conn.provider_key)
    except KeyError:
        return set()
    try:
        return set(cls(config=conn.config or {}).get_capabilities().features)
    except Exception:  # noqa: BLE001 — a provider that cannot describe itself must not break job selection
        return set(cls.declared_features())


def find_connection(db: Session, project_id: uuid.UUID | None, provider_key: str, enabled_only: bool = True) -> ProviderConnection | None:
    """Project-scoped connection first, then a global one (project_id NULL)."""
    stmt = select(ProviderConnection).where(ProviderConnection.provider_key == provider_key)
    if enabled_only:
        stmt = stmt.where(ProviderConnection.is_enabled.is_(True))
    conns = db.scalars(stmt).all()
    for c in conns:
        if project_id and c.project_id == project_id:
            return c
    for c in conns:
        if c.project_id is None:
            return c
    return None


def get_adapter(db: Session, project_id: uuid.UUID | None, provider_key: str) -> tuple[ProviderAdapter, ProviderConnection | None]:
    conn = find_connection(db, project_id, provider_key)
    if conn is not None:
        return build_adapter(conn), conn
    cls = get_adapter_class(provider_key)
    if not cls.requires_connection:
        return build_connectionless_adapter(provider_key), None
    raise ProviderNotConfigured(f"Provider '{cls.display_name}' is not configured. Add it under Integrations.")


def list_connections_for(db: Session, project_id: uuid.UUID | None, category: str) -> list[ProviderConnection]:
    stmt = select(ProviderConnection).where(ProviderConnection.category == category, ProviderConnection.is_enabled.is_(True))
    conns = db.scalars(stmt).all()
    return [c for c in conns if c.project_id is None or c.project_id == project_id]


def upsert_credentials(conn: ProviderConnection, new_values: dict[str, Any]) -> None:
    """Merge new credential values with stored ones; empty strings leave existing values untouched."""
    current = decrypt_credentials(conn.credentials_encrypted)
    for k, v in new_values.items():
        if v is None or v == "":
            continue
        current[k] = v
    conn.credentials_encrypted = encrypt_credentials(current) if current else None


def credential_preview(conn: ProviderConnection) -> dict[str, str]:
    """What each credential field holds, safe to return over the API.

    A field served by the environment reports where it came from rather than a masked value: the operator set it
    outside the app, and naming the variable is the useful thing to say — it explains why a connection with no
    stored key works, and which variable to change.
    """
    cls = get_adapter_class(conn.provider_key)
    creds = decrypt_credentials(conn.credentials_encrypted)
    from_env = env_credential_vars(conn.provider_key)
    out = {}
    for f in cls.credential_fields:
        v = creds.get(f.key)
        if v:
            out[f.key] = mask_secret(str(v)) if f.secret else str(v)
        elif f.key in from_env:
            out[f.key] = f"from {from_env[f.key]}"
        else:
            out[f.key] = ""
    return out


def run_health_check(db: Session, conn: ProviderConnection) -> dict[str, Any]:
    try:
        adapter = build_adapter(conn)
        res = adapter.health_check()
        conn.status = "healthy" if res.ok else "error"
        conn.last_error = None if res.ok else res.message[:2000]
        payload = {"ok": res.ok, "message": res.message, "details": res.details}
    except Exception as exc:  # noqa: BLE001
        conn.status = "error"
        conn.last_error = str(exc)[:2000]
        payload = {"ok": False, "message": str(exc), "details": {}}
    conn.last_checked_at = datetime.now(UTC)
    db.commit()
    return payload


def record_usage(db: Session, *, project_id: uuid.UUID | None, provider_key: str, operation: str,
                 connection_id: uuid.UUID | None = None, job_id: uuid.UUID | None = None, units: float = 1,
                 unit_type: str = "requests", tokens_in: int = 0, tokens_out: int = 0, details: dict[str, Any] | None = None) -> None:
    db.add(ProviderUsage(project_id=project_id, connection_id=connection_id, provider_key=provider_key, operation=operation,
                         units=units, unit_type=unit_type, tokens_in=tokens_in, tokens_out=tokens_out, job_id=job_id,
                         details=details or {}))


def usage_tokens(usage: dict[str, Any]) -> tuple[int, int]:
    """Normalize token counts across OpenAI (prompt_tokens/input_tokens) and Gemini (promptTokenCount)."""
    tin = usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("promptTokenCount") or 0
    tout = usage.get("completion_tokens") or usage.get("output_tokens") or usage.get("candidatesTokenCount") or 0
    return int(tin), int(tout)
