"""Bing Webmaster Tools adapter (first-party search performance, second search engine).

Why this exists alongside Search Console: Bing's index is what Microsoft Copilot answers from, so Bing is not a
rounding error for a product that measures AI visibility. Until now Bing could only be seen through SerpApi,
which costs money per query and reports rank only — it cannot say how many people saw the site or clicked it.
This is the first-party, free-of-charge source for those numbers.

Authentication is an API key, not OAuth: Bing Webmaster Tools → Settings → API access → API key. The key is
account-wide, so one connection covers every site verified in that account.

What the API does and does not give, because it differs from GSC in ways the data model has to respect:

* `GetRankAndTrafficStats` returns **daily** totals (impressions and clicks per date) — directly comparable to
  GSC's daily totals.
* `GetQueryStats` and `GetPageStats` return **one row per query or page aggregated over Bing's own rolling
  window**, not a row per day. There is no way to ask for a specific date range. We therefore stamp those rows
  with the last date Bing reported traffic for and mark the window in `meta`, rather than inventing a daily
  series that the API never provided.
* There is no country or device breakdown in these endpoints, so those fields stay empty rather than being
  guessed at.

Built against the JSON endpoint (`/webmaster/api.svc/json/...`) only. Microsoft retired the legacy SOAP and POX
endpoints on 2026-08-31, so neither is used here and neither should be added as a fallback. Because the key is
the customer's, this adapter has not been exercised against the live API in development — run the connection's
health check first: it calls `GetUserSites` and prints the exact site URLs the account has verified, which is
also the string each domain's Bing site URL has to match.
"""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar

import httpx

from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)

API = "https://ssl.bing.com/webmaster/api.svc/json"

