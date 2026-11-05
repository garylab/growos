"""YouTube search results as brand mentions, via SerpApi.

YouTube is the second-largest search engine and nothing else in GrowOS looks at it, so "who is making videos about
us, our competitors and our category" was previously unanswerable. Each tracked query is one search; results become
BrandMention rows through the same mention extraction as RSS and Hacker News, so a video only lands if the brand or
a competitor is actually named in its title or description.

A caveat worth knowing when reading the feed: YouTube search reports an *age* ("3 weeks ago"), not a date, so
`published_at` is reconstructed and coarse. Exact timestamps would need the YouTube Video engine, a credit per
video, which is not worth it for a mentions list.
"""
from __future__ import annotations

from typing import Any, ClassVar

from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)
from app.adapters.brand.common import extracted_int, parse_relative_date
from app.adapters.serpapi_client import SerpApiClient, account_summary, quota_details

# Sort by upload date instead of relevance. SerpApi documents this opaque token on the `sp` parameter; it is the
# same string the YouTube UI puts in its own URL for "Sort by: Upload date".
SORT_BY_DATE = "CAI%3D"


class SerpApiYouTubeAdapter(ProviderAdapter):
    key: ClassVar[str] = "serpapi_youtube"
    category: ClassVar[str] = "brand"
    vendor: ClassVar[str] = "SerpApi"
    vendor_url: ClassVar[str] = "https://serpapi.com"
    display_name: ClassVar[str] = "YouTube search (SerpApi)"
    description: ClassVar[str] = ("Videos mentioning the brand, competitors or topics, with channel and view counts. "
                                  "One SerpApi search per tracked query.")
    docs_url: ClassVar[str] = "https://serpapi.com/youtube-search-api"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_key", "API key", secret=True, required=True,
                        help="serpapi.com → Dashboard → Your Private API Key. Leave blank to use SERPAPI_API_KEY "
                             "from the server's environment."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("gl", "Country code", "string", "us"),
        ConfigField("hl", "Language code", "string", "en"),
        ConfigField("newest_first", "Sort by upload date", "boolean", True,
                    help="Newest videos rather than YouTube's relevance ranking — better for monitoring, worse for "
                         "finding the one big video about you."),
        ConfigField("max_per_query", "Videos kept per query", "number", 20,
                    help="One search returns about twenty; this only trims what is stored."),
        ConfigField("timeout_seconds", "Request timeout", "number", 60),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="brand", measurement_type="observed",
                            features=["mentions", "engagement", "video"],
                            notes="published_at is reconstructed from a relative age such as '3 weeks ago'.")

    def _client(self) -> SerpApiClient:
        return SerpApiClient(self.credentials.get("api_key"), timeout=float(self.config.get("timeout_seconds") or 60))

    def health_check(self) -> HealthResult:
        try:
            acct = self._client().account()
        except ProviderError as exc:
            return HealthResult(False, str(exc))
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"SerpApi check failed: {exc}")
        left = acct.get("total_searches_left")
        msg = f"{account_summary(acct)} · YouTube {self.config.get('gl')}"
        if left is not None and int(left) <= 0:
            return HealthResult(False, f"{msg} — no searches left on this plan")
        return HealthResult(True, msg, quota_details(acct))

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return UsageEstimate(requests=len(request.get("queries") or []), unit_type="requests",
                             note="One SerpApi search per query")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        queries: list[str] = [q for q in (request.get("queries") or []) if q]
        if not queries:
            raise ProviderError("No queries to search YouTube for")
        client = self._client()
        videos, failures = [], {}
        for q in queries:
            params = {"engine": "youtube", "search_query": q, "gl": str(self.config.get("gl") or "us").lower(),
                      "hl": str(self.config.get("hl") or "en").lower()}
            if self.config.get("newest_first"):
                params["sp"] = SORT_BY_DATE
            try:
                payload = client.search(params)
            except ProviderError as exc:
                # One dead query must not lose the others; the task reports what came back.
                failures[q] = str(exc)[:200]
                continue
            for item in (payload.get("video_results") or [])[:int(self.config.get("max_per_query") or 20)]:
                if isinstance(item, dict):
                    videos.append({**item, "_query": q})
        if not videos and failures:
            raise ProviderError("; ".join(f"{q}: {e}" for q, e in failures.items())[:500])
        return CollectResult(raw={"video_results": videos, "failures": failures},
                             meta={"queries": queries, "searches": len(queries) - len(failures),
                                   "count": len(videos), "failures": failures or None})

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for v in result.raw.get("video_results") or []:
            vid = v.get("video_id") or v.get("link")
            if not vid:
                continue
            channel = v.get("channel") or {}
            out.append({
                "source_id": f"youtube:{vid}",
                "source_url": v.get("link"),
                "source_name": str(channel.get("name") or "YouTube")[:200],
                "title": v.get("title"),
                "content": v.get("description") or v.get("snippet") or "",
                "author": str(channel.get("name") or "")[:200] or None,
                "published_at": parse_relative_date(v.get("published_date")),
                "engagement": {k: val for k, val in {
                    "views": extracted_int(v.get("extracted_views") or v.get("views")),
                    "length": v.get("length"),
                    "channel_url": channel.get("link"),
                    "kind": "video",
                    "published_age": v.get("published_date"),
                }.items() if val is not None},
                "language": str(self.config.get("hl") or "en").lower(),
            })
        return out
