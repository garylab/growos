"""Each backlink provider must collapse to the same normalised row shape.

The payloads mirror the documented response of each API. They are the contract this code was written against —
when a real key produces something different, fix the adapter and update the fixture here.
"""
from datetime import date

from app.adapters.backlinks.ahrefs import AhrefsBacklinksAdapter
from app.adapters.backlinks.apify_semrush import ApifySemrushBacklinksAdapter
from app.adapters.backlinks.common import dedupe, host_only, row
from app.adapters.backlinks.custom_backlinks import CustomBacklinksAdapter
from app.adapters.backlinks.dataforseo import DataForSEOBacklinksAdapter
from app.adapters.backlinks.semrush import SemrushBacklinksAdapter
from app.adapters.base import CollectResult

FIELDS = {"referring_domain", "backlinks", "dofollow", "domain_rating", "first_seen", "last_seen", "example_url"}


def test_apify_semrush_normalizes_samples_and_keeps_profile_totals_separate():
    raw = [{"type": "domain_overview", "domain": "me.com", "authority_score": 55, "backlinks": 2356171,
            "referring_domains": 77601, "follow_backlinks": 2000000, "nofollow_backlinks": 356171,
            "backlinks_list_count": 1, "referring_domains_list_count": 1,
            "referring_domains_list": [{"referring_domain": "semrush.com", "backlinks_count": 42,
                                         "domain_authority_score": 88, "first_seen": "2024-04-25"}],
            "backlinks_list": [{"source_url": "https://blog.example/post", "target_url": "https://me.com/",
                                 "anchor": "Me", "nofollow": False, "source_domain_authority_score": 70,
                                 "source_title": "Post", "last_seen": "2026-10-18"}]}]
    adapter = ApifySemrushBacklinksAdapter(credentials={"apify_token": "token"})
    result = CollectResult(raw=raw, meta={})
    domains = adapter.normalize(result)
    links = adapter.normalize_links(result)
    totals = adapter.profile_totals(result)
    assert domains[0]["referring_domain"] == "semrush.com" and domains[0]["backlinks"] == 42
    assert domains[0]["domain_rating"] == 88 and domains[0]["dofollow"] == 0
    assert links[0]["referring_domain"] == "blog.example" and links[0]["dofollow"] is True
    assert links[0]["page_title"] == "Post" and links[0]["last_seen"] == date(2026, 10, 18)
    assert totals["backlinks"] == 2356171 and totals["sampled_backlinks"] == 1


def test_apify_semrush_actor_input_and_paid_run_are_reused(monkeypatch):
    calls = []
    class Response:
        # Apify's synchronous Actor endpoint commonly returns 201 Created with the completed dataset body.
        status_code = 201
        text = "ok"
        def json(self):
            return [{"type": "domain_overview", "domain": "me.com", "backlinks_list": []}]
    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr("app.adapters.backlinks.apify_semrush.httpx.post", fake_post)
    adapter = ApifySemrushBacklinksAdapter(credentials={"apify_token": "secret"},
        config={"max_charge_usd": 0.5, "backlinks_limit": 80, "referring_domains_limit": 60})
    first = adapter.collect({"target": "me.com"})
    second = adapter.collect_links({"target": "me.com"})
    assert first is second and len(calls) == 1
    assert calls[0][1]["params"] == {"maxItems": 1, "maxTotalChargeUsd": 0.5}
    assert calls[0][1]["json"]["include_backlinks"] is True
    assert "secret" not in str(calls[0][1]["json"])


# ------------------------------------------------------------------ shared helpers
def test_host_only_strips_scheme_path_and_www():
    assert host_only("https://www.Example.com/a/b?c=1") == "example.com"
    assert host_only("Example.COM/path") == "example.com"
    assert host_only("sub.example.com") == "sub.example.com"
    assert host_only("") == "" and host_only(None) == ""


