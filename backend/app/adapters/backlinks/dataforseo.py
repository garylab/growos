"""DataForSEO Backlinks API — referring domains for a target host.

Auth is HTTP Basic with the API login and password. Endpoint used:
POST /v3/backlinks/referring_domains/live   (docs: https://docs.dataforseo.com/v3/backlinks/referring_domains/live/)
"""
from __future__ import annotations

import base64
from typing import Any, ClassVar

import httpx

from app.adapters.backlinks.common import as_int, dedupe, dedupe_links, link_row, row
from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)

API = "https://api.dataforseo.com/v3"


class DataForSEOBacklinksAdapter(ProviderAdapter):
    key: ClassVar[str] = "dataforseo_backlinks"
    category: ClassVar[str] = "backlinks"
    vendor: ClassVar[str] = "DataForSEO"
    vendor_url: ClassVar[str] = "https://dataforseo.com"
    display_name: ClassVar[str] = "DataForSEO Backlinks"
    description: ClassVar[str] = ("Referring domains and backlink counts from the DataForSEO index. Pay-as-you-go; "
                                  "a referring-domains call costs a fraction of a cent per request.")
    docs_url: ClassVar[str] = "https://docs.dataforseo.com/v3/backlinks/referring_domains/live/"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("login", "API login", secret=False, required=True, help="The email you sign in to DataForSEO with."),
        CredentialField("password", "API password", secret=True, required=True, help="From Dashboard → API Access."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("limit", "Referring domains per sync", "number", 1000, help="Up to 1000 per request."),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="backlinks", measurement_type="observed",
                            features=["referring_domains", "backlinks", "dofollow", "first_seen"],
                            notes="Third-party index; coverage differs from Ahrefs and Semrush.")

    def _auth(self) -> str:
        login, password = self.credentials.get("login"), self.credentials.get("password")
        if not login or not password:
            raise ProviderError("DataForSEO login and password are required")
        return "Basic " + base64.b64encode(f"{login}:{password}".encode()).decode()

    def health_check(self) -> HealthResult:
        try:
            resp = httpx.get(f"{API}/appendix/user_data", headers={"Authorization": self._auth()}, timeout=30)
            if resp.status_code == 401:
                return HealthResult(False, "DataForSEO rejected those credentials (401)")
            if resp.status_code != 200:
                return HealthResult(False, f"DataForSEO returned HTTP {resp.status_code}")
            data = (resp.json().get("tasks") or [{}])[0].get("result") or [{}]
            balance = (data[0] or {}).get("money", {}).get("balance")
            return HealthResult(True, f"DataForSEO reachable (balance {balance})", {"balance": balance})
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"DataForSEO check failed: {exc}")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return UsageEstimate(requests=1, unit_type="requests", note="One live referring-domains request")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        target = request["target"]
        limit = int(request.get("limit") or self.config.get("limit") or 1000)
        body = [{"target": target, "limit": min(limit, 1000), "order_by": ["backlinks,desc"]}]
        resp = httpx.post(f"{API}/backlinks/referring_domains/live", json=body,
                          headers={"Authorization": self._auth(), "Content-Type": "application/json"}, timeout=120)
        if resp.status_code != 200:
            raise ProviderError(f"DataForSEO referring_domains failed ({resp.status_code}): {resp.text[:300]}")
        payload = resp.json()
        task = (payload.get("tasks") or [{}])[0]
        if task.get("status_code") not in (20000, None):
            raise ProviderError(f"DataForSEO task error: {task.get('status_message')}")
        return CollectResult(raw=payload, meta={"target": target, "limit": limit, "provider": self.key})

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for task in result.raw.get("tasks") or []:
            for block in task.get("result") or []:
                for item in block.get("items") or []:
                    # DataForSEO reports link attributes as counts; dofollow is whatever is not marked nofollow.
                    total = as_int(item.get("backlinks"))
                    nofollow = as_int((item.get("referring_links_attributes") or {}).get("nofollow"))
                    r = row(item.get("domain"),
                            backlinks=total,
                            dofollow=max(0, total - nofollow),
                            domain_rating=item.get("rank"),
                            first_seen=item.get("first_seen"),
                            last_seen=item.get("last_seen"))
                    if r:
                        out.append(r)
        return dedupe(out)

    # ---------------------------------------------------------------- individual links
    def collect_links(self, request: dict[str, Any]) -> CollectResult:
        target = request["target"]
        limit = min(int(request.get("limit") or 500), 1000)
        body = [{"target": target, "limit": limit, "mode": "as_is",
                 "order_by": ["domain_from_rank,desc"],
                 "filters": [["dofollow", "=", True]] if request.get("dofollow_only") else None}]
        body = [{k: v for k, v in b.items() if v is not None} for b in body]
        resp = httpx.post(f"{API}/backlinks/backlinks/live", json=body,
                          headers={"Authorization": self._auth(), "Content-Type": "application/json"}, timeout=120)
        if resp.status_code != 200:
            raise ProviderError(f"DataForSEO backlinks failed ({resp.status_code}): {resp.text[:300]}")
        return CollectResult(raw=resp.json(), meta={"target": target, "limit": limit, "provider": self.key})

    def normalize_links(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for task in result.raw.get("tasks") or []:
            for block in task.get("result") or []:
                for item in block.get("items") or []:
                    r = link_row(item.get("url_from"), item.get("url_to"),
                                 anchor=item.get("anchor"),
                                 page_title=item.get("page_from_title"),
                                 dofollow=item.get("dofollow", True),
                                 domain_rating=item.get("domain_from_rank"),
                                 first_seen=item.get("first_seen"),
                                 last_seen=item.get("last_seen"))
                    if r:
                        out.append(r)
        return dedupe_links(out)
