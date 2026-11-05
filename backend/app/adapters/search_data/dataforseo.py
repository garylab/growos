"""DataForSEO Labs + SERP — keyword value, what a domain ranks for, and live positions.

Endpoints used:
  POST /v3/dataforseo_labs/google/keyword_overview/live   volume, difficulty, CPC, intent for given keywords
  POST /v3/dataforseo_labs/google/ranked_keywords/live     what a host ranks for (used for the keyword gap)
  POST /v3/serp/google/organic/live/{advanced|regular}      live SERP for one tracked keyword

`regular` returns organic results only, so SERP features are unavailable on that mode by design — not a parsing
failure. `advanced` costs more and reports AI overviews, People Also Ask and the rest.
"""
from __future__ import annotations

import base64
from typing import Any, ClassVar
from urllib.parse import urlsplit

import httpx

from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)
from app.adapters.search_data.common import (best_per_keyword, dedupe_metrics, metric_row, rank_row, ranked_row)

API = "https://api.dataforseo.com/v3"


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every item across every task/result block of a DataForSEO response."""
    out = []
    for task in payload.get("tasks") or []:
        for block in task.get("result") or []:
            out.extend(block.get("items") or [])
    return out


class DataForSEOSearchDataAdapter(ProviderAdapter):
    key: ClassVar[str] = "dataforseo_labs"
    category: ClassVar[str] = "search_data"
    vendor: ClassVar[str] = "DataForSEO"
    vendor_url: ClassVar[str] = "https://dataforseo.com"
    display_name: ClassVar[str] = "DataForSEO Labs & SERP"
    description: ClassVar[str] = ("Search volume, keyword difficulty and CPC; what any domain ranks for (for the "
                                  "competitor keyword gap); and live SERP positions for tracked keywords.")
    docs_url: ClassVar[str] = "https://docs.dataforseo.com/v3/dataforseo_labs/google/overview/"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("login", "API login", secret=False, required=True, help="The email you sign in to DataForSEO with."),
        CredentialField("password", "API password", secret=True, required=True, help="From Dashboard → API Access."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("location_name", "Location", "string", "United States",
                    help="Market to price keywords in, e.g. 'United States' or 'United Kingdom'."),
        ConfigField("language_name", "Language", "string", "English"),
        ConfigField("ranked_limit", "Ranked keywords per host", "number", 500,
                    help="How many ranking keywords to pull per site for the gap analysis."),
        ConfigField("serp_depth", "SERP depth for rank tracking", "number", 100,
                    help="How far down to look for your site. 100 is one page of results in API terms."),
        ConfigField("serp_mode", "SERP detail", "select", "advanced", ["advanced", "regular"],
                    help="'advanced' also reports SERP features such as AI overviews and People Also Ask; "
                         "'regular' returns organic results only and costs less."),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="search_data", measurement_type="estimated",
                            features=["keyword_metrics", "ranked_keywords", "rank_tracking", "keyword_gap"],
                            notes="Volume and difficulty are modelled estimates, not measurements.")

    def _auth(self) -> str:
        login, password = self.credentials.get("login"), self.credentials.get("password")
        if not login or not password:
            raise ProviderError("DataForSEO login and password are required")
        return "Basic " + base64.b64encode(f"{login}:{password}".encode()).decode()

    def _post(self, path: str, body: list[dict[str, Any]]) -> dict[str, Any]:
        resp = httpx.post(f"{API}{path}", json=body,
                          headers={"Authorization": self._auth(), "Content-Type": "application/json"}, timeout=120)
        if resp.status_code != 200:
            raise ProviderError(f"DataForSEO {path} failed ({resp.status_code}): {resp.text[:300]}")
        payload = resp.json()
        task = (payload.get("tasks") or [{}])[0]
        if task.get("status_code") not in (20000, None):
            raise ProviderError(f"DataForSEO task error: {task.get('status_message')}")
        return payload

    def _locale(self) -> dict[str, str]:
        return {"location_name": str(self.config.get("location_name") or "United States"),
                "language_name": str(self.config.get("language_name") or "English")}

    def health_check(self) -> HealthResult:
        try:
            resp = httpx.get(f"{API}/appendix/user_data", headers={"Authorization": self._auth()}, timeout=30)
            if resp.status_code == 401:
                return HealthResult(False, "DataForSEO rejected those credentials (401)")
            if resp.status_code != 200:
                return HealthResult(False, f"DataForSEO returned HTTP {resp.status_code}")
            data = (resp.json().get("tasks") or [{}])[0].get("result") or [{}]
            balance = (data[0] or {}).get("money", {}).get("balance")
            return HealthResult(True, f"DataForSEO Labs reachable (balance {balance})", {"balance": balance})
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"DataForSEO check failed: {exc}")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return UsageEstimate(requests=1, unit_type="requests", note="One live DataForSEO request")

    # ---------------------------------------------------------------- keyword metrics
    def collect_keyword_metrics(self, request: dict[str, Any]) -> CollectResult:
        keywords = [k for k in (request.get("keywords") or []) if k][:700]
        if not keywords:
            raise ProviderError("No keywords to price")
        body = [{"keywords": keywords, **self._locale()}]
        payload = self._post("/dataforseo_labs/google/keyword_overview/live", body)
        return CollectResult(raw=payload, meta={"provider": self.key, "keywords": len(keywords), **self._locale()})

    def normalize_keyword_metrics(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for item in _items(result.raw):
            info = item.get("keyword_info") or {}
            props = item.get("keyword_properties") or {}
            intent = ((item.get("search_intent_info") or {}).get("main_intent"))
            r = metric_row(item.get("keyword"),
                           search_volume=info.get("search_volume"),
                           difficulty=props.get("keyword_difficulty"),
                           cpc=info.get("cpc"),
                           competition=info.get("competition"),
                           intent=intent)
            if r:
                out.append(r)
        return dedupe_metrics(out)

    # ---------------------------------------------------------------- what a host ranks for
    def collect_ranked_keywords(self, request: dict[str, Any]) -> CollectResult:
        host = request["host"]
        limit = min(int(request.get("limit") or self.config.get("ranked_limit") or 500), 1000)
        body = [{"target": host, "limit": limit, **self._locale(),
                 "order_by": ["ranked_serp_element.serp_item.rank_group,asc"]}]
        payload = self._post("/dataforseo_labs/google/ranked_keywords/live", body)
        return CollectResult(raw=payload, meta={"provider": self.key, "host": host, "limit": limit, **self._locale()})

    def normalize_ranked_keywords(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for item in _items(result.raw):
            kd = item.get("keyword_data") or {}
            info = kd.get("keyword_info") or {}
            props = kd.get("keyword_properties") or {}
            serp = ((item.get("ranked_serp_element") or {}).get("serp_item")) or {}
            r = ranked_row(kd.get("keyword"), serp.get("rank_group"),
                           url=serp.get("url"),
                           search_volume=info.get("search_volume"),
                           traffic=serp.get("etv"),
                           difficulty=props.get("keyword_difficulty"))
            if r:
                out.append(r)
        return best_per_keyword(out)

    # ---------------------------------------------------------------- live rank for one keyword
    def collect_rank(self, request: dict[str, Any]) -> CollectResult:
        keyword = request["keyword"]
        mode = "regular" if str(self.config.get("serp_mode") or "advanced") == "regular" else "advanced"
        body = [{"keyword": keyword, "depth": min(int(self.config.get("serp_depth") or 100), 700), **self._locale()}]
        payload = self._post(f"/serp/google/organic/live/{mode}", body)
        return CollectResult(raw=payload, meta={"provider": self.key, "keyword": keyword, "serp_mode": mode,
                                                **self._locale()})

    def normalize_rank(self, result: CollectResult) -> dict[str, Any] | None:
        """Position of `host` on this SERP, plus which SERP features are present."""
        host = (result.meta.get("host") or "").lower().removeprefix("www.")
        items = _items(result.raw)
        # Only the advanced mode returns non-organic blocks; on regular there is nothing to report, not zero features.
        features = sorted({str(i.get("type")) for i in items if i.get("type") and i.get("type") != "organic"})
        position, url = None, None
        for item in items:
            if item.get("type") != "organic":
                continue
            item_host = (urlsplit(str(item.get("url") or "")).hostname or "").lower().removeprefix("www.")
            if host and (item_host == host or item_host.endswith("." + host)):
                position, url = item.get("rank_group"), item.get("url")
                break
        return rank_row(result.meta.get("keyword"), position=position, url=url, serp_features=features)