def test_row_never_claims_more_dofollow_than_links():
    assert row("a.com", backlinks=5, dofollow=9)["dofollow"] == 5
    assert row("a.com", backlinks=0, dofollow=0)["dofollow"] == 0
    assert row("   ") is None


def test_dedupe_keeps_the_richest_row_and_sorts_by_links():
    rows = [row("a.com", backlinks=2), row("b.com", backlinks=9), row("a.com", backlinks=7)]
    out = dedupe(rows)
    assert [r["referring_domain"] for r in out] == ["b.com", "a.com"]
    assert out[1]["backlinks"] == 7


# ------------------------------------------------------------------ DataForSEO
def test_dataforseo_normalize():
    raw = {"tasks": [{"status_code": 20000, "result": [{"items": [
        {"domain": "www.Blog.com", "backlinks": 12, "rank": 180, "first_seen": "2025-02-03 10:00:00 +00:00",
         "last_seen": "2026-10-01 00:00:00 +00:00", "referring_links_attributes": {"nofollow": 4}},
        {"domain": "news.example.org", "backlinks": 3, "rank": 90, "referring_links_attributes": {}},
        {"domain": "", "backlinks": 99},                       # unusable, dropped
    ]}]}]}
    rows = DataForSEOBacklinksAdapter().normalize(CollectResult(raw=raw, meta={}))
    assert [r["referring_domain"] for r in rows] == ["blog.com", "news.example.org"]
    assert set(rows[0]) == FIELDS
    assert rows[0]["backlinks"] == 12 and rows[0]["dofollow"] == 8      # 12 total - 4 nofollow
    assert rows[0]["domain_rating"] == 180.0
    assert rows[0]["first_seen"] == date(2025, 2, 3)
    assert rows[1]["dofollow"] == 3                                     # no attributes block -> all follow


# ------------------------------------------------------------------ Ahrefs
def test_ahrefs_normalize():
    raw = {"refdomains": [
        {"domain": "partner.io", "domain_rating": 61.5, "links_to_target": 40, "dofollow_links_to_target": 31,
         "first_seen": "2024-07-01T00:00:00Z", "last_seen": "2026-11-01T00:00:00Z"},
        {"domain": "www.tiny.dev", "domain_rating": 4, "links_to_target": 1, "dofollow_links_to_target": 0},
    ]}
    rows = AhrefsBacklinksAdapter().normalize(CollectResult(raw=raw, meta={}))
    assert [r["referring_domain"] for r in rows] == ["partner.io", "tiny.dev"]
    assert rows[0]["backlinks"] == 40 and rows[0]["dofollow"] == 31
    assert rows[0]["domain_rating"] == 61.5
    assert rows[0]["first_seen"] == date(2024, 7, 1)
    assert rows[1]["dofollow"] == 0


def test_ahrefs_empty_payload():
    assert AhrefsBacklinksAdapter().normalize(CollectResult(raw={}, meta={})) == []


# ------------------------------------------------------------------ Semrush (semicolon-separated text)
def test_semrush_normalize():
    body = ("domain;domain_ascore;backlinks_num;first_seen;last_seen\n"
            "good.com;55;120;2023-01-05;2026-10-30\n"
            "www.Other.NET;12;7;2025-06-01;2026-09-09\n"
            "broken;row\n")                                     # wrong column count, skipped
    rows = SemrushBacklinksAdapter().normalize(CollectResult(raw={"body": body}, meta={}))
    assert [r["referring_domain"] for r in rows] == ["good.com", "other.net"]
    assert rows[0]["backlinks"] == 120 and rows[0]["domain_rating"] == 55.0
    assert rows[0]["last_seen"] == date(2026, 10, 30)
    # Semrush does not split follow/nofollow in this report, so dofollow stays 0 rather than being invented.
    assert all(r["dofollow"] == 0 for r in rows)


def test_semrush_header_only_or_empty():
    assert SemrushBacklinksAdapter().normalize(CollectResult(raw={"body": "domain;backlinks_num\n"}, meta={})) == []
    assert SemrushBacklinksAdapter().normalize(CollectResult(raw={}, meta={})) == []


