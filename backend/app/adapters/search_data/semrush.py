"""Semrush Analytics API — keyword metrics and organic positions.

  type=phrase_these   volume, CPC and competition for a batch of phrases
  type=domain_organic what a domain ranks for

Responses are semicolon-separated text, so the raw payload is the body itself.
"""
from __future__ import annotations

from typing import Any, ClassVar

import httpx

from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)
from app.adapters.search_data.common import best_per_keyword, dedupe_metrics, metric_row, ranked_row

API = "https://api.semrush.com/"


def _rows(body: str) -> list[dict[str, str]]:
    lines = [l for l in (body or "").splitlines() if l.strip()]
    if len(lines) < 2:
        return []
    header = [h.strip().lower() for h in lines[0].split(";")]
    out = []
    for line in lines[1:]:
        cells = line.split(";")
        if len(cells) == len(header):
            out.append(dict(zip(header, cells)))
    return out


class SemrushSearchDataAdapter(ProviderAdapter):
    key: ClassVar[str] = "semrush_keywords"
    category: ClassVar[str] = "search_data"
    vendor: ClassVar[str] = "Semrush"
    vendor_url: ClassVar[str] = "https://www.semrush.com/api-analytics/"
    display_name: ClassVar[str] = "Semrush Keywords & Domain Analytics"
    description: ClassVar[str] = ("Keyword volume, CPC and competition, plus the organic keywords a domain ranks "
                                  "for. Each row consumes Semrush API units.")
    docs_url: ClassVar[str] = "https://developer.semrush.com/api/v3/analytics/overview/"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_key", "API key", secret=True, required=True, help="Semrush → Subscription info → API units."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("database", "Database", "string", "us", help="Semrush regional database, e.g. us, uk, de."),
        ConfigField("ranked_limit", "Ranked keywords per host", "number", 500),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="search_data", measurement_type="estimated",
                            features=["keyword_metrics", "ranked_keywords", "keyword_gap"],
                            notes="Semrush returns CSV-style rows; no keyword-difficulty field on phrase_these.")

    def _key(self) -> str:
        key = self.credentials.get("api_key")
        if not key:
            raise ProviderError("A Semrush API key is required")
        return key

    def _get(self, params: dict[str, Any]) -> str:
        resp = httpx.get(API, params={**params, "key": self._key()}, timeout=120)
        body = resp.text
        if resp.status_code != 200 or body.startswith("ERROR"):
            raise ProviderError(f"Semrush {params.get('type')} failed ({resp.status_code}): {body[:300]}")
        return body

    def health_check(self) -> HealthResult:
        try:
            resp = httpx.get("https://www.semrush.com/users/countapiunits.html", params={"key": self._key()}, timeout=30)
            text = resp.text.strip()
            if resp.status_code != 200 or not text.isdigit():
                return HealthResult(False, f"Semrush rejected that key: {text[:120] or resp.status_code}")
            return HealthResult(True, f"Semrush reachable ({text} API units left)", {"units_left": int(text)})
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Semrush check failed: {exc}")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return UsageEstimate(requests=1, unit_type="api units", note="Semrush charges per row returned")

    def collect_keyword_metrics(self, request: dict[str, Any]) -> CollectResult:
        keywords = [k for k in (request.get("keywords") or []) if k][:100]   # phrase_these caps the batch
        if not keywords:
            raise ProviderError("No keywords to price")
        params = {"type": "phrase_these", "phrase": ";".join(keywords),
                  "database": str(self.config.get("database") or "us"),
                  "export_columns": "Ph,Nq,Cp,Co,Nr"}
        return CollectResult(raw={"body": self._get(params)}, meta={"provider": self.key, "keywords": len(keywords)})

    def normalize_keyword_metrics(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for rec in _rows((result.raw or {}).get("body", "")):
            r = metric_row(rec.get("keyword"), search_volume=rec.get("search volume"),
                           cpc=rec.get("cpc"), competition=rec.get("competition"))
            if r:
                out.append(r)
        return dedupe_metrics(out)

    def collect_ranked_keywords(self, request: dict[str, Any]) -> CollectResult:
        host = request["host"]
        params = {"type": "domain_organic", "domain": host,
                  "database": str(self.config.get("database") or "us"),
                  "display_limit": min(int(request.get("limit") or self.config.get("ranked_limit") or 500), 1000),
                  "export_columns": "Ph,Po,Nq,Ur,Tr", "display_sort": "po_asc"}
        return CollectResult(raw={"body": self._get(params)}, meta={"provider": self.key, "host": host})

    def normalize_ranked_keywords(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for rec in _rows((result.raw or {}).get("body", "")):
            r = ranked_row(rec.get("keyword"), rec.get("position"),
                           url=rec.get("url"), search_volume=rec.get("search volume"),
                           traffic=rec.get("traffic (%)"))
            if r:
                out.append(r)
        return best_per_keyword(out)
