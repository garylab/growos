"""Google Search Console adapter (first-party search performance).

Two authentication modes:
- service_account: paste a Google service-account JSON and add its email as a user on the GSC property.
- oauth: OAuth 2.0 client (client_id/client_secret) + refresh token obtained through the in-app consent flow.
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any, ClassVar

import httpx

from app.adapters.google_auth import build_auth_url, exchange_code, google_access_token, google_api_error
from app.adapters.base import Capabilities, CollectResult, ConfigField, CredentialField, HealthResult, ProviderAdapter, ProviderError, UsageEstimate

SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
API = "https://www.googleapis.com/webmasters/v3"
API_V1 = "https://searchconsole.googleapis.com/webmasters/v3"


class GoogleSearchConsoleAdapter(ProviderAdapter):
    key: ClassVar[str] = "google_search_console"
    category: ClassVar[str] = "search_performance"
    vendor: ClassVar[str] = "Google"
    vendor_url: ClassVar[str] = "https://search.google.com/search-console"
    display_name: ClassVar[str] = "Google Search Console"
    description: ClassVar[str] = "First-party clicks, impressions, CTR and position by query, page, country and device."
    docs_url: ClassVar[str] = "https://developers.google.com/webmaster-tools/v1/searchanalytics/query"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("service_account_json", "Service account JSON", required=False,
                        help="Paste the JSON key; add the service-account email as a user on the property."),
        CredentialField("client_id", "OAuth client ID", secret=False, required=False,
                        help="Optional override; normally the app-level GOOGLE_OAUTH_CLIENT_ID from .env is used."),
        CredentialField("client_secret", "OAuth client secret", required=False),
        CredentialField("refresh_token", "OAuth refresh token", required=False,
                        help="Filled automatically after the in-app 'Connect Google' flow."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("auth_mode", "Auth mode", "select", "service_account", ["service_account", "oauth"]),
        ConfigField("row_limit", "Max rows per request", "number", 5000),
    ]

    # --------------------------------------------------------------- auth
    oauth_scope: ClassVar[str] = SCOPE

    def _access_token(self) -> str:
        return google_access_token(self.credentials, self.config, SCOPE)

    @staticmethod
    def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
        return build_auth_url(client_id, redirect_uri, state, SCOPE)

    @staticmethod
    def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict[str, Any]:
        return exchange_code(client_id, client_secret, code, redirect_uri)

    # --------------------------------------------------------------- API
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token()}"}

    def list_sites(self) -> list[dict[str, Any]]:
        resp = httpx.get(f"{API}/sites", headers=self._headers(), timeout=30)
        if resp.status_code != 200:
            raise google_api_error(resp, "GSC sites list")
        return resp.json().get("siteEntry", [])

    def health_check(self) -> HealthResult:
        try:
            sites = self.list_sites()
            return HealthResult(True, f"Connected. {len(sites)} property(ies) accessible.",
                                {"sites": [{"siteUrl": s.get("siteUrl"), "permissionLevel": s.get("permissionLevel")} for s in sites]})
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Search Console check failed: {exc}")

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="search_performance", measurement_type="first_party",
                            features=["clicks", "impressions", "ctr", "position", "query", "page", "country", "device"],
                            notes="Data is first-party but sampled/anonymized by Google for low-volume queries.")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        days = (request.get("end_date") - request.get("start_date")).days + 1 if request.get("end_date") else 1
        return UsageEstimate(requests=max(1, days // 7), note="One request per ~5000 rows per dimension set")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        """request: property_uri, start_date, end_date, dimensions (list)."""
        prop = request["property_uri"]
        start: date = request["start_date"]
        end: date = request["end_date"]
        dims = request.get("dimensions") or ["date", "query", "page", "country", "device"]
        row_limit = int(self.config.get("row_limit") or 5000)
        headers = self._headers()
        rows: list[dict[str, Any]] = []
        start_row = 0
        while True:
            body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": dims,
                    "rowLimit": row_limit, "startRow": start_row, "dataState": "all"}
            resp = httpx.post(f"{API_V1}/sites/{_enc(prop)}/searchAnalytics/query",
                              headers=headers, json=body, timeout=120)
            if resp.status_code == 429:
                time.sleep(5)
                continue
            if resp.status_code != 200:
                raise google_api_error(resp, "GSC query")
            batch = resp.json().get("rows", [])
            rows.extend(batch)
            if len(batch) < row_limit:
                break
            start_row += row_limit
            if start_row > 200_000:
                break
        return CollectResult(raw={"rows": rows, "request": {**body, "property": prop}},
                             meta={"property_uri": prop, "dimensions": dims, "start_date": start.isoformat(),
                                   "end_date": end.isoformat(), "row_count": len(rows)})

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        dims = result.meta["dimensions"]
        out = []
        for row in result.raw["rows"]:
            keys = dict(zip(dims, row.get("keys", []), strict=False))
            out.append({"date": date.fromisoformat(keys.get("date")) if keys.get("date") else date.fromisoformat(result.meta["end_date"]),
                        "query": keys.get("query", ""), "page": keys.get("page", ""),
                        "country": (keys.get("country") or "").upper(), "device": (keys.get("device") or "").lower(),
                        "clicks": int(row.get("clicks", 0)), "impressions": int(row.get("impressions", 0)),
                        "ctr": float(row.get("ctr", 0)), "position": float(row.get("position", 0))})
        return out


def _enc(prop: str) -> str:
    from urllib.parse import quote
    return quote(prop, safe="")


def default_window(days: int = 28) -> tuple[date, date]:
    end = date.today() - timedelta(days=3)  # GSC data lags ~2-3 days
    return end - timedelta(days=days - 1), end
