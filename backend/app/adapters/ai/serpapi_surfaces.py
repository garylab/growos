"""AI answer surfaces via SerpApi: Google AI Overview, Google AI Mode and Bing Copilot.

Why this sits in the `ai` category next to OpenAI and Gemini: GEO asks "when someone searches this, does the AI
answer mention us and cite us?". The model APIs answer a near version of that question — but nobody's customers
query the OpenAI API. These three are the surfaces real users see, so they are sampled through exactly the same
prompts, run grouping and mention extraction, and land in the same AIAnswerObservation rows. `grounding_type` is
`provider_search` because the surface did its own retrieval; no prompt of ours chose the sources.

One connection samples one surface, so tracking two surfaces means two connections — that keeps `provider_key`
plus `model` meaningful per observation and lets each surface be enabled, disabled and billed on its own.

Cost: one credit per prompt per sample, except AI Overview, which costs two when Google withholds the overview
behind a page token (see `_ai_overview`). There are no tokens to count, so the project's AI token budget does not
apply to this provider — the ceiling is the SerpApi plan.
"""
from __future__ import annotations

import time
from typing import Any, ClassVar

from app.adapters.ai.common import AIAnswer, Citation, dedupe_citations, domain_of
from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)
from app.adapters.serpapi_client import (SerpApiClient, account_summary, flatten_text_blocks, quota_details,
                                         reference_links)

SURFACES = {
    "google_ai_overview": "Google AI Overview",
    "google_ai_mode": "Google AI Mode",
    "bing_copilot": "Bing Copilot",
}


class SerpApiAISurfacesAdapter(ProviderAdapter):
    key: ClassVar[str] = "serpapi_ai"
    category: ClassVar[str] = "ai"
    vendor: ClassVar[str] = "SerpApi"
    vendor_url: ClassVar[str] = "https://serpapi.com"
    display_name: ClassVar[str] = "SerpApi AI surfaces (AI Overview / AI Mode / Copilot)"
    description: ClassVar[str] = ("Samples the AI answers real users see — Google AI Overview, Google AI Mode or Bing "
                                  "Copilot — including which sources each one cites. One connection per surface.")
    docs_url: ClassVar[str] = "https://serpapi.com/google-ai-overview-api"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_key", "API key", secret=True, required=True,
                        help="serpapi.com → Dashboard → Your Private API Key. Leave blank to use SERPAPI_API_KEY from the server's environment."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("surface", "AI surface to sample", "select", "google_ai_overview", list(SURFACES),
                    help="Which answer engine this connection measures. Add a second connection for a second surface."),
        ConfigField("location", "Location", "string", "",
                    help="Optional city/country the search appears to come from, e.g. 'Austin, Texas, United States'. "
                         "Leave blank to use the country below only."),
        ConfigField("timeout_seconds", "Request timeout", "number", 90,
                    help="AI surfaces are slower than a plain SERP; 90s is a safe floor."),
    ]

    def get_capabilities(self) -> Capabilities:
        surface = self._surface()
        return Capabilities(
            category="ai", measurement_type="observed",
            features=["answer_sampling", "citation_tracking", "ai_surface"],
            notes=f"Scraped from {SURFACES[surface]} as a user in the prompt's country would see it. No model "
                  f"tokens are consumed; usage is counted in SerpApi searches.")

    def _surface(self) -> str:
        s = str(self.config.get("surface") or "google_ai_overview")
        return s if s in SURFACES else "google_ai_overview"

    def _client(self) -> SerpApiClient:
        return SerpApiClient(self.credentials.get("api_key"), timeout=float(self.config.get("timeout_seconds") or 90))

    def health_check(self) -> HealthResult:
        try:
            acct = self._client().account()
        except ProviderError as exc:
            return HealthResult(False, str(exc))
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"SerpApi check failed: {exc}")
        left = acct.get("total_searches_left")
        msg = f"{account_summary(acct)} · sampling {SURFACES[self._surface()]}"
        if left is not None and int(left) <= 0:
            return HealthResult(False, f"{msg} — no searches left on this plan")
        return HealthResult(True, msg, quota_details(acct))

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        n = int(request.get("samples", 1))
        # AI Overview may need the page-token follow-up, so the worst case is two searches per sample.
        per = 2 if self._surface() == "google_ai_overview" else 1
        return UsageEstimate(requests=n * per, unit_type="requests",
                             note=f"Up to {per} SerpApi search(es) per sample")

    # ------------------------------------------------------------ sampling (GEO)
    def collect(self, request: dict[str, Any]) -> CollectResult:
        prompt = request["prompt"]
        language, country = request.get("language", "en"), request.get("country", "US")
        base = {"q": prompt, "gl": str(country).lower(), "hl": str(language).lower(),
                "location": self.config.get("location") or None}
        client = self._client()
        surface = self._surface()
        t0 = time.monotonic()
        if surface == "google_ai_overview":
            raw, searches = self._ai_overview(client, base)
        else:
            raw = client.search({"engine": surface, **base})
            searches = 1
        return CollectResult(raw=raw, meta={"latency_ms": int((time.monotonic() - t0) * 1000), "surface": surface,
                                            "searches": searches,
                                            "request": {"engine": surface, **{k: v for k, v in base.items() if v}}})

    def _ai_overview(self, client: SerpApiClient, base: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """AI Overview arrives one of two ways, and the second one is on a clock.

        Usually the `ai_overview` block comes back inline on the Google SERP. Sometimes Google returns only
        `ai_overview.page_token`, which SerpApi exchanges for the overview through a dedicated engine — and that
        token expires about a minute after the search, so the follow-up happens here and now rather than being
        queued. The second call is a second billed search; a failure on it is not fatal, since the SERP we already
        paid for still tells us the overview existed.
        """
        raw = client.search({"engine": "google", **base})
        overview = raw.get("ai_overview") or {}
        token = overview.get("page_token")
        if overview.get("text_blocks") or not token:
            return raw, 1
        try:
            second = client.search({"engine": "google_ai_overview", "page_token": token,
                                    "gl": base.get("gl"), "hl": base.get("hl")})
        except ProviderError as exc:
            raw["ai_overview"] = {**overview, "serpapi_error": str(exc)[:300]}
            return raw, 2
        raw["ai_overview"] = {**overview, **(second.get("ai_overview") or second)}
        return raw, 2

    def normalize(self, result: CollectResult) -> AIAnswer:
        raw = result.raw
        surface = result.meta["surface"]
        block = raw.get("ai_overview") if surface == "google_ai_overview" else raw
        block = block or {}
        parts = flatten_text_blocks(block.get("text_blocks"))
        if header := block.get("header"):            # Bing Copilot leads with a plain-text summary
            parts.insert(0, str(header))
        citations = [Citation(r["link"], domain_of(r["link"]), r["title"] or None)
                     for r in reference_links(block.get("references"))]
        if not parts and not citations:
            # A SERP with no overview is a real, reportable observation: this surface did not answer this prompt.
            note = block.get("serpapi_error") or block.get("error")
            if note:
                raise ProviderError(f"{SURFACES[surface]} unavailable for this prompt: {str(note)[:200]}")
        return AIAnswer(text="\n\n".join(parts), model=surface, model_version=None, grounded=True,
                        grounding_type="provider_search", citations=dedupe_citations(citations),
                        usage={"searches": result.meta["searches"]}, latency_ms=result.meta["latency_ms"],
                        request_config=result.meta["request"], raw=raw)
