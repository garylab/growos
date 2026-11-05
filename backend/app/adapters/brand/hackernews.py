"""Hacker News via the official Algolia search API (https://hn.algolia.com/api). No key required."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from app.adapters.base import Capabilities, CollectResult, ConfigField, HealthResult, ProviderAdapter, ProviderError

API = "https://hn.algolia.com/api/v1/search"


class HackerNewsAdapter(ProviderAdapter):
    key: ClassVar[str] = "hackernews"
    category: ClassVar[str] = "brand"
    vendor: ClassVar[str] = "Hacker News"
    vendor_url: ClassVar[str] = "https://hn.algolia.com/api"
    display_name: ClassVar[str] = "Hacker News"
    description: ClassVar[str] = "Stories and comments mentioning the brand, competitors or topics (official Algolia API)."
    docs_url: ClassVar[str] = "https://hn.algolia.com/api"
    requires_connection: ClassVar[bool] = False
    config_fields: ClassVar[list[ConfigField]] = [ConfigField("days", "Look back (days)", "number", 30),
                                                  ConfigField("hits_per_query", "Max hits per query", "number", 50)]

    def health_check(self) -> HealthResult:
        try:
            r = httpx.get(API, params={"query": "test", "hitsPerPage": 1}, timeout=15)
            return HealthResult(r.status_code == 200, f"HN Algolia API responded {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"HN check failed: {exc}")

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="brand", measurement_type="observed", features=["mentions", "discussions", "engagement"])

    def collect(self, request: dict[str, Any]) -> CollectResult:
        queries: list[str] = request["queries"]
        days = int(request.get("days") or self.config["days"])
        since = int(datetime.now(UTC).timestamp()) - days * 86400
        hits = []
        for q in queries:
            r = httpx.get(API, params={"query": q, "tags": "(story,comment)", "numericFilters": f"created_at_i>{since}",
                                       "hitsPerPage": int(self.config["hits_per_query"])}, timeout=30)
            if r.status_code != 200:
                raise ProviderError(f"HN API error {r.status_code}: {r.text[:200]}")
            for h in r.json().get("hits", []):
                h["_query"] = q
                hits.append(h)
        return CollectResult(raw={"hits": hits}, meta={"queries": queries, "since": since, "count": len(hits)})

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for h in result.raw["hits"]:
            is_comment = "comment" in (h.get("_tags") or [])
            oid = h.get("objectID")
            text = h.get("comment_text") or h.get("story_text") or ""
            from app.adapters.brand.rss import _strip_html
            out.append({"source_id": f"hn:{oid}", "source_url": f"https://news.ycombinator.com/item?id={oid}",
                        "source_name": "Hacker News", "title": h.get("title") or h.get("story_title"),
                        "content": _strip_html(text), "author": h.get("author"),
                        "published_at": datetime.fromtimestamp(h.get("created_at_i", 0), tz=UTC),
                        "engagement": {"points": h.get("points"), "comments": h.get("num_comments"), "kind": "comment" if is_comment else "story"},
                        "query": h.get("_query"), "external_url": h.get("url")})
        return out
