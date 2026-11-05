"""SerpApi — live Google SERP positions, SERP features, and keyword discovery.

What this is for: before it existed, `sync_rankings` worked only with DataForSEO, because Ahrefs and Semrush sell
keyword databases rather than per-keyword live SERPs. This adapter does the live half cheaply and does not pretend
to do the other half: it has no `collect_keyword_metrics` and no `collect_ranked_keywords`, because SerpApi reads
the SERP and does not model search volume, difficulty or a domain's whole ranking footprint. Provider selection is
therefore by feature, not by category — see `app.tasks.search_data.connected_provider`.

Engines used:
  engine=google_light   organic results only, the cheap default for a position check
  engine=google         the same plus SERP feature blocks (AI overview, People Also Ask, local pack, …)
  engine=bing           Bing organic results, in its own provider (see SerpApiBingAdapter)
  engine=google_autocomplete   what Google suggests mid-typing, with a relevance score
  engine=google_trends         interest over time and related queries

One provider per search engine, not one provider with an engine dropdown. `provider_key` is part of the uniqueness
of a RankObservation precisely so two sources' numbers are never mixed, and position 3 on Bing is a different fact
from position 3 on Google — more different, not less, than two vendors' estimates of the same SERP.

Discovery is the reason this pays for itself: a credit spent on autocomplete, People Also Ask and Trends-related
queries produces candidate keywords for nothing like the price of a keyword database, and the expensive provider
is then asked to price only the candidates that survive.
"""
from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import urlsplit

from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)
from app.adapters.search_data.common import clean_keyword, rank_row
from app.adapters.serpapi_client import SerpApiClient, account_summary, quota_details, reference_links

# Response keys that are not SERP feature blocks. Everything else present and non-empty is treated as a feature, so
# a block Google invents next quarter is reported rather than silently missed by a stale allowlist.
NOT_A_FEATURE = {
    "search_metadata", "search_parameters", "search_information", "organic_results", "pagination",
    "serpapi_pagination", "error", "filters", "ads", "serpapi_link", "serpapi_extra_pages",
}


def host_of(value: Any) -> str:
    return (urlsplit(str(value or "")).hostname or "").lower().removeprefix("www.")


def matches_host(candidate: str, host: str) -> bool:
    """Our site, including its subdomains — so blog.example.com counts as example.com ranking."""
    return bool(host) and (candidate == host or candidate.endswith("." + host))


class SerpApiSerpBase(ProviderAdapter):
    """Transport, quota reporting and SERP parsing shared by every SerpApi search engine."""

    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_key", "API key", secret=True, required=True,
                        help="serpapi.com → Dashboard → Your Private API Key. Leave blank to use SERPAPI_API_KEY "
                             "from the server's environment."),
    ]

    def _client(self) -> SerpApiClient:
        return SerpApiClient(self.credentials.get("api_key"), timeout=float(self.config.get("timeout_seconds") or 60))

    def _engine_summary(self) -> str:
        """What this connection is set up to do, for the health-check line."""
        return ""

    def health_check(self) -> HealthResult:
        try:
            acct = self._client().account()
        except ProviderError as exc:
            return HealthResult(False, str(exc))
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"SerpApi check failed: {exc}")
        left = acct.get("total_searches_left")
        msg = account_summary(acct)
        if summary := self._engine_summary():
            msg = f"{msg} · {summary}"
        if left is not None and int(left) <= 0:
            return HealthResult(False, f"{msg} — no searches left on this plan")
        return HealthResult(True, msg, quota_details(acct))

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return UsageEstimate(requests=1, unit_type="requests", note="One SerpApi search")

    def normalize_rank(self, result: CollectResult) -> dict[str, Any] | None:
        """Our position for this keyword, plus the features sitting around it.

        Engine-neutral: every SerpApi search engine returns `organic_results` with `position` and `link`, and every
        other non-metadata top-level key is a feature block. Two pseudo-features are added alongside the real block
        names: `ai_overview_cites_you` when our host is one of the overview's sources, and `ai_overview_present` so
        "there was an overview and it ignored us" can be told apart from "there was no overview". Both ride in
        `serp_features`, which already exists on RankObservation and is already rendered in the rankings table.
        """
        raw = result.raw
        host = str(result.meta.get("host") or "").strip().lower().removeprefix("www.")
        features = sorted(k for k, v in raw.items() if k not in NOT_A_FEATURE and v not in (None, "", [], {}))
        position, url = None, None
        for item in raw.get("organic_results") or []:
            if not isinstance(item, dict):
                continue
            if matches_host(host_of(item.get("link")), host):
                position, url = item.get("position"), item.get("link")
                break
        overview = raw.get("ai_overview") or {}
        if overview.get("text_blocks") or overview.get("references"):
            features.append("ai_overview_present")
            cited = {host_of(r["link"]) for r in reference_links(overview.get("references"))}
            if any(matches_host(c, host) for c in cited):
                features.append("ai_overview_cites_you")
        return rank_row(result.meta.get("keyword"), position=position, url=url, serp_features=sorted(set(features)))


