from app.core.content_extract import DOM, TRAFILATURA, main_text

ARTICLE = """<html><head><title>Why audits matter</title></head><body>
<nav>Home About Pricing Blog</nav>
<div id="cookie">We use cookies to improve your experience. Accept all cookies.</div>
<article><h1>Why audits matter</h1>
<p>A technical audit finds the problems that quietly cost a site its traffic over months rather than days.</p>
<p>The useful part is not the score but the list of pages, because a score cannot be assigned to anyone to fix.</p>
<p>Run it on a schedule and compare runs, so a regression shows up as a change and not as a number you distrust.</p>
</article>
<aside>Related: 7 tips for faster pages, 9 tricks, the latest post</aside>
<footer>Copyright 2026 Example Inc. All rights reserved.</footer></body></html>"""


def test_boilerplate_is_removed():
    out = main_text(ARTICLE, "https://example.com/post")
    assert out.method == TRAFILATURA
    assert "technical audit finds the problems" in out.text
    for furniture in ("cookies", "Related:", "Copyright 2026", "Home About Pricing"):
        assert furniture not in out.text


def test_only_boilerplate_changing_is_not_a_content_change():
    """The reason this exists: a rotating rail must not read as a changed page."""
    a = main_text(ARTICLE, "https://example.com/post").text
    b = main_text(ARTICLE.replace("Related: 7 tips for faster pages, 9 tricks, the latest post",
                                  "Related: a totally different set of posts entirely, and one more"),
                  "https://example.com/post").text
    assert a == b


def test_real_content_change_is_still_seen():
    changed = main_text(ARTICLE.replace("over months rather than days", "within a single week"),
                        "https://example.com/post").text
    assert changed != main_text(ARTICLE, "https://example.com/post").text
    assert "within a single week" in changed


def test_main_wrapped_content_is_not_doubled():
    html = """<html><head><title>Pricing</title></head><body>
    <main><h1>Pricing</h1>
    <p>Our plans are simple and transparent, with no hidden fees anywhere in the whole product.</p>
    <p>Every plan includes unlimited projects, email support and a fourteen day free trial.</p></main></body></html>"""
    text = main_text(html, "https://example.com/pricing").text
    assert text.count("no hidden fees") == 1
    assert text.count("fourteen day free trial") == 1


def test_tables_are_kept_because_pricing_pages_are_tables():
    html = """<html><head><title>Plans</title></head><body><main>
    <p>Pick the plan that fits how your team works today, and change it whenever that stops being true.</p>
    <table><tr><td>Starter</td><td>$19/mo</td></tr><tr><td>Pro</td><td>$49/mo</td></tr></table>
    </main></body></html>"""
    text = main_text(html, "https://example.com/plans").text
    assert "$19/mo" in text and "$49/mo" in text


def test_non_article_page_falls_back_rather_than_coming_back_empty():
    """An empty result downstream reads as 'the content was deleted', so a miss must fall back, not blank out."""
    html = "<html><head><title>Dashboard</title></head><body><div id='root'></div>" + \
           "<table>" + "".join(f"<tr><td>row {i}</td><td>{i * 3}</td></tr>" for i in range(200)) + "</table></body></html>"
    out = main_text(html, "https://example.com/app")
    assert out.text, "extraction must never return an empty document for a page with content"
    assert "row 7" in out.text
    assert out.method in (TRAFILATURA, DOM)


def test_title_comes_from_the_document_either_way():
    assert main_text(ARTICLE).title == "Why audits matter"
    assert main_text("<html><head><title>T</title></head><body><p>hi</p></body></html>").title == "T"
