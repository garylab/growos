"""Shared Google authentication for Search Console and Analytics adapters.

Modes: service_account (JSON key pasted in the UI) or oauth (client id/secret + refresh token from the in-app consent flow).
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.adapters.base import ProviderError

TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
# Scopes for "Sign in with Google" (identity only — no API access, no refresh token needed).
LOGIN_SCOPE = "openid email profile"


def google_access_token(credentials: dict[str, Any], config: dict[str, Any], scope: str) -> str:
    mode = config.get("auth_mode") or ("service_account" if credentials.get("service_account_json") else "oauth")
    if mode == "service_account":
        raw = credentials.get("service_account_json")
        if not raw:
            raise ProviderError("Service account JSON is missing")
        info = json.loads(raw) if isinstance(raw, str) else raw
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(info, scopes=[scope])
        creds.refresh(Request())
        return creds.token
    for k in ("client_id", "client_secret", "refresh_token"):
        if not credentials.get(k):
            raise ProviderError(f"OAuth credential '{k}' is missing — run the Connect Google flow")
    resp = httpx.post(TOKEN_URL, data={"client_id": credentials["client_id"], "client_secret": credentials["client_secret"],
                                       "refresh_token": credentials["refresh_token"], "grant_type": "refresh_token"}, timeout=30)
    if resp.status_code != 200:
        raise ProviderError(f"Google token refresh failed: {resp.text[:200]}")
    return resp.json()["access_token"]


def build_auth_url(client_id: str, redirect_uri: str, state: str, scope: str, *,
                   access_type: str = "offline", prompt: str = "consent") -> str:
    params = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": scope,
              "access_type": access_type, "prompt": prompt, "state": state}
    return str(httpx.URL(AUTH_URL, params=params))


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict[str, Any]:
    resp = httpx.post(TOKEN_URL, data={"client_id": client_id, "client_secret": client_secret, "code": code,
                                       "grant_type": "authorization_code", "redirect_uri": redirect_uri}, timeout=30)
    if resp.status_code != 200:
        raise ProviderError(f"OAuth code exchange failed: {resp.text[:200]}")
    return resp.json()


def fetch_userinfo(access_token: str) -> dict[str, Any]:
    """Return the signed-in Google account's profile (sub, email, email_verified, name) for the given access token.

    Trusted because the token was just obtained by our own server-side code exchange over TLS — not supplied by the client.
    """
    resp = httpx.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    if resp.status_code != 200:
        raise ProviderError(f"Fetching Google profile failed: {resp.text[:200]}")
    return resp.json()


def google_api_error(resp: httpx.Response, what: str) -> ProviderError:
    """Readable error for Google API responses: keeps the full 'message' (which often contains an enable-API link)."""
    try:
        err = resp.json().get("error", {})
        msg = err.get("message") if isinstance(err, dict) else None
    except ValueError:
        msg = None
    text = msg or resp.text[:400]
    return ProviderError(f"{what} failed ({resp.status_code}): {text[:900]}")
