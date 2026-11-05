"""Semrush Analytics API — referring domains for a target host.

Semrush returns semicolon-separated text, not JSON, so the raw payload is stored as the body plus the header row.
Endpoint used: GET /analytics/v1/?type=backlinks_refdomains
(docs: https://developer.semrush.com/api/v3/analytics/backlinks/)
"""
from __future__ import annotations

from typing import Any, ClassVar

import httpx

from app.adapters.backlinks.common import dedupe, dedupe_links, link_row, row
from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)

API = "https://api.semrush.com/analytics/v1/"


class SemrushBacklinksAdapter(ProviderAdapter):
    key: ClassVar[str] = "semrush_backlinks"
    category: ClassVar[str] = "backlinks"
    vendor: ClassVar[str] = "Semrush"
    vendor_url: ClassVar[str] = "https://www.semrush.com/api-analytics/"
    display_name: ClassVar[str] = "Semrush Backlinks"
    description: ClassVar[str] = ("Referring domains and Authority Score from Semrush. Needs a subscription with API "
                                  "units; each row consumes units.")
    docs_url: ClassVar[str] = "https://developer.semrush.com/api/v3/analytics/backlinks/"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_key", "API key", secret=True, required=True, help="Semrush → Subscription info → API units."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("limit", "Referring domains per sync", "number", 500, help="Each row consumes API units."),
        ConfigField("target_type", "Target type", "select", "root_domain", ["root_domain", "domain", "url"]),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="backlinks", measurement_type="observed",
                            features=["referring_domains", "backlinks", "domain_rating"],
                            notes="Semrush index; returns CSV-style rows, not JSON.")

    def _key(self) -> str:
        key = self.credentials.get("api_key")
        if not key:
            raise ProviderError("A Semrush API key is required")
        return key

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
        rows = int(request.get("limit") or self.config.get("limit") or 500)
        return UsageEstimate(requests=1, unit_type="api units", note=f"Semrush charges per row (~{rows} rows)")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        target = request["target"]
        params = {
            "type": "backlinks_refdomains",
            "key": self._key(),
            "target": target,
            "target_type": str(self.config.get("target_type") or "root_domain"),
            "export_columns": "domain,domain_ascore,backlinks_num,first_seen,last_seen",
            "display_limit": min(int(request.get("limit") or self.config.get("limit") or 500), 1000),
            "display_sort": "backlinks_num_desc",
        }
        resp = httpx.get(API, params=params, timeout=120)
        body = resp.text
        if resp.status_code != 200 or body.startswith("ERROR"):
            raise ProviderError(f"Semrush backlinks_refdomains failed ({resp.status_code}): {body[:300]}")
        safe = {k: v for k, v in params.items() if k != "key"}   # never store the key in an artifact
        return CollectResult(raw={"body": body}, meta={"target": target, "provider": self.key, **safe})

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        body = (result.raw or {}).get("body") or ""
        lines = [l for l in body.splitlines() if l.strip()]
        if len(lines) < 2:
            return []
        header = [h.strip().lower() for h in lines[0].split(";")]
        out = []
        for line in lines[1:]:
            cells = line.split(";")
            if len(cells) != len(header):
                continue
            rec = dict(zip(header, cells))
            r = row(rec.get("domain"),
                    backlinks=rec.get("backlinks_num"),
                    domain_rating=rec.get("domain_ascore"),
                    first_seen=rec.get("first_seen"),
                    last_seen=rec.get("last_seen"))
            if r:
                out.append(r)
        return dedupe(out)

    # ---------------------------------------------------------------- individual links
    def collect_links(self, request: dict[str, Any]) -> CollectResult:
        target = request["target"]
        params = {
            "type": "backlinks",
            "key": self._key(),
            "target": target,
            "target_type": str(self.config.get("target_type") or "root_domain"),
            "export_columns": "source_url,source_title,target_url,anchor,nofollow,page_ascore,first_seen,last_seen",
            "display_limit": min(int(request.get("limit") or 500), 1000),
            "display_sort": "page_ascore_desc",
        }
        resp = httpx.get(API, params=params, timeout=120)
        body = resp.text
        if resp.status_code != 200 or body.startswith("ERROR"):
            raise ProviderError(f"Semrush backlinks failed ({resp.status_code}): {body[:300]}")
        safe = {k: v for k, v in params.items() if k != "key"}
        return CollectResult(raw={"body": body}, meta={"target": target, "provider": self.key, **safe})

    def normalize_links(self, result: CollectResult) -> list[dict[str, Any]]:
        body = (result.raw or {}).get("body") or ""
        lines = [l for l in body.splitlines() if l.strip()]
        if len(lines) < 2:
            return []
        header = [h.strip().lower() for h in lines[0].split(";")]
        out = []
        for line in lines[1:]:
            cells = line.split(";")
            if len(cells) != len(header):
                continue
            rec = dict(zip(header, cells))
            # Semrush reports nofollow as "true"/"false"; dofollow is its inverse.
            r = link_row(rec.get("source_url"), rec.get("target_url"),
                         anchor=rec.get("anchor"),
                         page_title=rec.get("source_title"),
                         dofollow=str(rec.get("nofollow", "")).strip().lower() not in ("true", "1"),
                         domain_rating=rec.get("page_ascore"),
                         first_seen=rec.get("first_seen"),
                         last_seen=rec.get("last_seen"))
            if r:
                out.append(r)
        return dedupe_links(out)
