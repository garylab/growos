"""Registry of available provider adapters. The Integrations UI is generated from this."""
from __future__ import annotations

from app.adapters.ai.gemini import GeminiAdapter
from app.adapters.ai.openai_compat import OllamaAdapter, OpenAICompatibleAdapter, PerplexityAdapter
from app.adapters.ai.openai import OpenAIAdapter
from app.adapters.ai.serpapi_surfaces import SerpApiAISurfacesAdapter
from app.adapters.analytics.ga4 import GoogleAnalytics4Adapter
from app.adapters.backlinks.ahrefs import AhrefsBacklinksAdapter
from app.adapters.backlinks.apify_semrush import ApifySemrushBacklinksAdapter
from app.adapters.backlinks.dataforseo import DataForSEOBacklinksAdapter
from app.adapters.backlinks.semrush import SemrushBacklinksAdapter
from app.adapters.base import ProviderAdapter
from app.adapters.custom_api import CustomAPIAdapter
from app.adapters.search_data.ahrefs import AhrefsSearchDataAdapter
from app.adapters.search_data.dataforseo import DataForSEOSearchDataAdapter
from app.adapters.search_data.semrush import SemrushSearchDataAdapter
from app.adapters.search_data.serpapi import SerpApiBingAdapter, SerpApiSearchDataAdapter
from app.adapters.brand.bluesky import BlueskyAdapter
from app.adapters.brand.hackernews import HackerNewsAdapter
from app.adapters.brand.apify_linkedin import ApifyLinkedInPostsAdapter
from app.adapters.brand.rss import RSSAdapter
from app.adapters.brand.serpapi_tiktok import SerpApiTikTokDiscoverAdapter
from app.adapters.brand.serpapi_youtube import SerpApiYouTubeAdapter
from app.adapters.brand.twitter import TwitterAdapter
from app.adapters.crawling.serpapi_extract import SerpApiExtractAdapter
from app.adapters.crawling.siteone import SiteOneCrawlerAdapter
from app.adapters.performance.crux import CruxAdapter
from app.adapters.performance.pagespeed import PageSpeedInsightsAdapter
from app.adapters.search_performance.bing import BingWebmasterAdapter
from app.adapters.search_performance.gsc import GoogleSearchConsoleAdapter

ADAPTERS: dict[str, type[ProviderAdapter]] = {
    cls.key: cls for cls in [
        SiteOneCrawlerAdapter, SerpApiExtractAdapter,
        PageSpeedInsightsAdapter, CruxAdapter,
        GoogleSearchConsoleAdapter, BingWebmasterAdapter,
        GoogleAnalytics4Adapter,
        OpenAIAdapter, GeminiAdapter, PerplexityAdapter, OpenAICompatibleAdapter, OllamaAdapter,
        SerpApiAISurfacesAdapter,
        RSSAdapter, HackerNewsAdapter, BlueskyAdapter, TwitterAdapter, CustomAPIAdapter, ApifyLinkedInPostsAdapter,
        SerpApiYouTubeAdapter, SerpApiTikTokDiscoverAdapter,
        DataForSEOBacklinksAdapter, AhrefsBacklinksAdapter, SemrushBacklinksAdapter, ApifySemrushBacklinksAdapter,
        DataForSEOSearchDataAdapter, AhrefsSearchDataAdapter, SemrushSearchDataAdapter,
        SerpApiSearchDataAdapter, SerpApiBingAdapter,
    ]
}

CATEGORIES = {
    "crawling": "Website crawling & auditing",
    "performance": "Page performance (Lighthouse / CrUX)",
    "search_performance": "Search performance (first-party)",
    "ai": "AI answer providers (GEO) & analysis",
    "brand": "Brand & competitor monitoring",
    "analytics": "Website analytics",
    "backlinks": "Backlinks & referring domains",
    "search_data": "Keyword & SERP data",
}

PLANNED_ADAPTERS = [
    {"vendor": "Reddit", "key": "reddit", "category": "brand", "display_name": "Reddit API", "status": "planned",
     "note": "Requires an approved Reddit API application; not bundled to respect API terms."},
    {"vendor": "Google", "key": "youtube_data", "category": "brand", "display_name": "YouTube Data API (official)", "status": "planned",
     "note": "YouTube search is already available through SerpApi above. The official API would add exact publish "
             "dates and comment threads, at the cost of a Google Cloud project and quota management."},
    {"vendor": "Mastodon", "key": "mastodon", "category": "brand", "display_name": "Mastodon instances", "status": "planned", "note": ""},
    {"vendor": "Google", "key": "lighthouse_cli", "category": "performance", "display_name": "Local Lighthouse CLI", "status": "planned",
     "note": "PageSpeed Insights runs Lighthouse for you without bundling Chrome."},
]


def provider_features(key: str) -> set[str]:
    """Declared features of one provider, or an empty set for a key we do not ship."""
    cls = ADAPTERS.get(key)
    return set(cls.declared_features()) if cls else set()


def providers_with_feature(feature: str, category: str | None = None) -> list[str]:
    return [k for k, cls in ADAPTERS.items()
            if feature in cls.declared_features() and (category is None or cls.category == category)]


def get_adapter_class(key: str) -> type[ProviderAdapter]:
    try:
        return ADAPTERS[key]
    except KeyError as exc:
        raise KeyError(f"Unknown provider '{key}'") from exc
