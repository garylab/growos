from app.services.page_inspect import CODE_TO_INSPECTOR, INSPECTORS, PHONE_RE
from selectolax.parser import HTMLParser


def run(inspector: str, html: str, resp=None):
    return INSPECTORS[inspector]["fn"](HTMLParser(html), "https://x.test/p", resp)


def test_missing_h1():
    assert run("missing_h1", "<html><body><h2>x</h2></body></html>")
    assert not run("missing_h1", "<html><body><h1>x</h1></body></html>")


def test_skipped_heading_levels_reports_the_jump():
    issues = run("skipped_heading_levels", "<h1>A</h1><h2>B</h2><h4>C</h4>")
    assert len(issues) == 1
    assert "H2 to H4" in issues[0].detail and issues[0].snippet == "C" and issues[0].element == "h4"
    assert not run("skipped_heading_levels", "<h1>A</h1><h2>B</h2><h3>C</h3>")


def test_non_clickable_phone_ignores_linked_numbers():
    issues = run("non_clickable_phone", '<p>Call 058 553 8259 today</p>')
    assert len(issues) == 1 and "058 553 8259" in issues[0].snippet and 'tel:+' in issues[0].extra["fix"]
    assert not run("non_clickable_phone", '<p><a href="tel:+971585538259">058 553 8259</a></p>')


def test_form_labels():
    issues = run("form_labels", '<form><input name="email" type="email"><input id="a" type="text"><label for="a">A</label>'
                                '<input type="hidden" name="h"><input type="text" aria-label="Search"></form>')
    assert len(issues) == 1 and issues[0].snippet == "email"


def test_main_landmark_and_image_alt():
    assert run("main_landmark", "<body><div>x</div></body>")
    assert not run("main_landmark", "<body><main>x</main></body>")
    assert not run("main_landmark", '<body><div role="main">x</div></body>')
    assert len(run("image_alt", '<img src="/a.png"><img src="/b.png" alt=""><img src="/c.png" aria-hidden="true">')) == 1


def test_compression_uses_response_headers():
    class R:
        headers = {"content-encoding": "gzip", "vary": "Accept-Encoding"}
    issues = run("compression", "<html></html>", R())
    assert issues and issues[0].extra["content_encoding"] == "gzip"

    class R2:
        headers = {"content-encoding": "br"}
    assert not run("compression", "<html></html>", R2())


def test_every_mapped_code_has_an_inspector():
    assert all(v in INSPECTORS for v in CODE_TO_INSPECTOR.values())


def test_phone_regex_ignores_short_numbers_and_paths():
    assert not PHONE_RE.findall("/questions/12")