# Bing serialises dates as the .NET epoch form `/Date(1699228800000)/`, sometimes with a trailing timezone
# offset such as `/Date(1699228800000+0000)/`.
DOTNET_DATE = re.compile(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/")

# The three shapes of data this adapter can collect, as request["dataset"].
DAILY, QUERIES, PAGES = "rank_traffic", "query_stats", "page_stats"
DATASETS = (DAILY, QUERIES, PAGES)

_METHOD = {DAILY: "GetRankAndTrafficStats", QUERIES: "GetQueryStats", PAGES: "GetPageStats"}


class BingWebmasterAdapter(ProviderAdapter):
    key: ClassVar[str] = "bing_webmaster"
    category: ClassVar[str] = "search_performance"
    vendor: ClassVar[str] = "Microsoft"
    vendor_url: ClassVar[str] = "https://www.bing.com/webmasters"
    display_name: ClassVar[str] = "Bing Webmaster Tools"
    description: ClassVar[str] = ("First-party Bing clicks, impressions and position by query and page. Bing's "
                                  "index is what Microsoft Copilot answers from, so this is both a second search "
                                  "engine and the measurable half of Copilot visibility. Free.")
    docs_url: ClassVar[str] = "https://learn.microsoft.com/en-us/bingwebmaster/getting-access"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_key", "API key", secret=True, required=True,
                        help="Bing Webmaster Tools → Settings → API access → API key. Account-wide: one key "
                             "covers every site verified in the account."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("row_limit", "Max rows per dataset", "number", 5000,
                    help="Bing returns its whole rolling window in one response; this only caps how much of it "
                         "we store."),
    ]

    # ------------------------------------------------------------------ API
    def _call(self, method: str, **params: Any) -> Any:
        key = (self.credentials.get("api_key") or "").strip()
        if not key:
            raise ProviderError("Bing Webmaster Tools needs an API key. Add it under Integrations.")
        try:
            resp = httpx.get(f"{API}/{method}", params={"apikey": key, **params}, timeout=60)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Bing Webmaster request failed: {exc}") from exc
        if resp.status_code == 401:
            raise ProviderError("Bing Webmaster rejected the API key (HTTP 401). Re-copy it from Settings → API access.")
        if resp.status_code == 429:
            raise ProviderError("Bing Webmaster rate limit reached (HTTP 429). Try again later.")
        if resp.status_code != 200:
            raise ProviderError(f"Bing Webmaster {method} failed: HTTP {resp.status_code} {resp.text[:200]}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderError(f"Bing Webmaster {method} returned a non-JSON response") from exc
        # Every JSON endpoint wraps its result in "d". An error is reported inside a 200 response, so the body
        # has to be inspected rather than trusting the status code.
        if isinstance(payload, dict) and "d" in payload:
            return payload["d"]
        if isinstance(payload, dict) and payload.get("Message"):
            raise ProviderError(f"Bing Webmaster {method}: {payload['Message'][:300]}")
        return payload

    def list_sites(self) -> list[dict[str, Any]]:
        data = self._call("GetUserSites")
        return [s for s in (data or []) if isinstance(s, dict)]

    def health_check(self) -> HealthResult:
        try:
            sites = self.list_sites()
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Bing Webmaster check failed: {exc}")
        urls = [s.get("Url") for s in sites if s.get("Url")]
        return HealthResult(True, f"Connected. {len(urls)} verified site(s).",
                            {"sites": urls[:50],
                             "note": "Use one of these exact URLs as the domain's Bing site URL."})

    def get_capabilities(self) -> Capabilities:
        return Capabilities(
            category="search_performance", measurement_type="first_party",
            features=["clicks", "impressions", "ctr", "position", "query", "page"],
            notes="Bing only. Daily totals are per-date; query and page rows are aggregates over Bing's own "
                  "rolling window, and carry no country or device breakdown.")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        datasets = request.get("datasets") or DATASETS
        return UsageEstimate(requests=len(datasets), note="One request per dataset; the whole window comes back at once")

    # ------------------------------------------------------------------ collect
    def collect(self, request: dict[str, Any]) -> CollectResult:
        """request: site_url, dataset (one of DATASETS)."""
        site_url = request["site_url"]
        dataset = request.get("dataset") or DAILY
        if dataset not in _METHOD:
            raise ProviderError(f"Unknown Bing dataset '{dataset}'")
        rows = self._call(_METHOD[dataset], siteUrl=site_url) or []
        if not isinstance(rows, list):
            rows = [rows]
        return CollectResult(raw={"rows": rows, "dataset": dataset, "site_url": site_url},
                             meta={"site_url": site_url, "dataset": dataset, "row_count": len(rows)})

    # ------------------------------------------------------------------ normalize
    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        """Bing rows → the same shape `SearchObservation` already stores for Search Console."""
        dataset = result.raw["dataset"]
        rows = [r for r in result.raw["rows"] if isinstance(r, dict)]
        limit = int(self.config.get("row_limit") or 5000)
        if dataset == DAILY:
            return _normalize_daily(rows)[:limit]
        # Query and page rows have no date of their own, so they are stamped with the window they describe.
        stamp = result.meta.get("as_of") or date.today() - timedelta(days=1)
        if isinstance(stamp, str):
            stamp = date.fromisoformat(stamp)
        return (_normalize_queries(rows, stamp) if dataset == QUERIES else _normalize_pages(rows, stamp))[:limit]


def _normalize_daily(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        day = _parse_date(r.get("Date"))
        if day is None:
            continue
        clicks, impressions = _int(r.get("Clicks")), _int(r.get("Impressions"))
        out.append({"date": day, "query": "", "page": "", "country": "", "device": "",
                    "clicks": clicks, "impressions": impressions,
                    "ctr": _ratio(clicks, impressions), "position": 0.0})
    return out


def _normalize_queries(rows: list[dict[str, Any]], stamp: date) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        query = (r.get("Query") or "").strip()
        if not query:
            continue
        clicks, impressions = _int(r.get("Clicks")), _int(r.get("Impressions"))
        out.append({"date": stamp, "query": query[:500], "page": "", "country": "", "device": "",
                    "clicks": clicks, "impressions": impressions, "ctr": _ratio(clicks, impressions),
                    "position": _position(r)})
    return out


def _normalize_pages(rows: list[dict[str, Any]], stamp: date) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        page = (r.get("Query") or r.get("Url") or "").strip()  # GetPageStats puts the URL in "Query"
        if not page:
            continue
        clicks, impressions = _int(r.get("Clicks")), _int(r.get("Impressions"))
        out.append({"date": stamp, "query": "", "page": page[:2000], "country": "", "device": "",
                    "clicks": clicks, "impressions": impressions, "ctr": _ratio(clicks, impressions),
                    "position": _position(r)})
    return out


def _position(row: dict[str, Any]) -> float:
    """Average position, preferring the impression-weighted figure so it means what GSC's `position` means.

    Bing reports two averages. `AvgImpressionPosition` is over every impression, which is GSC's definition.
    `AvgClickPosition` is over clicks only and is therefore a different, flattering number — using it would make
    Bing and Google positions silently incomparable on the same chart.
    """
    for field_name in ("AvgImpressionPosition", "AvgClickPosition"):
        value = row.get(field_name)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return 0.0


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _ratio(clicks: int, impressions: int) -> float:
    """CTR, computed rather than read: Bing does not return one, and GSC's `ctr` is a 0-1 ratio."""
    return round(clicks / impressions, 6) if impressions else 0.0


def _parse_date(value: Any) -> date | None:
    """Bing's `/Date(ms)/`, an ISO string, or nothing."""
    if not value:
        return None
    if isinstance(value, str):
        m = DOTNET_DATE.search(value)
        if m:
            return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=UTC).date()
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def last_reported_date(daily_rows: list[dict[str, Any]]) -> date:
    """The most recent date Bing reported traffic for, used to stamp the undated query/page aggregates.

    Falls back to yesterday when the daily series is empty, which keeps the rows storable instead of discarding
    data because one of three requests came back thin.
    """
    dates = [r["date"] for r in daily_rows if r.get("date")]
    return max(dates) if dates else date.today() - timedelta(days=1)