# ------------------------------------------------------------------ Custom endpoint
def _custom(**config):
    return CustomBacklinksAdapter(credentials={}, config={"request_url": "https://api.example.com/x", **config})


def test_custom_normalize_with_nested_path_and_mapping():
    raw = {"data": {"refdomains": [
        {"site": "https://ref-one.com/page", "links": "25", "follow": "20", "score": "70", "seen": "2026-01-02"},
        {"site": "ref-two.com", "links": 2},
    ]}}
    rows = _custom(items_path="data.refdomains", map_domain="site", map_backlinks="links",
                   map_dofollow="follow", map_rating="score", map_first_seen="seen").normalize(
        CollectResult(raw=raw, meta={}))
    assert [r["referring_domain"] for r in rows] == ["ref-one.com", "ref-two.com"]
    assert rows[0]["backlinks"] == 25 and rows[0]["dofollow"] == 20 and rows[0]["domain_rating"] == 70.0
    assert rows[0]["first_seen"] == date(2026, 1, 2)


def test_custom_normalize_when_body_is_the_array():
    raw = [{"domain": "a.com", "backlinks": 4}]
    rows = _custom().normalize(CollectResult(raw=raw, meta={}))
    assert rows == [row("a.com", backlinks=4)]


def test_custom_normalize_bad_mapping_yields_nothing_rather_than_garbage():
    raw = {"data": {"refdomains": [{"site": "a.com", "links": 4}]}}
    assert _custom(items_path="wrong.path").normalize(CollectResult(raw=raw, meta={})) == []
    assert _custom(items_path="data.refdomains", map_domain="nope").normalize(CollectResult(raw=raw, meta={})) == []


def test_custom_respects_its_row_limit():
    raw = [{"domain": f"d{n}.com", "backlinks": n} for n in range(50)]
    assert len(_custom(limit=10).normalize(CollectResult(raw=raw, meta={}))) == 10


def test_custom_url_template_and_ssrf_guard():
    import pytest
    from app.adapters.base import ProviderError
    a = CustomBacklinksAdapter(credentials={"api_key": "k123"},
                               config={"request_url": "https://api.example.com/r?site={target}&key={api_key}"})
    assert a._url("acme.com") == "https://api.example.com/r?site=acme.com&key=k123"
    private = CustomBacklinksAdapter(config={"request_url": "http://127.0.0.1:8080/{target}"})
    with pytest.raises(ProviderError):
        private._url("acme.com")


# ================================================================== individual links
from app.adapters.backlinks.common import dedupe_links, link_hash, link_row  # noqa: E402

LINK_FIELDS = {"url_from", "url_to", "referring_domain", "anchor", "page_title", "dofollow",
               "domain_rating", "first_seen", "last_seen"}


def test_link_row_requires_a_usable_source_url():
    assert link_row("", "https://me.com") is None
    assert link_row("not a url", "https://me.com") is not None   # bare host is still addressable
    r = link_row("https://blog.com/post", "https://me.com/pricing", anchor="  best tool  ")
    assert set(r) == LINK_FIELDS
    assert r["referring_domain"] == "blog.com" and r["anchor"] == "best tool"


def test_link_hash_distinguishes_anchor_but_not_order():
    a = link_row("https://b.com/1", "https://me.com", anchor="one")
    b = link_row("https://b.com/1", "https://me.com", anchor="two")
    assert link_hash(a) != link_hash(b)
    assert link_hash(a) == link_hash(link_row("https://b.com/1", "https://me.com", anchor="one"))


def test_dedupe_links_keeps_order_and_drops_exact_repeats():
    rows = [link_row("https://a.com/1", "https://me.com", anchor="x"),
            link_row("https://b.com/1", "https://me.com", anchor="y"),
            link_row("https://a.com/1", "https://me.com", anchor="x")]
    assert [r["referring_domain"] for r in dedupe_links(rows)] == ["a.com", "b.com"]


