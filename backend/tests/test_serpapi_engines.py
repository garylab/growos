"""Bing positions, YouTube and TikTok Discover: the three engines added on top of the Google providers.

Payloads mirror SerpApi's documented responses. The Bing cases are the interesting ones — that engine has no
result-count parameter, so depth is paginated and billed per page.
"""
from datetime import UTC, datetime

import pytest

from app.adapters.base import CollectResult, ProviderError
from app.adapters.brand.common import extracted_int, parse_relative_date
from app.adapters.brand.serpapi_tiktok import SerpApiTikTokDiscoverAdapter, discover_keywords
from app.adapters.brand.serpapi_youtube import SerpApiYouTubeAdapter
from app.adapters.registry import provider_features, providers_with_feature
from app.adapters.search_data.serpapi import SerpApiBingAdapter

KEY = {"api_key": "test-key"}


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def search(self, params):
        self.calls.append(params)
        if not self.responses:
            raise AssertionError("unexpected extra search")
        payload = self.responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload


def with_client(adapter, *responses):
    fake = FakeClient(*responses)
    adapter._client = lambda: fake          # noqa: SLF001
    return fake


def bing_page(*links, **extra):
    return {"search_metadata": {"id": "b"}, "search_parameters": {"q": "k"},
            "organic_results": [{"position": i + 1, "link": l} for i, l in enumerate(links)], **extra}


# ------------------------------------------------------------------ Bing: paginated depth
def test_bing_stops_paging_as_soon_as_the_site_is_found():
    """Each page is a billed search, so the full depth is only paid for keywords we do not rank for."""
    a = SerpApiBingAdapter(credentials=KEY, config={"pages": 4})
    fake = with_client(a, bing_page("https://rival.test/a", "https://ours.test/b"))
    result = a.collect_rank({"keyword": "k", "host": "ours.test"})
    assert len(fake.calls) == 1 and result.meta["searches"] == 1
    assert a.normalize_rank(result)["position"] == 2


def test_bing_pays_for_every_page_when_the_site_is_absent():
    a = SerpApiBingAdapter(credentials=KEY, config={"pages": 3})
    fake = with_client(a, bing_page("https://x.test/1"), bing_page("https://x.test/2"), bing_page("https://x.test/3"))
    result = a.collect_rank({"keyword": "k", "host": "absent.test"})
    assert [c["first"] for c in fake.calls] == [1, 11, 21]
    assert result.meta["searches"] == 3
    row = a.normalize_rank(result)
    assert row["position"] is None and row["keyword"] == "k"


def test_a_position_on_a_later_page_is_counted_from_the_merged_list():
    """Bing may number results per page; the rank we report is where the result sits in what we actually read."""
    a = SerpApiBingAdapter(credentials=KEY, config={"pages": 3})
    with_client(a,
                bing_page(*[f"https://x.test/{i}" for i in range(10)]),
                bing_page(*[f"https://y.test/{i}" for i in range(10)]),
                bing_page("https://z.test/0", "https://ours.test/win"))
    result = a.collect_rank({"keyword": "k", "host": "ours.test"})
    assert a.normalize_rank(result)["position"] == 22


def test_results_repeated_across_pages_are_not_counted_twice():
    a = SerpApiBingAdapter(credentials=KEY, config={"pages": 2})
    with_client(a, bing_page("https://x.test/1", "https://x.test/2"),
                bing_page("https://x.test/2", "https://ours.test/c"))
    result = a.collect_rank({"keyword": "k", "host": "ours.test"})
    assert result.meta["results_read"] == 3
    assert a.normalize_rank(result)["position"] == 3


def test_paging_stops_early_when_bing_runs_out_of_results():
    a = SerpApiBingAdapter(credentials=KEY, config={"pages": 5})
    fake = with_client(a, bing_page("https://x.test/1"), bing_page())
    a.collect_rank({"keyword": "k", "host": "absent.test"})
    assert len(fake.calls) == 2


def test_the_extra_pages_we_store_are_not_mistaken_for_serp_features():
    a = SerpApiBingAdapter(credentials=KEY, config={"pages": 2})
    with_client(a, bing_page("https://x.test/1", related_searches=[{"query": "q"}]), bing_page("https://x.test/2"))
    result = a.collect_rank({"keyword": "k", "host": "absent.test"})
    assert "serpapi_extra_pages" in result.raw
    assert a.normalize_rank(result)["serp_features"] == ["related_searches"]


