"""Google PageSpeed Insights API: runs Lighthouse (lab) on Google's infrastructure and also returns CrUX field data.
API key optional but recommended for quota (https://developers.google.com/speed/docs/insights/v5/get-started)."""
from __future__ import annotations

from typing import Any, ClassVar

import httpx

from app.adapters.google_auth import google_api_error
from app.adapters.base import Capabilities, CollectResult, ConfigField, CredentialField, HealthResult, ProviderAdapter, ProviderError, UsageEstimate
from app.core.safe_http import validate_url

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


class PageSpeedInsightsAdapter(ProviderAdapter):
    key: ClassVar[str] = "pagespeed_insights"
    category: ClassVar[str] = "performance"
    vendor: ClassVar[str] = "Google"
    vendor_url: ClassVar[str] = "https://developers.google.com/speed/docs/insights/v5/get-started"
    display_name: ClassVar[str] = "Google Lighthouse via PageSpeed Insights"
    description: ClassVar[str] = "Lab performance/SEO/accessibility audits (Lighthouse) plus CrUX field data for a URL."
    docs_url: ClassVar[str] = "https://developers.google.com/speed/docs/insights/v5/get-started"
    requires_connection: ClassVar[bool] = False
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_key", "Google API key", required=False, help="Optional; raises the request quota."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("strategy", "Strategy", "select", "mobile", ["mobile", "desktop"]),
        ConfigField("categories", "Categories", "string", "performance,seo,accessibility,best-practices"),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="performance", measurement_type="lab",
                            features=["lighthouse", "core_web_vitals_lab", "crux_field_if_available"])

    def health_check(self) -> HealthResult:
        try:
            res = self.collect({"url": "https://example.com/", "strategy": "mobile", "categories": "performance"})
            version = (res.raw.get("lighthouseResult") or {}).get("lighthouseVersion")
            mode = "with API key" if self.credentials.get("api_key") else "keyless (shared quota — add GOOGLE_API_KEY for 25k/day)"
            return HealthResult(True, f"PageSpeed Insights reachable (Lighthouse {version}, {mode})", {"lighthouse": version})
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"PageSpeed Insights check failed: {exc}")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return UsageEstimate(requests=len(request.get("urls", [request.get("url")])), note="PSI quota: 25k/day with key")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        url = validate_url(request["url"])
        strategy = request.get("strategy") or self.config["strategy"]
        cats = [c.strip() for c in str(request.get("categories") or self.config["categories"]).split(",") if c.strip()]
        params: list[tuple[str, str]] = [("url", url), ("strategy", strategy)] + [("category", c) for c in cats]
        if self.credentials.get("api_key"):
            params.append(("key", self.credentials["api_key"]))
        try:
            resp = httpx.get(PSI_ENDPOINT, params=params, timeout=120)
        except httpx.HTTPError as exc:
            raise ProviderError(f"PageSpeed request failed: {exc}") from exc
        if resp.status_code == 429:
            hint = ("The shared keyless PageSpeed quota is exhausted. Add a Google API key (Cloud Console → APIs & Services → enable "
                    "'PageSpeed Insights API' → Credentials → API key) as GOOGLE_API_KEY in .env or on this provider's connection; "
                    "with a key the limit is 25,000 queries/day.") if not self.credentials.get("api_key") else "Daily PageSpeed quota for your API key is exhausted; retry tomorrow."
            raise ProviderError(f"PageSpeed API quota exceeded (429). {hint}")
        if resp.status_code != 200:
            raise google_api_error(resp, "PageSpeed API")
        return CollectResult(raw=resp.json(), meta={"url": url, "strategy": strategy})

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        """Returns up to two observations: lab (Lighthouse) and field (CrUX) if present."""
        raw = result.raw
        lh = raw.get("lighthouseResult") or {}
        out: list[dict[str, Any]] = []
        if lh:
            audits = lh.get("audits", {})
            metrics = {
                "lcp_ms": _num(audits, "largest-contentful-paint"), "cls": _num(audits, "cumulative-layout-shift"),
                "tbt_ms": _num(audits, "total-blocking-time"), "fcp_ms": _num(audits, "first-contentful-paint"),
                "speed_index_ms": _num(audits, "speed-index"), "tti_ms": _num(audits, "interactive"),
            }
            failing = [{"id": k, "title": v.get("title"), "score": v.get("score"), "display": v.get("displayValue")}
                       for k, v in audits.items()
                       if isinstance(v.get("score"), (int, float)) and v["score"] < 0.9 and v.get("scoreDisplayMode") != "informative"]
            failing.sort(key=lambda a: a["score"] or 0)
            out.append({
                "measurement_type": "lab", "strategy": result.meta["strategy"], "url": result.meta["url"],
                "tool_version": lh.get("lighthouseVersion"),
                "scores": {k: round((v.get("score") or 0) * 100) for k, v in (lh.get("categories") or {}).items()},
                "metrics": metrics, "audits": failing[:40],
            })
        field_data = raw.get("loadingExperience") or {}
        if field_data.get("metrics"):
            m = field_data["metrics"]
            out.append({
                "measurement_type": "field", "strategy": result.meta["strategy"], "url": result.meta["url"],
                "tool_version": "crux", "scores": {"overall_category": field_data.get("overall_category")},
                "metrics": {
                    "lcp_ms": (m.get("LARGEST_CONTENTFUL_PAINT_MS") or {}).get("percentile"),
                    "cls": ((m.get("CUMULATIVE_LAYOUT_SHIFT_SCORE") or {}).get("percentile") or 0) / 100,
                    "inp_ms": (m.get("INTERACTION_TO_NEXT_PAINT") or {}).get("percentile"),
                    "fcp_ms": (m.get("FIRST_CONTENTFUL_PAINT_MS") or {}).get("percentile"),
                    "ttfb_ms": (m.get("EXPERIMENTAL_TIME_TO_FIRST_BYTE") or {}).get("percentile"),
                    "origin_fallback": bool(field_data.get("origin_fallback")),
                }, "audits": [],
            })
        return out


def _num(audits: dict[str, Any], key: str) -> float | None:
    v = (audits.get(key) or {}).get("numericValue")
    return round(v, 3) if isinstance(v, (int, float)) else None
