"""LinkedIn public post search through HarvestAPI's Apify Actor."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)

ACTOR_ID = "buIWk2uOUzTmcLsuB"
API = "https://api.apify.com/v2"


def _published(value: Any) -> datetime | None:
    if isinstance(value, dict):
        value = value.get("date") or value.get("timestamp")
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, UTC)
        except (OSError, ValueError):
            return None
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class ApifyLinkedInPostsAdapter(ProviderAdapter):
    key: ClassVar[str] = "apify_linkedin_posts"
    category: ClassVar[str] = "brand"
    vendor: ClassVar[str] = "Apify"
    vendor_url: ClassVar[str] = "https://apify.com"
    display_name: ClassVar[str] = "LinkedIn post search"
    description: ClassVar[str] = ("Search public LinkedIn posts for the project brand and competitors using "
                                  "HarvestAPI's cookie-free Apify Actor. Paid per returned post; comments and "
                                  "reactions are disabled by default.")
    docs_url: ClassVar[str] = "https://apify.com/harvestapi/linkedin-post-search"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("apify_token", "Apify API token", secret=True, required=True,
                        help="Apify Console → Settings → Integrations → API tokens. Leave blank to use APIFY_API_TOKEN."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("posted_limit", "Post age", "select", "month",
                    ["24h", "week", "month", "3months", "6months", "year"],
                    help="Monitoring normally needs only the last week or month."),
        ConfigField("sort_by", "Sort posts by", "select", "date", ["date", "relevance"]),
        ConfigField("max_posts", "Maximum posts per query", "number", 25,
                    help="Applied to every brand/alias/competitor query. Start small because results are billed."),
        ConfigField("scrape_comments", "Include comments", "boolean", False,
                    help="Comments are separately billed dataset items. Usually unnecessary for mention monitoring."),
        ConfigField("max_comments", "Comments per post", "number", 10,
                    help="Used only when comments are enabled."),
        ConfigField("scrape_reactions", "Include reaction identities", "boolean", False,
                    help="Reaction identities are separately billed. Aggregate reaction counts are already on posts."),
        ConfigField("max_reactions", "Reactions per post", "number", 10,
                    help="Used only when reactions are enabled."),
        ConfigField("max_charge_usd", "Maximum charge per collection (USD)", "number", 1.0,
                    help="Apify stops the run rather than exceeding this safety cap."),
        ConfigField("timeout_seconds", "Run timeout (seconds)", "number", 300),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="brand", measurement_type="observed",
                            features=["mentions", "engagement", "linkedin"],
                            notes="Public LinkedIn posts via a paid third-party Apify Actor; no cookies required.")

    def _token(self) -> str:
        token = str(self.credentials.get("apify_token") or "").strip()
        if not token:
            raise ProviderError("An Apify API token is required")
        return token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}

    def health_check(self) -> HealthResult:
        try:
            response = httpx.get(f"{API}/users/me", headers=self._headers(), timeout=30)
            if not 200 <= response.status_code < 300:
                return HealthResult(False, f"Apify rejected that token ({response.status_code}): {response.text[:160]}")
            return HealthResult(True, "Apify token accepted. Mention collection will run the paid LinkedIn Actor.")
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Apify check failed: {exc}")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        queries = len(request.get("queries") or [])
        return UsageEstimate(requests=1, unit_type="Actor runs",
                             note=f"{queries} queries in one paid run; capped at "
                                  f"${float(self.config.get('max_charge_usd') or 1):.2f}")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        queries = list(dict.fromkeys(str(q).strip()[:500] for q in request.get("queries") or [] if str(q).strip()))
        if not queries:
            raise ProviderError("No brand or competitor queries to search on LinkedIn")
        max_posts = max(1, min(int(self.config.get("max_posts") or 25), 500))
        body = {"searchQueries": queries, "postedLimit": str(self.config.get("posted_limit") or "month"),
                "sortBy": str(self.config.get("sort_by") or "date"), "maxPosts": max_posts,
                "scrapeComments": bool(self.config.get("scrape_comments")),
                "maxComments": max(1, min(int(self.config.get("max_comments") or 10), 100)),
                "scrapeReactions": bool(self.config.get("scrape_reactions")),
                "maxReactions": max(1, min(int(self.config.get("max_reactions") or 10), 100))}
        params = {"maxTotalChargeUsd": float(self.config.get("max_charge_usd") or 1.0)}
        timeout = max(60, min(int(self.config.get("timeout_seconds") or 300), 300))
        response = httpx.post(f"{API}/actors/{ACTOR_ID}/run-sync-get-dataset-items", params=params, json=body,
                              headers=self._headers(), timeout=timeout + 15)
        if not 200 <= response.status_code < 300:
            raise ProviderError(f"Apify LinkedIn Actor failed ({response.status_code}): {response.text[:300]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(f"Apify returned invalid JSON: {response.text[:200]}") from exc
        if not isinstance(payload, list):
            raise ProviderError("Apify LinkedIn Actor returned an unexpected response shape")
        return CollectResult(raw=payload, meta={"queries": queries, "searches": len(queries),
                                                "count": len(payload), "actor_id": ACTOR_ID})

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        out, seen = [], set()
        for post in result.raw:
            if not isinstance(post, dict) or post.get("type", "post") != "post":
                continue
            post_id = post.get("id") or post.get("linkedinUrl")
            if not post_id or str(post_id) in seen:
                continue
            seen.add(str(post_id))
            author = post.get("author") or {}
            engagement = post.get("engagement") or {}
            reactions = engagement.get("reactions")
            reaction_total = (sum(int(r.get("count") or 0) for r in reactions if isinstance(r, dict))
                              if isinstance(reactions, list) else reactions)
            out.append({
                "source_id": f"linkedin:{post_id}", "source_url": post.get("linkedinUrl"),
                "source_name": "LinkedIn", "title": None, "content": post.get("content") or "",
                "author": author.get("name") or author.get("publicIdentifier"),
                "published_at": _published(post.get("postedAt")),
                "engagement": {k: v for k, v in {
                    "likes": engagement.get("likes"), "comments": engagement.get("comments"),
                    "shares": engagement.get("shares"), "reactions": reaction_total,
                    "author_url": author.get("linkedinUrl"), "author_type": author.get("type"),
                }.items() if v is not None},
                "language": None,
            })
        return out