def test_bing_sends_its_own_locale_parameters_not_googles():
    a = SerpApiBingAdapter(credentials=KEY, config={"cc": "GB", "mkt": "en-GB", "pages": 1})
    fake = with_client(a, bing_page("https://ours.test/a"))
    a.collect_rank({"keyword": "k", "host": "ours.test"})
    sent = fake.calls[0]
    assert sent["engine"] == "bing" and sent["cc"] == "gb" and sent["mkt"] == "en-GB"
    assert "num" not in sent and "gl" not in sent          # Bing has neither


def test_bing_budgets_one_search_per_page():
    a = SerpApiBingAdapter(credentials=KEY, config={"pages": 3})
    assert a.estimate_usage({}).requests == 3


def test_bing_is_a_separate_provider_so_its_rows_never_overwrite_googles():
    """RankObservation is unique per provider_key, which is why these are two providers and not one engine switch."""
    assert SerpApiBingAdapter.key != "serpapi_serp"
    assert {"serpapi_serp", "serpapi_bing", "dataforseo_labs"} <= set(providers_with_feature("rank_tracking"))
    assert "keyword_discovery" not in provider_features("serpapi_bing")


# ------------------------------------------------------------------ relative dates
def test_a_relative_age_becomes_a_timestamp():
    now = datetime(2026, 6, 15, tzinfo=UTC)
    assert parse_relative_date("3 days ago", now=now).date() == datetime(2026, 6, 12, tzinfo=UTC).date()
    assert parse_relative_date("6d ago", now=now).date() == datetime(2026, 6, 9, tzinfo=UTC).date()
    assert parse_relative_date("Streamed 2 weeks ago", now=now).date() == datetime(2026, 6, 1, tzinfo=UTC).date()
    assert parse_relative_date("1 year ago", now=now).year == 2025


def test_an_absolute_date_is_passed_through_and_junk_is_dropped():
    assert parse_relative_date("2026-03-04T10:00:00Z").year == 2026
    assert parse_relative_date("") is None and parse_relative_date(None) is None
    assert parse_relative_date("sometime") is None


def test_counts_are_read_from_either_the_number_or_the_label():
    assert extracted_int(12345) == 12345
    assert extracted_int("1.2M views") == 1_200_000
    assert extracted_int("12K views") == 12_000
    assert extracted_int("1,234 views") == 1234
    assert extracted_int(None) is None and extracted_int("no views") is None


# ------------------------------------------------------------------ YouTube
YT_VIDEO = {"title": "Acme vs Rival honest review", "link": "https://www.youtube.com/watch?v=abc",
            "video_id": "abc", "channel": {"name": "Tech Reviews", "link": "https://youtube.com/@tech"},
            "published_date": "3 days ago", "views": "12K views", "extracted_views": 12043,
            "length": "10:21", "description": "We compare Acme and Rival."}


def test_youtube_maps_one_search_per_query_onto_mention_rows():
    a = SerpApiYouTubeAdapter(credentials=KEY, config={"newest_first": True})
    fake = with_client(a, {"video_results": [YT_VIDEO]}, {"video_results": []})
    result = a.collect({"queries": ["Acme", "Rival"]})
    assert [c["engine"] for c in fake.calls] == ["youtube", "youtube"]
    assert fake.calls[0]["search_query"] == "Acme" and "sp" in fake.calls[0]
    assert result.meta["searches"] == 2
    row = a.normalize(result)[0]
    assert row["source_id"] == "youtube:abc"
    assert row["source_name"] == "Tech Reviews" and row["author"] == "Tech Reviews"
    assert row["content"] == "We compare Acme and Rival."
    assert row["engagement"]["views"] == 12043 and row["engagement"]["length"] == "10:21"
    assert row["published_at"] is not None


def test_relevance_order_is_used_when_newest_first_is_off():
    a = SerpApiYouTubeAdapter(credentials=KEY, config={"newest_first": False})
    fake = with_client(a, {"video_results": []})
    a.collect({"queries": ["Acme"]})
    assert "sp" not in fake.calls[0]


def test_one_dead_query_does_not_lose_the_others():
    a = SerpApiYouTubeAdapter(credentials=KEY)
    with_client(a, ProviderError("rate limited"), {"video_results": [YT_VIDEO]})
    result = a.collect({"queries": ["Acme", "Rival"]})
    assert result.meta["searches"] == 1 and "Acme" in result.meta["failures"]
    assert len(a.normalize(result)) == 1


