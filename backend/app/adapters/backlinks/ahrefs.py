"""Ahrefs API v3 — referring domains for a target host.

Auth is a Bearer API token. Endpoint used:
GET /v3/site-explorer/refdomains  (docs: https://docs.ahrefs.com/en/api/docs/)
Requests consume Ahrefs API units, so the row limit is deliberately conservative.
"""
from __future__ import annotations

from typing import Any, ClassVar

import httpx

from app.adapters.backlinks.common import dedupe, dedupe_links, link_row, row
from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)

API = "https://api.ahrefs.com/v3"
FIELDS = "domain,domain_rating,links_to_target,dofollow_links_to_target,first_seen,last_seen"
LINK_FIELDS = "url_from,url_to,anchor,title,is_dofollow,domain_rating_source,first_seen,last_seen"


class AhrefsBacklinksAdapter(ProviderAdapter):
    key: ClassVar[str] = "ahrefs_backlinks"
    category: ClassVar[str] = "backlinks"
    vendor: ClassVar[str] = "Ahrefs"
    vendor_url: ClassVar[str] = "https://ahrefs.com/api"
    display_name: ClassVar[str] = "Ahrefs API v3"
    description: ClassVar[str] = ("Referring domains and Domain Rating from Ahrefs. Requires a paid plan with API "
                                  "access; every request consumes API units.")
    docs_url: ClassVar[str] = "https://docs.ahrefs.com/en/api/docs/introduction"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_token", "API token", secret=True, required=True, help="Ahrefs → Account settings → API keys."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("limit", "Referring domains per sync", "number", 500, help="Each row costs API units — keep it modest."),
        ConfigField("mode", "Target mode", "select", "subdomains", ["exact", "prefix", "domain", "subdomains"],
                    help="'subdomains' counts links to any subdomain of the site."),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="backlinks", measurement_type="observed",
                            features=["referring_domains", "backlinks", "dofollow", "domain_rating", "first_seen"],
                            notes="Ahrefs index; units are consumed per request and per row.")

    def _headers(self) -> dict[str, str]:
        token = self.credentials.get("api_token")
        if not token:
            raise ProviderError("An Ahrefs API token is required")
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def health_check(self) -> HealthResult:
        try:
            resp = httpx.get(f"{API}/subscription-info/limits-and-usage", headers=self._headers(), timeout=30)
            if resp.status_code in (401, 403):
                return HealthResult(False, f"Ahrefs rejected that token ({resp.status_code})")
            if resp.status_code != 200:
                return HealthResult(False, f"Ahrefs returned HTTP {resp.status_code}: {resp.text[:200]}")
            info = resp.json().get("limits_and_usage", {})
            left = info.get("units_limit_workspace", 0) - info.get("units_usage_workspace", 0)
            return HealthResult(True, f"Ahrefs reachable (~{left} API units left this period)", {"units_left": left})
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Ahrefs check failed: {exc}")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return UsageEstimate(requests=1, unit_type="api units", note="Ahrefs bills per request and per row returned")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        target = request["target"]
        params = {
            "target": target,
            "limit": min(int(request.get("limit") or self.config.get("limit") or 500), 1000),
            "mode": str(self.config.get("mode") or "subdomains"),
            "select": FIELDS,
            "order_by": "links_to_target:desc",
            "aggregation": "similar_links",
        }
        resp = httpx.get(f"{API}/site-explorer/refdomains", params=params, headers=self._headers(), timeout=120)
        if resp.status_code != 200:
            raise ProviderError(f"Ahrefs refdomains failed ({resp.status_code}): {resp.text[:300]}")
        return CollectResult(raw=resp.json(), meta={"target": target, "provider": self.key, **params})

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for item in result.raw.get("refdomains") or []:
            r = row(item.get("domain"),
                    backlinks=item.get("links_to_target"),
                    dofollow=item.get("dofollow_links_to_target"),
                    domain_rating=item.get("domain_rating"),
                    first_seen=item.get("first_seen"),
                    last_seen=item.get("last_seen"))
            if r:
                out.append(r)
        return dedupe(out)

    # ---------------------------------------------------------------- individual links
    def collect_links(self, request: dict[str, Any]) -> CollectResult:
        target = request["target"]
        params = {
            "target": target,
            "limit": min(int(request.get("limit") or 500), 1000),
            "mode": str(self.config.get("mode") or "subdomains"),
            "select": LINK_FIELDS,
            "order_by": "domain_rating_source:desc",
            "aggregation": "all",
        }
        resp = httpx.get(f"{API}/site-explorer/all-backlinks", params=params, headers=self._headers(), timeout=120)
        if resp.status_code != 200:
            raise ProviderError(f"Ahrefs all-backlinks failed ({resp.status_code}): {resp.text[:300]}")
        return CollectResult(raw=resp.json(), meta={"target": target, "provider": self.key, **params})

    def normalize_links(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for item in result.raw.get("backlinks") or []:
            r = link_row(item.get("url_from"), item.get("url_to"),
                         anchor=item.get("anchor"),
                         page_title=item.get("title"),
                         dofollow=item.get("is_dofollow", True),
                         domain_rating=item.get("domain_rating_source"),
                         first_seen=item.get("first_seen"),
                         last_seen=item.get("last_seen"))
            if r:
                out.append(r)
        return dedupe_links(out)
