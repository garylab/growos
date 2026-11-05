"""TikTok Discover pages as a brand source, via SerpApi.

Read the shape of this one before relying on it, because it is not a search:

SerpApi has no TikTok search engine. The Discover engine takes the keyword of a TikTok *Discover page* — the last
part of `tiktok.com/discover/<keyword>` — and returns the videos that page lists. So it cannot be asked "who
mentioned Acme Corp"; it can only be asked "what is on the skincare Discover page". The brand and competitor names
the monitoring task passes to every other source are therefore ignored here, and the pages to read are configured
per connection instead.

What that means in practice: a video only becomes a BrandMention if the brand or a competitor is named in its
description or hashtags, exactly as for every other source. Harvesting a category page and keeping only the videos
that name someone you track is a thin filter, so expect few rows — the value is that those rows are ones nothing
else in GrowOS can see, on a platform where a single video moves demand.
"""
from __future__ import annotations

from typing import Any, ClassVar

from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)
from app.adapters.brand.common import parse_relative_date
from app.adapters.serpapi_client import SerpApiClient, account_summary, quota_details


def discover_keywords(raw: str | None) -> list[str]:
    """Discover page keywords from the configured text, one per line or comma-separated.

    A pasted URL is accepted and reduced to its last path segment, because that is what a user who went looking
    for the page actually has in their clipboard.
    """
    out: list[str] = []
    for chunk in str(raw or "").replace(",", "\n").splitlines():
        token = chunk.strip()
        if not token:
            continue
        if "tiktok.com" in token or token.startswith("http"):
            token = token.rstrip("/").split("/")[-1].split("?")[0]
        token = token.lstrip("#").strip()
        if token and token not in out:
            out.append(token[:100])
    return out


class SerpApiTikTokDiscoverAdapter(ProviderAdapter):
    key: ClassVar[str] = "serpapi_tiktok"
    category: ClassVar[str] = "brand"
    vendor: ClassVar[str] = "SerpApi"
    vendor_url: ClassVar[str] = "https://serpapi.com"
    display_name: ClassVar[str] = "TikTok Discover (SerpApi)"
    description: ClassVar[str] = ("Videos from the TikTok Discover pages you choose, kept when they name your brand "
                                  "or a competitor. Not a TikTok search — SerpApi has no search engine for TikTok, "
                                  "so you pick category pages rather than query names. One search per page.")
    docs_url: ClassVar[str] = "https://serpapi.com/tiktok-discover-api"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_key", "API key", secret=True, required=True,
                        help="serpapi.com → Dashboard → Your Private API Key. Leave blank to use SERPAPI_API_KEY "
                             "from the server's environment."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("discover_pages", "Discover pages", "textarea", "",
                    help="One TikTok Discover keyword per line — the last part of tiktok.com/discover/<keyword>. "
                         "Paste the whole URL and the keyword is taken from it. Your brand name only works here if "
                         "TikTok has a Discover page for it; category terms are the reliable use."),
        ConfigField("gl", "Country code", "string", "us"),
        ConfigField("num", "Videos per page", "number", 30, help="1-100. TikTok's own default is 16."),
        ConfigField("timeout_seconds", "Request timeout", "number", 60),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="brand", measurement_type="observed",
                            features=["mentions", "engagement", "video"],
                            notes="Reads chosen Discover pages, not arbitrary queries — SerpApi has no TikTok "
                                  "search engine. Rows appear only where a tracked name is in the description.")

    def _pages(self) -> list[str]:
        return discover_keywords(self.config.get("discover_pages"))

    def _client(self) -> SerpApiClient:
        return SerpApiClient(self.credentials.get("api_key"), timeout=float(self.config.get("timeout_seconds") or 60))

    def health_check(self) -> HealthResult:
        pages = self._pages()
        if not pages:
            return HealthResult(False, "No Discover pages configured — add at least one keyword, e.g. the category "
                                       "your product sits in. This source reads pages, not search queries.")
        try:
            acct = self._client().account()
        except ProviderError as exc:
            return HealthResult(False, str(exc))
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"SerpApi check failed: {exc}")
        left = acct.get("total_searches_left")
        msg = f"{account_summary(acct)} · {len(pages)} Discover page(s): {', '.join(pages[:5])}"
        if left is not None and int(left) <= 0:
            return HealthResult(False, f"{msg} — no searches left on this plan")
        return HealthResult(True, msg, quota_details(acct))

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return UsageEstimate(requests=len(self._pages()), unit_type="requests",
                             note="One SerpApi search per Discover page")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        """`request["queries"]` is ignored here — see the module docstring."""
        pages = self._pages()
        if not pages:
            raise ProviderError("No TikTok Discover pages are configured for this connection")
        client = self._client()
        videos, failures = [], {}
        for page in pages:
            try:
                payload = client.search({"engine": "tiktok_discover", "q": page,
                                         "gl": str(self.config.get("gl") or "us").lower(),
                                         "num": min(max(int(self.config.get("num") or 30), 1), 100)})
            except ProviderError as exc:
                failures[page] = str(exc)[:200]
                continue
            for item in payload.get("video_results") or []:
                if isinstance(item, dict):
                    videos.append({**item, "_page": page})
        if not videos and failures:
            raise ProviderError("; ".join(f"{p}: {e}" for p, e in failures.items())[:500])
        return CollectResult(raw={"video_results": videos, "failures": failures},
                             meta={"discover_pages": pages, "searches": len(pages) - len(failures),
                                   "count": len(videos), "failures": failures or None})

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for v in result.raw.get("video_results") or []:
            vid = v.get("id") or v.get("link")
            if not vid:
                continue
            author = v.get("author") or {}
            tags = [str(h.get("name")) for h in (v.get("hashtags") or []) if isinstance(h, dict) and h.get("name")]
            # Hashtags carry brand names that the description does not spell out, and mention extraction only
            # reads text, so they are appended to the content it sees.
            description = str(v.get("description") or "")
            content = " ".join([description] + [f"#{t}" for t in tags if t.lower() not in description.lower()])
            out.append({
                "source_id": f"tiktok:{vid}",
                "source_url": v.get("link"),
                "source_name": "TikTok",
                "title": description.splitlines()[0][:300] if description else None,
                "content": content.strip(),
                "author": str(author.get("name") or author.get("username") or "")[:200] or None,
                "published_at": parse_relative_date(v.get("published_date")),
                "engagement": {k: val for k, val in {
                    "plays": v.get("plays"), "likes": v.get("likes"), "comments": v.get("comments"),
                    "shares": v.get("shares"), "bookmarks": v.get("bookmarks"),
                    "duration": v.get("duration"), "author_url": author.get("link"),
                    "discover_page": v.get("_page"), "kind": "tiktok",
                }.items() if val is not None},
                "language": None,
            })
        return out