class SerpApiSearchDataAdapter(SerpApiSerpBase):
    key: ClassVar[str] = "serpapi_serp"
    category: ClassVar[str] = "search_data"
    vendor: ClassVar[str] = "SerpApi"
    vendor_url: ClassVar[str] = "https://serpapi.com"
    display_name: ClassVar[str] = "SerpApi (live SERP & keyword discovery)"
    description: ClassVar[str] = ("Live Google positions for tracked keywords, the SERP features around them "
                                 "(including whether Google's AI Overview cites you), and keyword discovery from "
                                 "autocomplete, People Also Ask and Trends. Does not provide search volume or "
                                 "difficulty — pair it with a keyword database for those.")
    docs_url: ClassVar[str] = "https://serpapi.com/search-api"
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("engine", "SERP engine", "select", "google_light", ["google_light", "google"],
                    help="'google_light' is the fast, organic-only engine — right for pure position checks. "
                         "'google' costs the same but also returns the SERP feature blocks."),
        ConfigField("location", "Location", "string", "",
                    help="Optional city/country the search appears to come from, e.g. 'United States'."),
        ConfigField("gl", "Country code", "string", "us", help="Two-letter market code, e.g. us, gb, de."),
        ConfigField("hl", "Language code", "string", "en"),
        ConfigField("serp_depth", "Results per check", "number", 100,
                    help="How far down to look for your site. Google returns at most 100 per search."),
        ConfigField("ai_overview", "Record AI Overview citations", "boolean", True,
                    help="On the 'google' engine, also read who the AI Overview cites and flag the keywords where "
                         "it cites you. Costs a second search when Google withholds the overview behind a token."),
        ConfigField("discovery_trends", "Use Google Trends for discovery", "boolean", True,
                    help="Adds Trends 'related queries' to keyword discovery — one extra search per seed."),
        ConfigField("timeout_seconds", "Request timeout", "number", 60),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(
            category="search_data", measurement_type="observed",
            features=["rank_tracking", "serp_features", "ai_overview_citations", "keyword_discovery",
                      "keyword_trends"],
            notes="Positions are read off a live SERP, so they are observed rather than modelled — but a single "
                  "check is one location and one moment. No search volume, difficulty or competitor footprint.")

    def _locale(self) -> dict[str, Any]:
        return {"gl": str(self.config.get("gl") or "us").lower(), "hl": str(self.config.get("hl") or "en").lower(),
                "location": self.config.get("location") or None}

    def _engine_summary(self) -> str:
        return f"engine {self.config.get('engine')}"

    # ---------------------------------------------------------------- live rank for one keyword
    def collect_rank(self, request: dict[str, Any]) -> CollectResult:
        keyword = request["keyword"]
        host = str(request.get("host") or "").strip().lower().removeprefix("www.")
        engine = "google" if str(self.config.get("engine")) == "google" else "google_light"
        params = {"engine": engine, "q": keyword, "num": min(int(self.config.get("serp_depth") or 100), 100),
                  **self._locale()}
        client = self._client()
        raw = client.search(params)
        searches = 1
        # Only the full `google` engine returns an overview to begin with, so the follow-up is scoped to it.
        if engine == "google" and self.config.get("ai_overview"):
            overview = raw.get("ai_overview") or {}
            if overview.get("page_token") and not overview.get("text_blocks"):
                try:
                    second = client.search({"engine": "google_ai_overview", "page_token": overview["page_token"],
                                            "gl": params["gl"], "hl": params["hl"]})
                    raw["ai_overview"] = {**overview, **(second.get("ai_overview") or second)}
                    searches = 2
                except ProviderError:
                    searches = 2          # it was attempted and billed; the SERP itself is still usable
        return CollectResult(raw=raw, meta={"provider": self.key, "keyword": keyword, "engine": engine,
                                            "host": host, "searches": searches, **self._locale()})

    # ---------------------------------------------------------------- keyword discovery
    def collect_suggestions(self, request: dict[str, Any]) -> CollectResult:
        """Autocomplete for one seed: what Google offers while the phrase is still being typed."""
        seed = request["seed"]
        raw = self._client().search({"engine": "google_autocomplete", "q": seed, **self._locale()})
        return CollectResult(raw=raw, meta={"provider": self.key, "seed": seed, "source": "autocomplete",
                                            "searches": 1})

    def collect_serp_ideas(self, request: dict[str, Any]) -> CollectResult:
        """One SERP read for its related searches and People Also Ask questions rather than for a position."""
        seed = request["seed"]
        raw = self._client().search({"engine": "google_light", "q": seed, **self._locale()})
        return CollectResult(raw=raw, meta={"provider": self.key, "seed": seed, "source": "serp", "searches": 1})

    def collect_trend_queries(self, request: dict[str, Any]) -> CollectResult:
        seed = request["seed"]
        raw = self._client().search({"engine": "google_trends", "q": seed, "data_type": "RELATED_QUERIES",
                                     "geo": str(self.config.get("gl") or "us").upper(),
                                     "hl": str(self.config.get("hl") or "en").lower()})
        return CollectResult(raw=raw, meta={"provider": self.key, "seed": seed, "source": "trends", "searches": 1})

    def normalize_ideas(self, result: CollectResult) -> list[dict[str, Any]]:
        """Candidate keywords from any of the three discovery calls: {keyword, source, score}.

        `score` is comparable only within a source — autocomplete relevance and Trends rising-query values are
        different scales — so it orders candidates from one call and is never mixed across calls.
        """
        raw, source = result.raw, result.meta["source"]
        out: list[dict[str, Any]] = []

        def add(text: Any, score: Any = None) -> None:
            kw = clean_keyword(text)
            if kw:
                try:
                    s = float(score) if score is not None else None
                except (TypeError, ValueError):
                    s = None
                out.append({"keyword": kw, "source": source, "score": s})

        if source == "autocomplete":
            for s in raw.get("suggestions") or []:
                if isinstance(s, dict):
                    add(s.get("value"), s.get("relevance"))
        elif source == "serp":
            for s in raw.get("related_searches") or []:
                if isinstance(s, dict):
                    add(s.get("query") or s.get("name"))
            for q in raw.get("related_questions") or []:
                if isinstance(q, dict):
                    add(q.get("question"))
        elif source == "trends":
            related = raw.get("related_queries") or {}
            for bucket in ("rising", "top"):
                for item in related.get(bucket) or []:
                    if isinstance(item, dict):
                        add(item.get("query"), item.get("extracted_value") or item.get("value"))
        seen, unique = set(), []
        for row in out:
            if row["keyword"] not in seen:
                seen.add(row["keyword"])
                unique.append(row)
        return unique

    # ---------------------------------------------------------------- seasonality
    def collect_interest_over_time(self, request: dict[str, Any]) -> CollectResult:
        """Trends interest over time. Google compares at most five terms in one request, hence the slice."""
        keywords = [k for k in (request.get("keywords") or []) if k][:5]
        if not keywords:
            raise ProviderError("No keywords to chart")
        raw = self._client().search({"engine": "google_trends", "q": ",".join(keywords), "data_type": "TIMESERIES",
                                     "geo": str(self.config.get("gl") or "us").upper(),
                                     "hl": str(self.config.get("hl") or "en").lower(),
                                     "date": request.get("date") or "today 12-m"})
        return CollectResult(raw=raw, meta={"provider": self.key, "keywords": keywords, "searches": 1})

    def normalize_interest_over_time(self, result: CollectResult) -> list[dict[str, Any]]:
        """Per keyword: the 0-100 series plus the shape of it that a reader actually wants.

        Trends values are relative to the peak of the compared set, never absolute volume, so only `peak`,
        `latest` and the direction of travel are meaningful — and that is all this returns.
        """
        timeline = ((result.raw.get("interest_over_time") or {}).get("timeline_data")) or []
        series: dict[str, list[tuple[str, int]]] = {}
        for point in timeline:
            if not isinstance(point, dict):
                continue
            label = str(point.get("date") or "")
            for v in point.get("values") or []:
                if not isinstance(v, dict):
                    continue
                name = clean_keyword(v.get("query"))
                try:
                    value = int(v.get("extracted_value") if v.get("extracted_value") is not None else v.get("value"))
                except (TypeError, ValueError):
                    continue
                series.setdefault(name, []).append((label, value))
        out = []
        for name, points in series.items():
            values = [v for _l, v in points]
            if not values:
                continue
            peak_at, peak = max(points, key=lambda p: p[1])
            # Last four points against the twelve before them: enough to call a direction without mistaking one
            # quiet week for a decline.
            recent = values[-4:]
            baseline = values[-16:-4] or values[:-4] or values
            avg_recent = sum(recent) / len(recent)
            avg_base = sum(baseline) / len(baseline)
            change = ((avg_recent - avg_base) / avg_base * 100) if avg_base else None
            out.append({"keyword": name, "points": [{"date": l, "value": v} for l, v in points],
                        "peak": peak, "peak_at": peak_at, "latest": values[-1],
                        "trend_pct": round(change, 1) if change is not None else None,
                        "direction": ("up" if change > 10 else "down" if change < -10 else "flat")
                                     if change is not None else None})
        return sorted(out, key=lambda r: -r["peak"])


