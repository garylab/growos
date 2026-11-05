"""Chrome UX Report API (field data from real Chrome users). Optional; requires an API key."""
from __future__ import annotations

from typing import Any, ClassVar

import httpx

from app.adapters.google_auth import google_api_error
from app.adapters.base import Capabilities, CollectResult, ConfigField, CredentialField, HealthResult, ProviderAdapter, ProviderError
from app.core.safe_http import validate_url

CRUX_ENDPOINT = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"


class CruxAdapter(ProviderAdapter):
    key: ClassVar[str] = "crux"
    category: ClassVar[str] = "performance"
    vendor: ClassVar[str] = "Google"
    vendor_url: ClassVar[str] = "https://developer.chrome.com/docs/crux"
    display_name: ClassVar[str] = "Chrome UX Report API"
    description: ClassVar[str] = "Field Core Web Vitals (p75) for an origin or URL from real Chrome users."
    docs_url: ClassVar[str] = "https://developer.chrome.com/docs/crux/api"
    requires_connection: ClassVar[bool] = False
    credential_fields: ClassVar[list[CredentialField]] = [CredentialField("api_key", "Google API key", required=False, help="Optional when GOOGLE_API_KEY is set in .env.")]
    config_fields: ClassVar[list[ConfigField]] = [ConfigField("form_factor", "Form factor", "select", "PHONE", ["PHONE", "DESKTOP", "TABLET"])]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="performance", measurement_type="field", features=["core_web_vitals_field"])

    def health_check(self) -> HealthResult:
        try:
            self.collect({"origin": "https://www.google.com"})
            return HealthResult(True, "CrUX API key accepted")
        except ProviderError as exc:
            return HealthResult(False, str(exc))

    def collect(self, request: dict[str, Any]) -> CollectResult:
        if not self.credentials.get("api_key"):
            raise ProviderError("CrUX needs a Google API key: set GOOGLE_API_KEY in .env or add it on this provider.")
        body: dict[str, Any] = {"formFactor": request.get("form_factor") or self.config["form_factor"]}
        if request.get("url"):
            body["url"] = validate_url(request["url"])
        else:
            body["origin"] = validate_url(request["origin"]).rstrip("/")
        resp = httpx.post(CRUX_ENDPOINT, params={"key": self.credentials["api_key"]}, json=body, timeout=30)
        if resp.status_code == 404:
            raise ProviderError("CrUX has no data for this origin/URL (not enough traffic)")
        if resp.status_code != 200:
            raise google_api_error(resp, "CrUX API")
        return CollectResult(raw=resp.json(), meta=body)

    def normalize(self, result: CollectResult) -> dict[str, Any]:
        rec = result.raw.get("record", {})
        m = rec.get("metrics", {})
        p75 = lambda k: (m.get(k) or {}).get("percentiles", {}).get("p75")  # noqa: E731
        return {"measurement_type": "field", "strategy": result.meta.get("formFactor", "PHONE").lower(),
                "url": result.meta.get("url") or result.meta.get("origin"), "tool_version": "crux-api",
                "scores": {}, "metrics": {"lcp_ms": p75("largest_contentful_paint"), "cls": p75("cumulative_layout_shift"),
                                          "inp_ms": p75("interaction_to_next_paint"), "fcp_ms": p75("first_contentful_paint"),
                                          "ttfb_ms": p75("experimental_time_to_first_byte")},
                "audits": [], "collection_period": rec.get("collectionPeriod")}
