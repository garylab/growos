"""Google Analytics 4 adapter (GA4 Data API runReport). First-party website analytics.

Imports daily landing-page sessions, users, key events (conversions) and revenue by session source/medium into
AnalyticsEvent rows. Auth: service account (add its email as a Viewer on the GA4 property) or OAuth.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, ClassVar

import httpx

from app.adapters.base import Capabilities, CollectResult, ConfigField, CredentialField, HealthResult, ProviderAdapter, ProviderError, UsageEstimate
from app.adapters.google_auth import google_access_token, google_api_error

SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
DATA_API = "https://analyticsdata.googleapis.com/v1beta"
ADMIN_API = "https://analyticsadmin.googleapis.com/v1beta"
PAGE_SIZE = 100_000


class GoogleAnalytics4Adapter(ProviderAdapter):
    key: ClassVar[str] = "google_analytics_4"
    category: ClassVar[str] = "analytics"
    vendor: ClassVar[str] = "Google"
    vendor_url: ClassVar[str] = "https://analytics.google.com"
    display_name: ClassVar[str] = "Google Analytics 4"
    description: ClassVar[str] = "First-party sessions, users, key events (conversions), engagement and revenue per landing page from the GA4 Data API."
    docs_url: ClassVar[str] = "https://developers.google.com/analytics/devguides/reporting/data/v1"
    oauth_scope: ClassVar[str] = SCOPE
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("service_account_json", "Service account JSON", required=False,
                        help="Paste the JSON key; add the service-account email as a Viewer on the GA4 property."),
        CredentialField("client_id", "OAuth client ID", secret=False, required=False, help="Optional override; normally the app-level GOOGLE_OAUTH_CLIENT_ID from .env is used."),
        CredentialField("client_secret", "OAuth client secret", required=False),
        CredentialField("refresh_token", "OAuth refresh token", required=False, help="Filled automatically after the in-app 'Connect Google' flow."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("auth_mode", "Auth mode", "select", "service_account", ["service_account", "oauth"]),
        ConfigField("conversion_metric", "Conversion metric", "select", "keyEvents", ["keyEvents", "conversions"],
                    help="GA4 renamed conversions to key events; older properties may still report 'conversions'."),
    ]

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {google_access_token(self.credentials, self.config, SCOPE)}"}

    def list_properties(self) -> list[dict[str, Any]]:
        """Properties visible to the credentials (Admin API account summaries)."""
        resp = httpx.get(f"{ADMIN_API}/accountSummaries", headers=self._headers(), params={"pageSize": 200}, timeout=30)
        if resp.status_code != 200:
            raise google_api_error(resp, "GA4 account summaries")
        out = []
        for acc in resp.json().get("accountSummaries", []):
            for p in acc.get("propertySummaries", []):
                out.append({"property": p.get("property"), "display_name": p.get("displayName"), "account": acc.get("displayName")})
        return out

    def list_web_streams(self, max_properties: int = 25) -> list[dict[str, Any]]:
        """Web data streams (property, stream, default URI host) for the accessible properties — used to auto-match domains."""
        from urllib.parse import urlsplit
        headers = self._headers()
        out = []
        for p in self.list_properties()[:max_properties]:
            r = httpx.get(f"{ADMIN_API}/{p['property']}/dataStreams", headers=headers, timeout=30)
            if r.status_code != 200:
                continue
            for s in r.json().get("dataStreams", []):
                uri = (s.get("webStreamData") or {}).get("defaultUri")
                if uri:
                    out.append({"property": p["property"], "stream": s.get("name"), "display_name": s.get("displayName"),
                                "uri": uri, "host": (urlsplit(uri).hostname or "").lower()})
        return out

    def health_check(self) -> HealthResult:
        try:
            props = self.list_properties()
            return HealthResult(True, f"Connected. {len(props)} GA4 property(ies) accessible.", {"properties": props[:50]})
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Google Analytics check failed: {exc}")

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="analytics", measurement_type="first_party",
                            features=["sessions", "users", "conversions", "revenue", "engagement", "landing_page", "source_medium"],
                            notes="GA4 applies thresholding/sampling on small segments; numbers are first-party but may be withheld.")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return UsageEstimate(requests=2, note="GA4 Data API quota: 25k tokens/day per property (standard)")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        """request: property_id (numeric or 'properties/123'), start_date, end_date."""
        prop = str(request["property_id"]).strip()
        if not prop.startswith("properties/"):
            prop = f"properties/{prop}"
        start: date = request["start_date"]
        end: date = request["end_date"]
        metric = request.get("conversion_metric") or self.config.get("conversion_metric") or "keyEvents"
        headers = self._headers()
        rows: list[dict[str, Any]] = []
        offset = 0
        body: dict[str, Any] = {}
        while True:
            body = {"dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
                    "dimensions": [{"name": "date"}, {"name": "landingPagePlusQueryString"}, {"name": "sessionSource"}, {"name": "sessionMedium"}],
                    "metrics": [{"name": "sessions"}, {"name": "totalUsers"}, {"name": metric}, {"name": "totalRevenue"},
                                {"name": "engagedSessions"}, {"name": "userEngagementDuration"}],
                    "limit": PAGE_SIZE, "offset": offset, "keepEmptyRows": False}
            resp = httpx.post(f"{DATA_API}/{prop}:runReport", headers=headers, json=body, timeout=120)
            if resp.status_code != 200:
                raise google_api_error(resp, "GA4 runReport")
            data = resp.json()
            batch = data.get("rows", [])
            rows.extend(batch)
            total = int(data.get("rowCount") or 0)
            offset += len(batch)
            if not batch or offset >= total or offset >= 1_000_000:
                break
        return CollectResult(raw={"rows": rows, "request": body, "property": prop},
                             meta={"property_id": prop, "start_date": start.isoformat(), "end_date": end.isoformat(),
                                   "row_count": len(rows), "conversion_metric": metric})

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for row in result.raw["rows"]:
            d = [v.get("value", "") for v in row.get("dimensionValues", [])]
            m = [v.get("value", "0") for v in row.get("metricValues", [])]
            if len(d) < 4 or len(m) < 4:
                continue
            try:
                day = date(int(d[0][:4]), int(d[0][4:6]), int(d[0][6:8]))
            except ValueError:
                continue
            out.append({"date": day, "landing_page": d[1] or "(not set)", "source": _clean(d[2]), "medium": _clean(d[3]),
                        "sessions": _int(m[0]), "users": _int(m[1]), "conversions": _int(m[2]), "revenue": _float(m[3]),
                        # Engagement metrics were added later; older stored artifacts replay without them.
                        "engaged_sessions": _int(m[4]) if len(m) > 4 else 0,
                        "engagement_time_sec": _float(m[5]) if len(m) > 5 else 0.0})
        return out


def _clean(v: str) -> str:
    return "" if v in ("(not set)", "(none)") else v[:120]


def _int(v: str) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _float(v: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def default_window(days: int = 28) -> tuple[date, date]:
    end = date.today() - timedelta(days=1)
    return end - timedelta(days=days - 1), end
