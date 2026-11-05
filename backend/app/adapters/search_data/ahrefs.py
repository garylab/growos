"""Ahrefs API v3 — keyword metrics and organic keywords.

  GET /v3/keywords-explorer/overview     volume, difficulty, CPC for given keywords
  GET /v3/site-explorer/organic-keywords what a host ranks for

Ahrefs has no cheap per-keyword live SERP call, so rank tracking is derived from organic-keywords rather than
pretending to be a live check.
"""
from __future__ import annotations

from typing import Any, ClassVar

import httpx

from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)
from app.adapters.search_data.common import best_per_keyword, dedupe_metrics, metric_row, ranked_row

API = "https://api.ahrefs.com/v3"


class AhrefsSearchDataAdapter(ProviderAdapter):
    key: ClassVar[str] = "ahrefs_keywords"
    category: ClassVar[str] = "search_data"
    vendor: ClassVar[str] = "Ahrefs"
    vendor_url: ClassVar[str] = "https://ahrefs.com/api"
    display_name: ClassVar[str] = "Ahrefs Keywords & Site Explorer"
    description: ClassVar[str] = ("Keyword volume and difficulty, and the organic keywords any domain ranks for. "
                                  "Consumes Ahrefs API units per request and per row.")
    docs_url: ClassVar[str] = "https://docs.ahrefs.com/en/api/docs/introduction"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_token", "API token", secret=True, required=True, help="Ahrefs → Account settings → API keys."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("country", "Country code", "string", "us", help="Two-letter market code, e.g. us, gb, de."),
        ConfigField("ranked_limit", "Ranked keywords per host", "number", 500),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="search_data", measurement_type="estimated",
                            features=["keyword_metrics", "ranked_keywords", "keyword_gap"],
                            notes="No live per-keyword SERP endpoint; positions come from organic-keywords.")

    def _headers(self) -> dict[str, str]:
        token = self.credentials.get("api_token")
        if not token:
            raise ProviderError("An Ahrefs API token is required")
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        resp = httpx.get(f"{API}{path}", params=params, headers=self._headers(), timeout=120)
        if resp.status_code != 200:
            raise ProviderError(f"Ahrefs {path} failed ({resp.status_code}): {resp.text[:300]}")
        return resp.json()

    def health_check(self) -> HealthResult:
        try:
            resp = httpx.get(f"{API}/subscription-info/limits-and-usage", headers=self._headers(), timeout=30)
            if resp.status_code in (401, 403):
                return HealthResult(False, f"Ahrefs rejected that token ({resp.status_code})")
            if resp.status_code != 200:
                return HealthResult(False, f"Ahrefs returned HTTP {resp.status_code}: {resp.text[:200]}")
            info = resp.json().get("limits_and_usage", {})
            left = info.get("units_limit_workspace", 0) - info.get("units_usage_workspace", 0)
            return HealthResult(True, f"Ahrefs reachable (~{left} API units left)", {"units_left": left})
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Ahrefs check failed: {exc}")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return UsageEstimate(requests=1, unit_type="api units", note="Ahrefs bills per request and per row")

    def collect_keyword_metrics(self, request: dict[str, Any]) -> CollectResult:
        keywords = [k for k in (request.get("keywords") or []) if k][:1000]
        if not keywords:
            raise ProviderError("No keywords to price")
        params = {"keywords": ",".join(keywords), "country": str(self.config.get("country") or "us"),
                  "select": "keyword,volume_monthly,difficulty,cpc"}
        return CollectResult(raw=self._get("/keywords-explorer/overview", params),
                             meta={"provider": self.key, "keywords": len(keywords), **params})

    def normalize_keyword_metrics(self, result: CollectResult) -> list[dict[str, Any]]:
        rows = result.raw.get("keywords") or result.raw.get("metrics") or []
        out = []
        for item in rows:
            r = metric_row(item.get("keyword"),
                           search_volume=item.get("volume_monthly", item.get("volume")),
                           difficulty=item.get("difficulty"),
                           cpc=item.get("cpc"))
            if r:
                out.append(r)
        return dedupe_metrics(out)

    def collect_ranked_keywords(self, request: dict[str, Any]) -> CollectResult:
        host = request["host"]
        params = {"target": host, "country": str(self.config.get("country") or "us"),
                  "limit": min(int(request.get("limit") or self.config.get("ranked_limit") or 500), 1000),
                  "select": "keyword,best_position,best_position_url,volume,keyword_difficulty,sum_traffic",
                  "order_by": "best_position:asc", "mode": "subdomains"}
        return CollectResult(raw=self._get("/site-explorer/organic-keywords", params),
                             meta={"provider": self.key, "host": host, **params})

    def normalize_ranked_keywords(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for item in result.raw.get("keywords") or []:
            r = ranked_row(item.get("keyword"), item.get("best_position"),
                           url=item.get("best_position_url"),
                           search_volume=item.get("volume"),
                           traffic=item.get("sum_traffic"),
                           difficulty=item.get("keyword_difficulty"))
            if r:
                out.append(r)
        return best_per_keyword(out)
