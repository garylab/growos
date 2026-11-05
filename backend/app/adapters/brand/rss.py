"""RSS/Atom feed monitoring (news sites, blogs, Google Alerts feeds, subreddit RSS where permitted by the publisher)."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, ClassVar

import feedparser

from app.adapters.base import Capabilities, CollectResult, ConfigField, HealthResult, ProviderAdapter, ProviderError, UsageEstimate
from app.core.content_extract import main_text
from app.core.safe_http import safe_get, validate_url

# A summary this long is the article, not a teaser, so there is nothing to gain by fetching the page.
FULL_TEXT_THRESHOLD = 600


class RSSAdapter(ProviderAdapter):
    key: ClassVar[str] = "rss"
    category: ClassVar[str] = "brand"
    vendor: ClassVar[str] = "RSS / Atom feeds"
    display_name: ClassVar[str] = "RSS / Atom feeds"
    description: ClassVar[str] = "Monitor any RSS/Atom feed (news, blogs, Google Alerts) for brand and competitor mentions."
    requires_connection: ClassVar[bool] = False
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("feeds", "Feed URLs (one per line)", "string", ""),
        ConfigField("fetch_full_text", "Read the full article", "boolean", True,
                    help="Most feeds publish a one-sentence teaser. With this on, items whose summary looks "
                         "truncated are fetched and their main text extracted, so a brand named further down "
                         "the article is still found. Off means mentions are detected from the teaser only."),
        ConfigField("max_article_fetches", "Articles to read per run", "number", 25,
                    help="Ceiling on those extra page fetches, so a busy feed cannot turn one run into hundreds "
                         "of requests against someone else's site."),
    ]

    def feed_urls(self) -> list[str]:
        return [u.strip() for u in str(self.config.get("feeds") or "").splitlines() if u.strip()]

    def health_check(self) -> HealthResult:
        urls = self.feed_urls()
        if not urls:
            return HealthResult(False, "No feed URLs configured")
        errors = []
        for u in urls:
            try:
                validate_url(u)
                r = safe_get(u, timeout=15)
                if r.status_code != 200:
                    errors.append(f"{u}: HTTP {r.status_code}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{u}: {exc}")
        return HealthResult(not errors, "All feeds reachable" if not errors else "; ".join(errors)[:500])

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="brand", measurement_type="observed", features=["mentions", "discussions"],
                            notes="Mentions are found in whatever text the feed gives us. With 'Read the full "
                                  "article' on, truncated items are fetched and their main content extracted; "
                                  "without it, a mention below the teaser cannot be seen.")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        feeds = len(request.get("feeds") or self.feed_urls())
        extra = int(self.config.get("max_article_fetches") or 0) if self.config.get("fetch_full_text") else 0
        return UsageEstimate(requests=feeds + extra, note=f"{feeds} feed fetch(es) plus up to {extra} article page(s)")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        urls = request.get("feeds") or self.feed_urls()
        items = []
        errors = []
        for u in urls:
            try:
                r = safe_get(u, timeout=20)
                if r.status_code != 200:
                    errors.append(f"{u}: HTTP {r.status_code}")
                    continue
                parsed = feedparser.parse(r.content)
                for e in parsed.entries:
                    items.append({"feed": u, "feed_title": parsed.feed.get("title"), "id": e.get("id") or e.get("link"),
                                  "link": e.get("link"), "title": e.get("title"), "summary": e.get("summary") or e.get("description"),
                                  "author": e.get("author"), "published": _ts(e)})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{u}: {exc}")
        if errors and not items:
            raise ProviderError("; ".join(errors)[:500])
        fetched = self._add_full_text(items, errors)
        return CollectResult(raw={"items": items, "errors": errors},
                             meta={"feeds": urls, "count": len(items), "articles_fetched": fetched})

    def _add_full_text(self, items: list[dict[str, Any]], errors: list[str]) -> int:
        """Fill in `full_text` for items whose summary is a teaser. Mutates `items`; returns how many were read.

        A failure here is not a collection failure: the item still carries its summary, so the run continues with
        less text rather than losing the mention entirely. Each skipped article is recorded in `errors` so the
        job log says which ones were only read as teasers.
        """
        if not self.config.get("fetch_full_text"):
            return 0
        budget = int(self.config.get("max_article_fetches") or 0)
        fetched = 0
        seen: set[str] = set()
        for it in items:
            if fetched >= budget:
                break
            link = it.get("link")
            if not link or link in seen or len(_strip_html(it.get("summary") or "")) >= FULL_TEXT_THRESHOLD:
                continue
            seen.add(link)
            # The budget counts attempts, not successes. Counting only successes would let a feed full of dead
            # links spend an unbounded number of requests before the ceiling was ever reached.
            fetched += 1
            try:
                r = safe_get(link, timeout=20)
                if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                    continue
                extracted = main_text(r.text, link)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{link}: {exc}")
                continue
            # Only replace the teaser when the page actually gave us more than the feed did.
            if extracted.chars > len(_strip_html(it.get("summary") or "")):
                it["full_text"] = extracted.text[:20000]
                it["full_text_method"] = extracted.method
        return fetched

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for it in result.raw["items"]:
            text = it.get("full_text") or _strip_html(it.get("summary") or "")
            out.append({"source_id": it.get("id") or it.get("link") or "", "source_url": it.get("link"),
                        "source_name": it.get("feed_title") or it.get("feed"), "title": it.get("title"),
                        "content": text, "author": it.get("author"), "published_at": it.get("published"),
                        "engagement": {}})
        return out


def _ts(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        v = entry.get(key)
        if v:
            return datetime.fromtimestamp(time.mktime(v), tz=UTC)
    return None


def _strip_html(s: str) -> str:
    from selectolax.parser import HTMLParser
    try:
        return HTMLParser(s).text(separator=" ", strip=True)[:4000]
    except Exception:  # noqa: BLE001
        return s[:4000]