class SerpApiBingAdapter(SerpApiSerpBase):
    """Bing organic positions for tracked keywords.

    Worth tracking for more than Bing's own share of search: Bing is what grounds Copilot and ChatGPT's web
    search, so a Bing position is a leading indicator for the AI surfaces measured under GEO AI Visibility
    rather than a second opinion on Google.

    The one awkward thing about this engine: it has no result-count parameter. `first` moves an offset and each
    page is a separate billed search, so depth costs credits in a way the Google engines do not — `num=100` there
    is one search, the top 50 here is five. `pages` is the ceiling and the search stops as soon as the site is
    found, so the full price is only paid for keywords where we do not rank at all.
    """

    key: ClassVar[str] = "serpapi_bing"
    category: ClassVar[str] = "search_data"
    vendor: ClassVar[str] = "SerpApi"
    vendor_url: ClassVar[str] = "https://serpapi.com"
    display_name: ClassVar[str] = "SerpApi (Bing positions)"
    description: ClassVar[str] = ("Live Bing positions for tracked keywords. Bing grounds Copilot and ChatGPT's web "
                                  "search, so this doubles as an early signal for AI answer visibility. Billed one "
                                  "search per result page, unlike the Google engines.")
    docs_url: ClassVar[str] = "https://serpapi.com/bing-search-api"
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("cc", "Country code", "string", "us", help="Two-letter market code, e.g. us, gb, de."),
        ConfigField("mkt", "Market", "string", "en-US",
                    help="Language-country market Bing should answer as, e.g. en-US, en-GB, de-DE."),
        ConfigField("location", "Location", "string", "",
                    help="Optional city/country the search appears to come from."),
        ConfigField("pages", "Result pages per keyword", "number", 2,
                    help="Bing returns about ten results per page and charges a search for each one. 2 pages ≈ top "
                         "20. The search stops early once your site is found, so this is a ceiling, not a cost."),
        ConfigField("device", "Device", "select", "desktop", ["desktop", "mobile", "tablet"]),
        ConfigField("timeout_seconds", "Request timeout", "number", 60),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(
            category="search_data", measurement_type="observed",
            features=["rank_tracking", "serp_features"],
            notes="Positions are read off a live Bing SERP. No search volume, difficulty or competitor footprint, "
                  "and no keyword discovery — those stay with the Google and keyword-database providers.")

    def _engine_summary(self) -> str:
        return f"Bing {self.config.get('mkt')} · up to {int(self.config.get('pages') or 2)} page(s) per keyword"

    def collect_rank(self, request: dict[str, Any]) -> CollectResult:
        keyword = request["keyword"]
        host = str(request.get("host") or "").strip().lower().removeprefix("www.")
        pages = max(1, min(int(self.config.get("pages") or 2), 10))
        base = {"engine": "bing", "q": keyword, "cc": str(self.config.get("cc") or "us").lower(),
                "mkt": self.config.get("mkt") or None, "location": self.config.get("location") or None,
                "device": str(self.config.get("device") or "desktop")}
        client = self._client()
        first_page: dict[str, Any] | None = None
        extra: list[dict[str, Any]] = []
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for n in range(pages):
            payload = client.search({**base, "first": n * 10 + 1})
            if first_page is None:
                first_page = payload
            else:
                extra.append(payload)
            # Positions are recomputed from the merged order rather than trusted per page: whether Bing numbers
            # results page-locally or globally, and whether a page returns exactly ten, the rank we report is
            # simply where the result sits in the list we actually read.
            for item in payload.get("organic_results") or []:
                if not isinstance(item, dict) or not item.get("link"):
                    continue
                link = str(item["link"])
                if link in seen:
                    continue
                seen.add(link)
                merged.append({**item, "position": len(merged) + 1})
            if host and any(matches_host(host_of(i.get("link")), host) for i in merged):
                break
            if not (payload.get("organic_results") or []):
                break
        raw = {**(first_page or {}), "organic_results": merged}
        if extra:
            raw["serpapi_extra_pages"] = extra
        # `host` travels with the result: normalize_rank needs it, and an adapter that was told which site to look
        # for should not depend on its caller putting that back afterwards.
        return CollectResult(raw=raw, meta={"provider": self.key, "keyword": keyword, "engine": "bing",
                                            "host": host, "searches": 1 + len(extra), "results_read": len(merged),
                                            "cc": base["cc"], "mkt": base["mkt"]})

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        pages = max(1, min(int(self.config.get("pages") or 2), 10))
        return UsageEstimate(requests=pages, unit_type="requests",
                             note=f"Up to {pages} SerpApi search(es) per keyword — one per Bing result page")