def test_dataforseo_normalize_links():
    raw = {"tasks": [{"result": [{"items": [
        {"url_from": "https://blog.com/review", "url_to": "https://me.com/pricing", "anchor": "the pricing page",
         "page_from_title": "A review", "dofollow": True, "domain_from_rank": 210,
         "first_seen": "2025-05-05 00:00:00 +00:00", "last_seen": "2026-10-10 00:00:00 +00:00"},
        {"url_from": "https://spam.io/x", "url_to": "https://me.com/", "anchor": "click here", "dofollow": False},
        {"url_from": "", "url_to": "https://me.com/"},                        # unusable, dropped
    ]}]}]}
    rows = DataForSEOBacklinksAdapter().normalize_links(CollectResult(raw=raw, meta={}))
    assert len(rows) == 2 and set(rows[0]) == LINK_FIELDS
    assert rows[0]["anchor"] == "the pricing page" and rows[0]["page_title"] == "A review"
    assert rows[0]["url_to"] == "https://me.com/pricing" and rows[0]["dofollow"] is True
    assert rows[1]["dofollow"] is False


def test_ahrefs_normalize_links():
    raw = {"backlinks": [
        {"url_from": "https://news.org/story", "url_to": "https://me.com/docs", "anchor": "their docs",
         "title": "Story", "is_dofollow": True, "domain_rating_source": 72.5,
         "first_seen": "2024-01-01T00:00:00Z", "last_seen": "2026-11-01T00:00:00Z"},
        {"url_from": "https://dir.net/l", "url_to": "https://me.com", "anchor": "", "is_dofollow": False},
    ]}
    rows = AhrefsBacklinksAdapter().normalize_links(CollectResult(raw=raw, meta={}))
    assert [r["referring_domain"] for r in rows] == ["news.org", "dir.net"]
    assert rows[0]["anchor"] == "their docs" and rows[0]["domain_rating"] == 72.5
    assert rows[1]["anchor"] is None and rows[1]["dofollow"] is False


def test_semrush_normalize_links_inverts_the_nofollow_flag():
    body = ("source_url;source_title;target_url;anchor;nofollow;page_ascore;first_seen;last_seen\n"
            "https://a.com/p;Post A;https://me.com/x;great tool;false;44;2025-01-01;2026-10-01\n"
            "https://b.com/p;Post B;https://me.com/y;here;true;12;2025-02-02;2026-09-09\n")
    rows = SemrushBacklinksAdapter().normalize_links(CollectResult(raw={"body": body}, meta={}))
    assert [r["dofollow"] for r in rows] == [True, False]
    assert rows[0]["anchor"] == "great tool" and rows[0]["page_title"] == "Post A"
    assert rows[0]["domain_rating"] == 44.0


def test_custom_normalize_links_with_mapping_and_nofollow():
    raw = {"items": [
        {"from": "https://x.com/a", "to": "https://me.com/p", "text": "anchor text", "nf": "false"},
        {"from": "https://y.com/b", "to": "https://me.com/q", "text": "other", "nf": "true"},
    ]}
    a = _custom(links_url="https://api.example.com/links?t={target}", links_items_path="items",
                map_url_from="from", map_url_to="to", map_anchor="text", map_nofollow="nf")
    rows = a.normalize_links(CollectResult(raw=raw, meta={}))
    assert [r["dofollow"] for r in rows] == [True, False]
    assert rows[0]["anchor"] == "anchor text" and rows[0]["referring_domain"] == "x.com"


def test_custom_links_default_to_dofollow_when_no_flag_is_mapped():
    raw = {"items": [{"url_from": "https://x.com/a", "url_to": "https://me.com/p", "anchor": "t"}]}
    rows = _custom(links_items_path="items").normalize_links(CollectResult(raw=raw, meta={}))
    assert rows[0]["dofollow"] is True and rows[0]["page_title"] is None
