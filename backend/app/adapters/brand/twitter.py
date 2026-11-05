"""X (Twitter) brand mention monitoring via the official API v2 recent-search endpoint.

Unlike Bluesky (free public API), X requires a paid plan: mention search is unavailable on the Free tier and needs at
least Basic. You supply an App Bearer token; GrowOS never scrapes. The health check states the tier requirement.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

import httpx

from app.adapters.base import Capabilities, CollectResult, ConfigField, CredentialField, HealthResult, ProviderAdapter, ProviderError

SEARCH = "https://api.twitter.com/2/tweets/search/recent"


class TwitterAdapter(ProviderAdapter):
    key: ClassVar[str] = "twitter"
    category: ClassVar[str] = "brand"
    vendor: ClassVar[str] = "X / Twitter"
    display_name: ClassVar[str] = "X (Twitter)"
    description: ClassVar[str] = ("Recent public posts mentioning the brand or competitors via the official X API v2. "
                                  "Requires a paid X API plan (Basic or above) — the Free tier cannot search mentions.")
    docs_url: ClassVar[str] = "https://developer.x.com/en/docs/x-api/tweets/search/introduction"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("bearer_token", "App Bearer token", help="From your X developer app (OAuth 2.0 App-Only). Needs a paid plan."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("limit_per_query", "Max posts per query", "number", 25, help="X caps page size at 100; 10-100."),
        ConfigField("exclude_retweets", "Exclude retweets", "boolean", True),
    ]

    def _headers(self) -> dict[str, str]:
        tok = self.credentials.get("bearer_token")
        if not tok:
            raise ProviderError("X API bearer token is not configured")
        return {"Authorization": f"Bearer {tok}"}

    def _search(self, query: str) -> dict[str, Any]:
        q = query if not self.config.get("exclude_retweets") else f"{query} -is:retweet"
        params = {"query": q[:512], "max_results": max(10, min(100, int(self.config["limit_per_query"]))),
                  "tweet.fields": "created_at,public_metrics,lang,author_id",
                  "expansions": "author_id", "user.fields": "username,name"}
        r = httpx.get(SEARCH, headers=self._headers(), params=params, timeout=30)
        if r.status_code == 429:
            raise ProviderError("X API rate limit reached. Recent search is heavily capped on lower tiers; wait or raise your plan.")
        if r.status_code in (401, 403):
            raise ProviderError("X API rejected the request (401/403). Mention search needs a paid plan (Basic or above) "
                                "and an App-Only Bearer token with read access.")
        if r.status_code != 200:
            raise ProviderError(f"X API error {r.status_code}: {r.text[:200]}")
        return r.json()

    def health_check(self) -> HealthResult:
        if not self.credentials.get("bearer_token"):
            return HealthResult(False, "No bearer token set. X mention search requires a paid X API plan (Basic+).")
        try:
            self._search("the")
            return HealthResult(True, "X API reachable with your token.")
        except ProviderError as exc:
            return HealthResult(False, str(exc))
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"X check failed: {exc}")

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="brand", measurement_type="observed", features=["mentions", "engagement"],
                            notes="Recent (last ~7 days) search only on standard access; paid plan required.")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        tweets, users = [], {}
        for q in request["queries"]:
            data = self._search(q)
            for u in (data.get("includes") or {}).get("users", []):
                users[u["id"]] = u
            for t in data.get("data", []):
                t["_query"] = q
                tweets.append(t)
        return CollectResult(raw={"tweets": tweets, "users": users}, meta={"queries": request["queries"], "count": len(tweets)})

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        users = result.raw.get("users", {})
        out = []
        for t in result.raw["tweets"]:
            u = users.get(t.get("author_id"), {})
            handle = u.get("username", "")
            tid = t.get("id")
            created = t.get("created_at")
            m = t.get("public_metrics") or {}
            out.append({"source_id": f"x:{tid}", "source_url": f"https://x.com/{handle}/status/{tid}" if handle else f"https://x.com/i/status/{tid}",
                        "source_name": "X", "title": None, "content": t.get("text", ""), "author": handle or u.get("name"),
                        "published_at": datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None,
                        "engagement": {"likes": m.get("like_count"), "reposts": m.get("retweet_count"),
                                       "replies": m.get("reply_count"), "quotes": m.get("quote_count")},
                        "query": t.get("_query"), "language": t.get("lang")})
        return out
