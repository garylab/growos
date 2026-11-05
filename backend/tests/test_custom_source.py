from datetime import UTC, datetime

from app.adapters.base import CollectResult
from app.adapters.brand.custom_source import CustomSourceAdapter, _dig, _parse_time


def test_dig_paths():
    obj = {"data": {"items": [{"text": "hi"}, {"text": "yo"}]}}
    assert _dig(obj, "data.items.1.text") == "yo"
    assert _dig(obj, "missing.x") is None
    assert _dig([1, 2, 3], "2") == 3
    assert _dig({"a": 1}, "") == {"a": 1}


def test_parse_time_formats():
    assert _parse_time("2026-11-01T10:00:00.000Z").year == 2026
    assert _parse_time(1762000000).tzinfo is UTC          # epoch seconds
    assert _parse_time(1762000000000).year == _parse_time(1762000000).year  # epoch millis
    assert _parse_time(None) is None and _parse_time("") is None
    assert _parse_time("not a date") is None


def test_normalize_with_field_mapping():
    cfg = {"items_path": "data", "map_id": "id_str", "map_url": "link", "map_text": "body",
           "map_author": "user.handle", "map_published": "ts", "map_language": "lang",
           "map_likes": "stats.likes", "map_reposts": "", "map_replies": "", "source_label": "Twitter via Apify"}
    a = CustomSourceAdapter(config=cfg)
    raw = {"items": [{"_query": "MockReal", "_item": {
        "id_str": "9", "link": "https://x.com/u/9", "body": "MockReal is great",
        "user": {"handle": "bob"}, "ts": "2026-10-30T12:00:00Z", "lang": "en", "stats": {"likes": 12}}}], "errors": []}
    out = a.normalize(CollectResult(raw=raw, meta={}))
    assert len(out) == 1
    m = out[0]
    assert m["source_id"] == "twitter via apify:9" and m["source_url"] == "https://x.com/u/9"
    assert m["author"] == "bob" and m["content"] == "MockReal is great" and m["language"] == "en"
    assert m["engagement"] == {"likes": 12} and m["source_name"] == "Twitter via Apify"


def test_fill_injects_query_and_key_url_encoded():
    a = CustomSourceAdapter(credentials={"api_key": "SECRET"}, config={"request_url": "https://x/s?q={query}&k={api_key}"})
    assert a._fill("https://x/s?q={query}&k={api_key}", "a b") == "https://x/s?q=a%20b&k=SECRET"


def test_health_check_requires_url():
    r = CustomSourceAdapter().health_check()
    assert not r.ok and "request URL" in r.message


def test_fill_leaves_body_query_unencoded_but_json_safe():
    """A POST body is JSON, not a URL: 'web scraping' must not become 'web%20scraping'."""
    a = CustomSourceAdapter(config={})
    assert a._fill('{"q":"{query}"}', "web scraping", encode=False) == '{"q":"web scraping"}'
    assert a._fill('{"q":"{query}"}', 'say "hi"', encode=False) == '{"q":"say \\"hi\\""}'


def test_timeout_is_configurable_and_clamped():
    assert CustomSourceAdapter(config={})._timeout() == 30.0
    assert CustomSourceAdapter(config={"timeout_seconds": 120})._timeout() == 120.0
    assert CustomSourceAdapter(config={"timeout_seconds": 9999})._timeout() == 300.0
    assert CustomSourceAdapter(config={"timeout_seconds": "nope"})._timeout() == 30.0
