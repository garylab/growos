"""SerpApi Extract — fetch a page the way a browser would, for the pages our own fetcher cannot read.

The gap this fills: SiteOne crawls and `safe_get` fetches, but nothing in GrowOS executes JavaScript. On a
client-rendered site the HTML we receive is an empty shell, so every on-page check — H1, headings, canonical,
JSON-LD, Open Graph, alt text — reports a problem that does not exist. Extract routes the URL through a renderer
and returns the resolved HTML, which selectolax then parses exactly as before.

It is a fallback, not a replacement: it is used only when a page is fetched successfully and still looks unrendered
(see `app.services.page_signals.looks_unrendered`), because it costs a credit per page and the direct fetch is
free, honours our SSRF rules and is an order of magnitude faster.

Deliberately not wired up: `mode=map` and `mode=crawl`. Site discovery is SiteOne's job and it is bundled and
unmetered — paying per page to duplicate it would be a poor trade.
"""
from __future__ import annotations

from typing import Any, ClassVar

from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)
from app.adapters.serpapi_client import SerpApiClient, account_summary, quota_details


class SerpApiExtractAdapter(ProviderAdapter):
    key: ClassVar[str] = "serpapi_extract"
    category: ClassVar[str] = "crawling"
    vendor: ClassVar[str] = "SerpApi"
    vendor_url: ClassVar[str] = "https://serpapi.com"
    display_name: ClassVar[str] = "SerpApi Extract (JavaScript rendering)"
    description: ClassVar[str] = ("Renders a page's JavaScript and returns the resolved HTML or Markdown. Used "
                                  "automatically as a fallback when a crawled page looks like an empty app shell, "
                                  "so on-page checks work on client-rendered sites. One credit per page.")
    docs_url: ClassVar[str] = "https://serpapi.com/extract-api"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_key", "API key", secret=True, required=True,
                        help="serpapi.com → Dashboard → Your Private API Key, or leave blank to use "
                             "SERPAPI_API_KEY from the server's environment. The same key as the other SerpApi "
                             "providers; a separate connection keeps its spend visible on its own."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("device", "Render as", "select", "desktop", ["desktop", "mobile", "tablet"]),
        ConfigField("prefetch_delay", "Wait after load (seconds)", "number", 0,
                    help="Extra settle time for pages that fetch their content after first paint."),
        ConfigField("timeout_seconds", "Request timeout", "number", 90,
                    help="Rendering is slower than a plain fetch."),
        ConfigField("max_pages_per_job", "Rendered pages per job", "number", 20,
                    help="Ceiling on the fallback so one crawl of a broken site cannot drain the plan."),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="crawling", measurement_type="observed",
                            features=["javascript_rendering", "markdown_extraction"],
                            notes="Fetched through SerpApi rather than directly, so our SSRF pinning does not apply "
                                  "to the final hop; only URLs already discovered by a crawl are sent.")

    def _client(self) -> SerpApiClient:
        return SerpApiClient(self.credentials.get("api_key"), timeout=float(self.config.get("timeout_seconds") or 90))

    def _params(self, url: str) -> dict[str, Any]:
        return {"engine": "extract", "url": url, "mode": "scrape",
                "device": str(self.config.get("device") or "desktop"),
                "prefetch_delay": int(self.config.get("prefetch_delay") or 0) or None}

    def health_check(self) -> HealthResult:
        try:
            acct = self._client().account()
        except ProviderError as exc:
            return HealthResult(False, str(exc))
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"SerpApi check failed: {exc}")
        left = acct.get("total_searches_left")
        msg = f"{account_summary(acct)} · rendering as {self.config.get('device')}"
        if left is not None and int(left) <= 0:
            return HealthResult(False, f"{msg} — no searches left on this plan")
        return HealthResult(True, msg, quota_details(acct))

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        n = len(request.get("urls") or [request.get("url")])
        return UsageEstimate(requests=n, unit_type="requests", note="One credit per successfully rendered page")

    @property
    def page_budget(self) -> int:
        return max(0, int(self.config.get("max_pages_per_job") or 20))

    def render_html(self, url: str) -> str:
        """Resolved HTML for one URL. Raises ProviderError rather than returning a shell, so callers can fall back."""
        html = self._client().fetch_text(self._params(url), output="html")
        if not html or "<" not in html:
            raise ProviderError(f"Extract returned no HTML for {url}")
        return html

    def collect(self, request: dict[str, Any]) -> CollectResult:
        """Markdown for one URL — the form that suits an LLM reading a competitor's page."""
        url = request["url"]
        text = self._client().fetch_text(self._params(url), output="md")
        return CollectResult(raw=text, meta={"provider": self.key, "url": url, "searches": 1, "format": "markdown"})

    def normalize(self, result: CollectResult) -> dict[str, Any]:
        return {"url": result.meta["url"], "markdown": result.raw}