def test_youtube_raises_when_every_query_failed():
    a = SerpApiYouTubeAdapter(credentials=KEY)
    with_client(a, ProviderError("bad key"))
    with pytest.raises(ProviderError, match="bad key"):
        a.collect({"queries": ["Acme"]})
    with pytest.raises(ProviderError, match="No queries"):
        a.collect({"queries": []})


def test_a_video_without_an_id_is_dropped_rather_than_stored_unkeyed():
    a = SerpApiYouTubeAdapter(credentials=KEY)
    rows = a.normalize(CollectResult(raw={"video_results": [{"title": "no id or link"}]}, meta={}))
    assert rows == []


# ------------------------------------------------------------------ TikTok Discover
TT_VIDEO = {"position": 1, "id": "7123", "link": "https://www.tiktok.com/@user/video/7123",
            "description": "My Acme routine\nday 4", "duration": 31, "published_date": "2026-05-02T09:00:00Z",
            "plays": 120000, "likes": 8400, "comments": 310, "shares": 95, "bookmarks": 1200,
            "author": {"id": "u1", "username": "user", "name": "Skin User", "link": "https://tiktok.com/@user"},
            "hashtags": [{"name": "skincare"}, {"name": "acmebrand"}]}


def test_discover_keywords_accept_lines_commas_hashtags_and_pasted_urls():
    assert discover_keywords("skincare\n#retinol, https://www.tiktok.com/discover/face-serum?lang=en") == \
        ["skincare", "retinol", "face-serum"]
    assert discover_keywords(" ") == [] and discover_keywords(None) == []
    assert discover_keywords("dupe\ndupe") == ["dupe"]          # deduped


def test_tiktok_reads_the_configured_pages_and_ignores_the_tracked_queries():
    """The asymmetry that matters: SerpApi has no TikTok search, so brand names cannot be the query."""
    a = SerpApiTikTokDiscoverAdapter(credentials=KEY, config={"discover_pages": "skincare\nretinol"})
    fake = with_client(a, {"video_results": [TT_VIDEO]}, {"video_results": []})
    result = a.collect({"queries": ["Acme", "Rival"]})
    assert [c["q"] for c in fake.calls] == ["skincare", "retinol"]
    assert all(c["engine"] == "tiktok_discover" for c in fake.calls)
    assert result.meta["searches"] == 2 and result.meta["discover_pages"] == ["skincare", "retinol"]


def test_tiktok_rows_carry_the_engagement_a_video_platform_actually_reports():
    a = SerpApiTikTokDiscoverAdapter(credentials=KEY, config={"discover_pages": "skincare"})
    row = a.normalize(CollectResult(raw={"video_results": [{**TT_VIDEO, "_page": "skincare"}]}, meta={}))[0]
    assert row["source_id"] == "tiktok:7123" and row["source_name"] == "TikTok"
    assert row["title"] == "My Acme routine" and row["author"] == "Skin User"
    assert row["published_at"].year == 2026 and row["published_at"].month == 5
    assert row["engagement"] == {"plays": 120000, "likes": 8400, "comments": 310, "shares": 95,
                                 "bookmarks": 1200, "duration": 31, "author_url": "https://tiktok.com/@user",
                                 "discover_page": "skincare", "kind": "tiktok"}


def test_hashtags_are_appended_so_mention_extraction_can_see_the_brand_in_them():
    """A video whose caption never spells out the brand but tags it would otherwise be filtered out."""
    a = SerpApiTikTokDiscoverAdapter(credentials=KEY, config={"discover_pages": "skincare"})
    row = a.normalize(CollectResult(raw={"video_results": [TT_VIDEO]}, meta={}))[0]
    assert "#acmebrand" in row["content"]
    assert row["content"].count("skincare") == 1          # already in no caption, added once from the hashtag


def test_tiktok_refuses_to_run_with_no_pages_configured():
    a = SerpApiTikTokDiscoverAdapter(credentials=KEY)
    with pytest.raises(ProviderError, match="no TikTok Discover pages|No TikTok Discover pages"):
        a.collect({"queries": ["Acme"]})
    assert a.health_check().ok is False
    assert "Discover pages" in a.health_check().message


def test_both_video_sources_join_the_brand_pipeline_by_capability():
    assert "mentions" in provider_features("serpapi_youtube")
    assert "mentions" in provider_features("serpapi_tiktok")
    assert {"rss", "hackernews", "serpapi_youtube", "serpapi_tiktok"} <= set(providers_with_feature("mentions"))
