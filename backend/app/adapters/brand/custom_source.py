"""Generic brand-mention source: point it at any JSON HTTP endpoint and map its fields to GrowOS mentions.

This is how you connect a third-party aggregator you have chosen and whose terms you accept — an Apify dataset, a
RapidAPI endpoint, your own scraper's output, a saved-search service. GrowOS ships no scraper of its own and does not
endorse any source; the choice and its terms of service are yours. All fetches go through the SSRF-safe client, so the
endpoint must be a public host.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import quote, urlsplit

import httpx

from app.adapters.base import Capabilities, CollectResult, ConfigField, CredentialField, HealthResult, ProviderAdapter, ProviderError
from app.core.safe_http import UnsafeURLError, resolve_public_ip, safe_get, validate_url


def _dig(obj: Any, path: str) -> Any:
    """Walk a dotted path like 'data.items.0.text'. Empty path returns obj."""
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _parse_time(v: Any) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
        n = float(v)
        if n > 1e12:  # milliseconds
            n /= 1000
        try:
            return datetime.fromtimestamp(n, tz=UTC)
        except (ValueError, OSError):
            return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(str(v), fmt)
            except ValueError:
                continue
    return None


class CustomSourceAdapter(ProviderAdapter):
    key: ClassVar[str] = "custom_source"
    category: ClassVar[str] = "brand"
    vendor: ClassVar[str] = "Custom JSON API"
    display_name: ClassVar[str] = "Custom source (any JSON API)"
    description: ClassVar[str] = ("Connect any JSON HTTP endpoint — an Apify dataset, a RapidAPI endpoint, your own "
                                  "aggregator — and map its fields to mentions. You are responsible for the source's terms.")
    docs_url: ClassVar[str] = ""
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_key", "API key / token", required=False,
                        help="Optional secret. Use {api_key} in the URL or headers to inject it (kept encrypted)."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("request_url", "Request URL", "string", "",
                    help="Use {query} for the search term (URL-encoded) and {api_key} for the secret. e.g. https://api.example.com/search?q={query}&key={api_key}"),
        ConfigField("method", "Method", "select", "GET", ["GET", "POST"]),
        ConfigField("headers_json", "Headers (JSON)", "string", "",
                    help='Optional. e.g. {"X-RapidAPI-Key": "{api_key}", "X-RapidAPI-Host": "twttrapi.p.rapidapi.com"}'),
        ConfigField("body_template", "POST body (JSON, for POST)", "string", "", help='Use {query}. e.g. {"query": "{query}", "count": 25}'),
        ConfigField("timeout_seconds", "Request timeout (seconds)", "number", 30,
                    help="Raise this for endpoints that run a scrape on demand - an Apify run-sync URL can take 60-120s."),
        ConfigField("items_path", "Path to the list of items", "string", "data",
                    help="Dotted path to the array in the response. '' if the response is itself an array."),
        ConfigField("map_id", "Field: id", "string", "id"),
        ConfigField("map_url", "Field: post URL", "string", "url"),
        ConfigField("map_text", "Field: text/content", "string", "text"),
        ConfigField("map_author", "Field: author", "string", "author"),
        ConfigField("map_published", "Field: published time", "string", "created_at"),
        ConfigField("map_language", "Field: language", "string", "lang"),
        ConfigField("map_likes", "Field: likes (optional)", "string", ""),
        ConfigField("map_reposts", "Field: reposts (optional)", "string", ""),
        ConfigField("map_replies", "Field: replies (optional)", "string", ""),
        ConfigField("source_label", "Source label", "string", "Custom"),
        ConfigField("limit_per_query", "Max items per query", "number", 25),
    ]

    # --------------------------------------------------------------- fetch
    def _fill(self, template: str, query: str, *, encode: bool = True) -> str:
        """Substitute {query} and {api_key}. encode=True percent-encodes for a URL; False JSON-escapes for a body."""
        q = quote(query) if encode else json.dumps(query)[1:-1]
        return template.replace("{query}", q).replace("{api_key}", self.credentials.get("api_key", ""))

    def _timeout(self) -> float:
        try:
            t = float(self.config.get("timeout_seconds") or 30)
        except (TypeError, ValueError):
            t = 30.0
        return max(5.0, min(t, 300.0))

    def _headers(self) -> dict[str, str]:
        raw = (self.config.get("headers_json") or "").strip()
        if not raw:
            return {}
        try:
            hdrs = json.loads(raw)
        except ValueError as exc:
            raise ProviderError(f"Headers must be valid JSON: {exc}") from exc
        return {k: str(v).replace("{api_key}", self.credentials.get("api_key", "")) for k, v in hdrs.items()}

    def _fetch(self, query: str) -> Any:
        url_t = (self.config.get("request_url") or "").strip()
        if not url_t:
            raise ProviderError("Request URL is not configured")
        url = self._fill(url_t, query)
        try:
            validate_url(url)
        except UnsafeURLError as exc:
            raise ProviderError(f"Unsafe or invalid URL: {exc}") from exc
        method = (self.config.get("method") or "GET").upper()
        if method == "GET":
            resp = safe_get(url, headers=self._headers(), timeout=self._timeout(), max_bytes=10_000_000)
            if not 200 <= resp.status_code < 300:
                raise ProviderError(f"Source returned HTTP {resp.status_code}: {resp.text[:200]}")
            text = resp.text
        else:
            host = urlsplit(url).hostname or ""
            resolve_public_ip(host)  # SSRF guard before POST
            body = self._fill(self.config.get("body_template") or "{}", query, encode=False)
            try:
                payload = json.loads(body)
            except ValueError as exc:
                raise ProviderError(f"POST body must be valid JSON: {exc}") from exc
            r = httpx.post(url, headers={"Content-Type": "application/json", **self._headers()}, json=payload, timeout=self._timeout())
            if not 200 <= r.status_code < 300:
                raise ProviderError(f"Source returned HTTP {r.status_code}: {r.text[:200]}")
            text = r.text
        try:
            return json.loads(text)
        except ValueError as exc:
            raise ProviderError(f"Response is not JSON: {exc}") from exc

    # --------------------------------------------------------------- adapter API
    def health_check(self) -> HealthResult:
        if not (self.config.get("request_url") or "").strip():
            return HealthResult(False, "Set a request URL with a {query} placeholder.")
        try:
            data = self._fetch("test")
            items = _dig(data, self.config.get("items_path") or "")
            n = len(items) if isinstance(items, list) else 0
            if not isinstance(items, list):
                return HealthResult(False, f"Reached the endpoint, but '{self.config.get('items_path')}' is not a list. "
                                           f"Top-level keys: {list(data)[:8] if isinstance(data, dict) else type(data).__name__}")
            return HealthResult(True, f"Reached the source and found {n} item(s) under '{self.config.get('items_path') or '(root)'}'.")
        except ProviderError as exc:
            return HealthResult(False, str(exc))
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Check failed: {exc}")

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="brand", measurement_type="observed", features=["mentions", "engagement"],
                            notes="Whatever the configured endpoint returns. You accept the source's terms of service.")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        limit = max(1, int(self.config.get("limit_per_query") or 25))
        items, errors = [], []
        for q in request["queries"]:
            try:
                data = self._fetch(q)
            except ProviderError as exc:
                errors.append(f"{q}: {exc}")
                continue
            arr = _dig(data, self.config.get("items_path") or "")
            if isinstance(arr, list):
                for it in arr[:limit]:
                    items.append({"_item": it, "_query": q})
        if errors and not items:
            raise ProviderError("; ".join(errors)[:400])
        return CollectResult(raw={"items": items, "errors": errors}, meta={"queries": request["queries"], "count": len(items)})

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        c = self.config
        label = c.get("source_label") or "Custom"

        def eng(it: Any, key: str) -> Any:
            path = c.get(key)
            return _dig(it, path) if path else None

        out = []
        for wrap in result.raw["items"]:
            it = wrap["_item"]
            sid = _dig(it, c.get("map_id") or "") or _dig(it, c.get("map_url") or "")
            if sid is None:
                continue
            out.append({
                "source_id": f"{label.lower()}:{sid}"[:500], "source_url": _dig(it, c.get("map_url") or ""),
                "source_name": label, "title": None, "content": str(_dig(it, c.get("map_text") or "") or ""),
                "author": _dig(it, c.get("map_author") or ""), "published_at": _parse_time(_dig(it, c.get("map_published") or "")),
                "engagement": {k: eng(it, f"map_{k2}") for k, k2 in (("likes", "likes"), ("reposts", "reposts"), ("replies", "replies"))
                               if eng(it, f"map_{k2}") is not None},
                "query": wrap["_query"], "language": _dig(it, c.get("map_language") or "")})
        return out
