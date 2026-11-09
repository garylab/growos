import json
from pathlib import Path

from app.adapters.base import CollectResult
from app.adapters.crawling.siteone import SiteOneCrawlerAdapter, _page_findings, _score_page, NormalizedPage

FIXTURE = Path(__file__).parent / "fixtures" / "siteone_example.json"


def test_normalize_real_output():
    raw = json.loads(FIXTURE.read_text())
    adapter = SiteOneCrawlerAdapter()
    n = adapter.normalize(CollectResult(raw=raw, meta={"url": "https://example.com/"}))
    assert n.total_urls == 2 and n.html_pages == 1
    assert n.crawler_version.startswith("2.5.1")
    home = next(p for p in n.pages if p.content_type == "html")
    assert home.title == "Example Domain" and home.status_code == 200 and home.path == "/"
    assert home.meta_description is None and home.h1 is None
    codes = {f.code for f in n.findings if f.url == home.url}
    assert {"missing_meta_description", "missing_h1"} <= codes
    assert "title_too_short" in codes  # "Example Domain" is 14 chars
    assert home.seo_score == 100 - 10 - 10 - 3
    assert n.quality_scores["overall"]["score"] == 9.2
    assert any(f.code.startswith("site_") and f.severity == "critical" for f in n.findings)


def test_page_findings_and_score():
    p = NormalizedPage(url="https://x.test/a", path="/a", status_code=200, content_type="html", response_time_ms=2000, size_bytes=10,
                       title="x" * 80, meta_description="d" * 200, h1=None, headings_errors=2, robots_index=False, metadata_captured=True)
    codes = {f.code for f in _page_findings(p)}
    assert codes == {"title_too_long", "meta_description_too_long", "missing_h1", "heading_structure", "noindex", "slow_response"}
    assert _score_page(_page_findings(p)) == 100 - 10 - 3 - 10 - 3 - 3 - 10


def test_extras_used_for_every_page_and_no_false_missing_findings():
    raw = json.loads(FIXTURE.read_text())
    # Simulate a crawl where the seo table is capped (empty) but per-URL extras exist.
    raw["tables"]["seo"]["rows"] = []
    raw["tables"]["seo-headings"]["rows"] = []
    for r in raw["results"]:
        if r["type"] == 1:
            r["extras"] = {"Title": "Example &amp; Co", "Description": "", "H1": "Hello"}
    n = SiteOneCrawlerAdapter().normalize(CollectResult(raw=raw, meta={}))
    home = next(p for p in n.pages if p.content_type == "html")
    assert home.title == "Example & Co" and home.h1 == "Hello" and home.metadata_captured
    codes = {f.code for f in n.findings if f.url == home.url}
    assert "missing_title" not in codes and "missing_h1" not in codes
    assert "missing_meta_description" in codes


def test_pages_without_metadata_are_not_flagged():
    raw = json.loads(FIXTURE.read_text())
    raw["tables"]["seo"]["rows"] = []  # capped table, no extras → metadata unknown
    n = SiteOneCrawlerAdapter().normalize(CollectResult(raw=raw, meta={}))
    home = next(p for p in n.pages if p.content_type == "html")
    assert not home.metadata_captured and home.seo_score == 100
    assert not any(f.code.startswith("missing_") for f in n.findings if f.url == home.url)


def test_page_signal_extraction():
    from app.services.page_signals import extract_signals
    html = """<html><head>
      <link rel="canonical" href="/pricing"/>
      <meta name="robots" content="noindex, follow"/>
      <meta property="og:title" content="Hi"/>
      <script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"X"},{"@type":"WebPage"}]}</script>
    </head><body>
      <a href="https://wa.me/+123">Chat</a><a href="tel:+1">Call</a><a href="mailto:a@b.com">Mail</a>
      <a href="https://www.linkedin.com/company/x">in</a><a href="https://x.com/x">x</a><a href="/about">about</a>
      <form></form></body></html>"""
    s = extract_signals(html, "https://example.com/page")
    assert s["checked"] and s["canonical"] == "https://example.com/pricing"
    assert s["noindex"] is True and s["og_title"] == "Hi"
    assert s["has_organization_schema"] and set(s["jsonld_types"]) == {"Organization", "WebPage"}
    assert s["chat_link"] == "https://wa.me/+123" and s["tel"] == "tel:+1" and s["mailto"] == "mailto:a@b.com"
    assert len(s["social_links"]) == 2 and s["has_form"] is True


def test_page_signals_absent():
    from app.services.page_signals import extract_signals
    s = extract_signals("<html><head><title>t</title></head><body><p>hi</p></body></html>", "https://example.com/")
    assert s["checked"] and s["canonical"] is None and not s["has_organization_schema"]
    assert s["chat_link"] is None and s["social_links"] == [] and s["noindex"] is False


