"""Generic backlink source: point it at any JSON HTTP endpoint and map its fields to referring domains.

This is how you connect a provider GrowOS does not bundle — a smaller index, a RapidAPI endpoint, your own
crawler's output, an internal export. GrowOS endorses no source; the choice and its terms are yours. Fetches go
through the SSRF-safe client, so the endpoint must be a public host.

Mirrors the Custom source adapter used for brand mentions, so the two feel the same to configure.
"""
from __future__ import annotations

import json
from typing import Any, ClassVar

from app.adapters.backlinks.common import dedupe, dedupe_links, link_row, row
from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)
from app.core.safe_http import UnsafeURLError, safe_get, validate_url


def _dig(obj: Any, path: str) -> Any:
    """Walk a dotted path like 'data.items.0.domain'. An empty path returns obj unchanged."""
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


def _truthy(value: Any) -> bool:
    """Interpret a provider's flag field: 'false', '0', '' and None all mean not set."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "0", "no", "null")
    return bool(value)


def _field(item: Any, path: str) -> Any:
    """Read a mapped field. An unmapped (blank) path means 'this source does not provide it' — never the whole record,
    which is what _dig('') would return."""
    return _dig(item, path) if path else None


class CustomBacklinksAdapter(ProviderAdapter):
    key: ClassVar[str] = "custom_backlinks"
    category: ClassVar[str] = "backlinks"
    vendor: ClassVar[str] = "Custom JSON API"
    display_name: ClassVar[str] = "Custom backlinks API (any JSON endpoint)"
    description: ClassVar[str] = ("Connect any JSON endpoint that lists referring domains and map its field names. "
                                  "Use {target} in the URL for the site being checked. You are responsible for the "
                                  "source's terms of service.")
    docs_url: ClassVar[str] = ""
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_key", "API key / token", secret=True, required=False,
                        help="Optional. Sent as configured below, or usable as {api_key} in the URL."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("request_url", "Request URL", "string", "",
                    help="e.g. https://api.example.com/refdomains?site={target}&key={api_key}"),
        ConfigField("auth_header", "Auth header", "select", "none", ["none", "Authorization: Bearer", "X-API-Key"],
                    help="How to send the key, if it is not already in the URL."),
        ConfigField("items_path", "Path to the list", "string", "",
                    help="Dotted path to the array of domains, e.g. 'data.refdomains'. Blank if the body is the array."),
        ConfigField("map_domain", "Field: referring domain", "string", "domain"),
        ConfigField("map_backlinks", "Field: backlinks", "string", "backlinks"),
        ConfigField("map_dofollow", "Field: dofollow links", "string", ""),
        ConfigField("map_rating", "Field: domain rating", "string", ""),
        ConfigField("map_first_seen", "Field: first seen", "string", ""),
        ConfigField("map_last_seen", "Field: last seen", "string", ""),
        ConfigField("map_example_url", "Field: example linking URL", "string", ""),
        ConfigField("limit", "Referring domains per sync", "number", 500),
        ConfigField("links_url", "Individual links: request URL", "string", "",
                    help="Optional second endpoint listing single links. {target} and {api_key} work here too."),
        ConfigField("links_items_path", "Individual links: path to the list", "string", ""),
        ConfigField("map_url_from", "Field: linking page URL", "string", "url_from"),
        ConfigField("map_url_to", "Field: target URL", "string", "url_to"),
        ConfigField("map_anchor", "Field: anchor text", "string", "anchor"),
        ConfigField("map_page_title", "Field: linking page title", "string", ""),
        ConfigField("map_nofollow", "Field: nofollow flag", "string", "",
                    help="A truthy value here marks the link nofollow. Leave blank to treat every link as dofollow."),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="backlinks", measurement_type="observed",
                            features=["referring_domains", "backlinks"],
                            notes="User-supplied endpoint; coverage and terms are whatever the source provides.")

    def _fill(self, raw: str, target: str) -> str:
        filled = raw.replace("{target}", target).replace("{api_key}", str(self.credentials.get("api_key") or ""))
        try:
            return validate_url(filled)
        except UnsafeURLError as exc:
            raise ProviderError(str(exc)) from exc

    def _url(self, target: str) -> str:
        raw = str(self.config.get("request_url") or "").strip()
        if not raw:
            raise ProviderError("Set the request URL for this custom backlinks source")
        return self._fill(raw, target)

    def _headers(self) -> dict[str, str]:
        key = self.credentials.get("api_key")
        mode = str(self.config.get("auth_header") or "none")
        if not key or mode == "none":
            return {}
        return {"Authorization": f"Bearer {key}"} if mode.startswith("Authorization") else {"X-API-Key": str(key)}

    def health_check(self) -> HealthResult:
        if not str(self.config.get("request_url") or "").strip():
            return HealthResult(False, "No request URL configured")
        try:
            result = self.collect({"target": "example.com"})
            rows = self.normalize(result)
            if not rows:
                return HealthResult(False, "Endpoint responded, but no rows matched the field mapping — check the paths")
            return HealthResult(True, f"Endpoint reachable, {len(rows)} referring domain(s) parsed", {"sample": rows[0]})
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Custom backlinks check failed: {exc}")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return UsageEstimate(requests=1, note="One request to your configured endpoint")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        url = self._url(request["target"])
        resp = safe_get(url, headers=self._headers(), timeout=60)
        try:
            payload = json.loads(resp.text)
        except ValueError as exc:
            raise ProviderError(f"Endpoint did not return JSON: {resp.text[:200]}") from exc
        return CollectResult(raw=payload, meta={"target": request["target"], "provider": self.key, "url": url})

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        items = _dig(result.raw, str(self.config.get("items_path") or ""))
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            return []
        limit = int(self.config.get("limit") or 500)
        out = []
        for item in items[:limit]:
            r = row(_field(item, str(self.config.get("map_domain") or "domain")),
                    backlinks=_field(item, str(self.config.get("map_backlinks") or "")) or 0,
                    dofollow=_field(item, str(self.config.get("map_dofollow") or "")) or 0,
                    domain_rating=_field(item, str(self.config.get("map_rating") or "")),
                    first_seen=_field(item, str(self.config.get("map_first_seen") or "")),
                    last_seen=_field(item, str(self.config.get("map_last_seen") or "")),
                    example_url=_field(item, str(self.config.get("map_example_url") or "")))
            if r:
                out.append(r)
        return dedupe(out)

    # ---------------------------------------------------------------- individual links
    def collect_links(self, request: dict[str, Any]) -> CollectResult:
        raw_url = str(self.config.get("links_url") or "").strip()
        if not raw_url:
            raise ProviderError("No individual-links URL configured for this source")
        url = self._fill(raw_url, request["target"])
        resp = safe_get(url, headers=self._headers(), timeout=60)
        try:
            payload = json.loads(resp.text)
        except ValueError as exc:
            raise ProviderError(f"Links endpoint did not return JSON: {resp.text[:200]}") from exc
        return CollectResult(raw=payload, meta={"target": request["target"], "provider": self.key, "url": url})

    def normalize_links(self, result: CollectResult) -> list[dict[str, Any]]:
        items = _dig(result.raw, str(self.config.get("links_items_path") or ""))
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            return []
        nofollow_field = str(self.config.get("map_nofollow") or "")
        out = []
        for item in items[:int(self.config.get("limit") or 500)]:
            nofollow = _field(item, nofollow_field)
            r = link_row(_field(item, str(self.config.get("map_url_from") or "url_from")),
                         _field(item, str(self.config.get("map_url_to") or "url_to")),
                         anchor=_field(item, str(self.config.get("map_anchor") or "anchor")),
                         page_title=_field(item, str(self.config.get("map_page_title") or "")),
                         dofollow=not _truthy(nofollow) if nofollow_field else True,
                         domain_rating=_field(item, str(self.config.get("map_rating") or "")),
                         first_seen=_field(item, str(self.config.get("map_first_seen") or "")),
                         last_seen=_field(item, str(self.config.get("map_last_seen") or "")))
            if r:
                out.append(r)
        return dedupe_links(out)
