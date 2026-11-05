"""Bluesky post search (app.bsky.feed.searchPosts).

Works without credentials through the public AppView. Some networks block public.api.bsky.app (HTTP 403), so the adapter
tries several endpoints in order. Optionally, a Bluesky handle + app password authenticates against the PDS
(com.atproto.server.createSession), which is the most robust option and has higher rate limits.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

import httpx

from app.adapters.base import Capabilities, CollectResult, ConfigField, CredentialField, HealthResult, ProviderAdapter, ProviderError

SEARCH = "/xrpc/app.bsky.feed.searchPosts"
PUBLIC_ENDPOINTS = ["https://public.api.bsky.app", "https://api.bsky.app"]
DEFAULT_PDS = "https://bsky.social"


class BlueskyAdapter(ProviderAdapter):
    key: ClassVar[str] = "bluesky"
    category: ClassVar[str] = "brand"
    vendor: ClassVar[str] = "Bluesky"
    vendor_url: ClassVar[str] = "https://docs.bsky.app"
    display_name: ClassVar[str] = "Bluesky"
    description: ClassVar[str] = "Public posts mentioning the brand or competitors via the Bluesky API (keyless, or with an app password)."
    docs_url: ClassVar[str] = "https://docs.bsky.app/docs/api/app-bsky-feed-search-posts"
    requires_connection: ClassVar[bool] = False
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("handle", "Bluesky handle", secret=False, required=False, help="Optional, e.g. yourbrand.bsky.social"),
        CredentialField("app_password", "App password", required=False, help="Optional: Settings → App passwords in Bluesky. Not your main password."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("limit_per_query", "Max posts per query", "number", 50),
        ConfigField("endpoint", "Preferred public endpoint", "string", PUBLIC_ENDPOINTS[0], help="Falls back to api.bsky.app automatically."),
        ConfigField("pds", "PDS for authenticated access", "string", DEFAULT_PDS),
    ]

    # ------------------------------------------------------------------ transport
    def _session(self) -> tuple[str, dict[str, str]]:
        """Returns (base_url, headers) for an authenticated session if credentials are set."""
        pds = (self.config.get("pds") or DEFAULT_PDS).rstrip("/")
        r = httpx.post(f"{pds}/xrpc/com.atproto.server.createSession",
                       json={"identifier": self.credentials["handle"], "password": self.credentials["app_password"]}, timeout=20)
        if r.status_code != 200:
            raise ProviderError(f"Bluesky login failed ({r.status_code}): {r.text[:200]}")
        return pds, {"Authorization": f"Bearer {r.json()['accessJwt']}"}

    def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.credentials.get("handle") and self.credentials.get("app_password"):
            base, headers = self._session()
            r = httpx.get(f"{base}{SEARCH}", params=params, headers=headers, timeout=30)
            if r.status_code != 200:
                raise ProviderError(f"Bluesky search failed ({r.status_code}): {r.text[:200]}")
            return r.json()
        preferred = (self.config.get("endpoint") or PUBLIC_ENDPOINTS[0]).rstrip("/")
        endpoints = [preferred] + [e for e in PUBLIC_ENDPOINTS if e != preferred]
        errors = []
        for base in endpoints:
            try:
                r = httpx.get(f"{base}{SEARCH}", params=params, timeout=30)
            except httpx.HTTPError as exc:
                errors.append(f"{base}: {exc}")
                continue
            if r.status_code == 200:
                return r.json()
            errors.append(f"{base}: HTTP {r.status_code}")
        raise ProviderError("Bluesky public API unreachable (" + "; ".join(errors) + "). Add a handle + app password to use authenticated access.")

    # ------------------------------------------------------------------ adapter API
    def health_check(self) -> HealthResult:
        try:
            self._search({"q": "bluesky", "limit": 1})
            mode = "authenticated" if self.credentials.get("app_password") else "public endpoint"
            return HealthResult(True, f"Bluesky search reachable ({mode})")
        except ProviderError as exc:
            return HealthResult(False, str(exc))
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Bluesky check failed: {exc}")

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="brand", measurement_type="observed", features=["mentions", "engagement"])

    def collect(self, request: dict[str, Any]) -> CollectResult:
        posts = []
        for q in request["queries"]:
            data = self._search({"q": q, "limit": int(self.config["limit_per_query"]), "sort": "latest"})
            for p in data.get("posts", []):
                p["_query"] = q
                posts.append(p)
        return CollectResult(raw={"posts": posts}, meta={"queries": request["queries"], "count": len(posts)})

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for p in result.raw["posts"]:
            uri = p.get("uri", "")
            handle = (p.get("author") or {}).get("handle", "")
            rkey = uri.rsplit("/", 1)[-1]
            record = p.get("record") or {}
            created = record.get("createdAt")
            out.append({"source_id": uri, "source_url": f"https://bsky.app/profile/{handle}/post/{rkey}",
                        "source_name": "Bluesky", "title": None, "content": record.get("text", ""), "author": handle,
                        "published_at": datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None,
                        "engagement": {"likes": p.get("likeCount"), "reposts": p.get("repostCount"), "replies": p.get("replyCount")},
                        "query": p.get("_query"), "language": (record.get("langs") or [None])[0]})
        return out