def test_business_signals_email_and_logo():
    from app.services.page_signals import extract_signals
    html = """<html><head><link rel="icon" href="/fav.ico"/>
      <script type="application/ld+json">{"@type":"Organization","logo":"https://x.test/logo.png"}</script></head>
      <body><header><img src="/img/logo.svg" alt="Acme logo"/></header>
      <a href="mailto:hello@x.test">mail</a><a href="mailto:acme@gmail.com">other</a></body></html>"""
    s = extract_signals(html, "https://x.test/")
    assert s["has_logo"] and s["logo_img"] == "https://x.test/img/logo.svg"
    assert s["logo_in_schema"] == "https://x.test/logo.png" and s["favicon"] == "https://x.test/fav.ico"
    assert s["own_domain_emails"] == ["hello@x.test"] and s["free_emails"] == ["acme@gmail.com"]


def test_business_signals_cloudflare_and_plaintext_email():
    from app.services.page_signals import _decode_cfemail, extract_signals

    # Cloudflare encodes "contact@x.test"; first hex byte is the XOR key.
    key = 0x2a
    enc = bytes([key]) + bytes(ord(c) ^ key for c in "contact@x.test")
    cf = enc.hex()
    assert _decode_cfemail(cf) == "contact@x.test"
    assert _decode_cfemail("") is None and _decode_cfemail("zz") is None

    html = f"""<html><body>
      <a href="/cdn-cgi/l/email-protection#{cf}"><span class="__cf_email__" data-cfemail="{cf}"></span></a>
      <p>Or just email founder@x.test directly. See logo@2x.png in the header.</p></body></html>"""
    s = extract_signals(html, "https://x.test/")
    # Cloudflare-protected and plaintext addresses are both recovered; the asset filename is not.
    assert set(s["own_domain_emails"]) == {"contact@x.test", "founder@x.test"}
    assert "logo@2x.png" not in s["emails"]
    # A synthetic mailto is offered so downstream outreach has a usable address even without a real link.
    assert s["mailto"] == "mailto:contact@x.test"


def test_business_signals_missing():
    from app.services.page_signals import extract_signals
    s = extract_signals('<html><head></head><body><a href="mailto:me@gmail.com">m</a></body></html>', "https://x.test/")
    assert not s["has_logo"] and s["favicon"] is None
    assert s["free_emails"] == ["me@gmail.com"] and s["own_domain_emails"] == []


def test_signals_analytics_hreflang_and_capture():
    from app.services.page_signals import extract_signals
    html = """<html><head>
      <link rel="alternate" hreflang="en" href="/"/><link rel="alternate" hreflang="es" href="/es"/>
      <script src="https://www.googletagmanager.com/gtag/js?id=G-X"></script>
      <script src="https://www.clarity.ms/tag/abc"></script></head>
      <body><p>Subscribe to our newsletter for updates</p><form><input type="email" name="email"/></form></body></html>"""
    s = extract_signals(html, "https://x.test/")
    assert s["hreflang"] == ["en", "es"]
    assert set(s["analytics"]) == {"google_analytics", "clarity"}
    assert s["email_capture"] is True


def test_signals_no_analytics_or_capture():
    from app.services.page_signals import extract_signals
    s = extract_signals("<html><body><form><input type='text'/></form></body></html>", "https://x.test/")
    assert s["analytics"] == [] and s["hreflang"] == [] and s["email_capture"] is False


def test_twitter_normalize():
    from app.adapters.base import CollectResult
    from app.adapters.brand.twitter import TwitterAdapter
    raw = {"tweets": [{"id": "123", "text": "Love MockReal!", "author_id": "u1", "created_at": "2026-11-01T10:00:00.000Z",
                       "lang": "en", "public_metrics": {"like_count": 5, "retweet_count": 2, "reply_count": 1, "quote_count": 0}, "_query": "MockReal"}],
           "users": {"u1": {"id": "u1", "username": "alice", "name": "Alice"}}}
    out = TwitterAdapter().normalize(CollectResult(raw=raw, meta={}))
    assert len(out) == 1
    m = out[0]
    assert m["source_name"] == "X" and m["author"] == "alice"
    assert m["source_url"] == "https://x.com/alice/status/123"
    assert m["engagement"]["likes"] == 5 and m["language"] == "en" and m["content"] == "Love MockReal!"


def test_twitter_health_without_token():
    from app.adapters.brand.twitter import TwitterAdapter
    r = TwitterAdapter().health_check()
    assert not r.ok and "paid" in r.message.lower()
