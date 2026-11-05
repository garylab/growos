"""Main-content extraction: the article, without the furniture around it.

Two callers need the same thing for different reasons, and both were getting it wrong in the same way.

*Change detection* hashes a watched page's text and reports a change when the hash moves. Stripping only
`nav`/`footer` by tag name leaves cookie banners, rotating testimonials, "12 people are viewing this", related-post
rails and dated copyright lines in the text, so a page whose actual content never changed reports a change on
most runs. A change report that is usually noise trains the user to ignore it, which costs more than not having it.

*Brand monitoring* reads RSS `summary`, which publishers truncate to a sentence or two. A brand named in the third
paragraph is simply never seen, and the mention is missed with no trace that anything was missed.

Trafilatura does the main-content extraction. It is deliberately wrapped rather than called directly:

* It returns `None` when it cannot find an article, which is common and expected on exactly the pages change
  detection watches — a pricing page is a table and six words, not prose. `None` must therefore fall back to the
  DOM strip rather than yield an empty document, which would otherwise read as "the whole page was deleted".
* `method` travels with the result so a caller comparing two extractions can tell whether they are comparable at
  all. Two texts produced by different extractors cannot be diffed into a meaningful change ratio.
* On some documents — reproducibly, pages whose content sits in a `<main>` element — it emits the main block
  twice. Left alone that doubles every change ratio computed from the text, so the repeat is dropped here.
"""
from __future__ import annotations

from dataclasses import dataclass

from selectolax.parser import HTMLParser

# Boilerplate lives in these; nav/footer alone is not enough, and `aside` carries the related-content rails that
# change whenever anything else on the site is published.
BOILERPLATE_TAGS = ("script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "template", "iframe", "form")

TRAFILATURA = "trafilatura"
DOM = "dom"


@dataclass
class Extracted:
    text: str
    title: str | None = None
    method: str = DOM        # which extractor produced `text`; see the module docstring
    chars: int = 0

    def __post_init__(self) -> None:
        self.chars = len(self.text)


def _dom_text(html: str) -> tuple[str | None, str]:
    """The previous behaviour, kept as the fallback: strip the obvious furniture and take what is left."""
    tree = HTMLParser(html)
    title = tree.css_first("title")
    for tag in BOILERPLATE_TAGS:
        for node in tree.css(tag):
            node.decompose()
    body = tree.body or tree.root
    text = body.text(separator="\n", strip=True) if body else ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return (title.text(strip=True) if title else None), "\n".join(lines)


def main_text(html: str, url: str | None = None, *, min_chars: int = 180) -> Extracted:
    """Extract a page's main content, falling back to a DOM strip when no article is found.

    The guard is relative, not absolute. The failure that matters is trafilatura returning a short fragment — a
    cookie notice, a lone caption — for a page that plainly has more on it, because accepting that would make a
    full page look nearly empty and read downstream as "the content was deleted". So its output is rejected only
    when it falls below both `min_chars` and the length of the DOM text: a genuinely two-line page is not a miss,
    and two lines out of five thousand characters is.
    """
    dom_title, dom_text = _dom_text(html)
    extracted = _trafilatura_text(html, url)
    if extracted and len(extracted) >= min(min_chars, len(dom_text) or min_chars):
        return Extracted(text=extracted, title=dom_title, method=TRAFILATURA)
    return Extracted(text=dom_text, title=dom_title, method=DOM)


def _trafilatura_text(html: str, url: str | None) -> str | None:
    """Trafilatura's view of the page, or None if it declines.

    `include_tables` is on because the pages change detection watches most closely are pricing tables, and
    `favor_recall` because a marketing page is thin prose that the default precision setting discards wholesale.
    No network access: `trafilatura.extract` is given the HTML we already fetched through the SSRF-safe client,
    and `url` is passed for link resolution only.
    """
    try:
        import trafilatura
    except ImportError:          # extraction is an upgrade, never a hard requirement
        return None
    try:
        text = trafilatura.extract(html, url=url, output_format="txt", include_tables=True,
                                   include_comments=False, include_links=False, favor_recall=True)
    except Exception:  # noqa: BLE001 — a page that defeats the parser falls back, it does not fail the job
        return None
    return _drop_repeated_tail(text) if text else None


def _drop_repeated_tail(text: str) -> str:
    """Remove a trailing run of lines that merely repeats the run immediately before it.

    Only the tail is considered and only runs of two lines or more, so a page that genuinely says the same short
    line twice keeps both. The alternative — deduplicating every line — would silently delete real repetition
    such as a price that appears once per plan row.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for k in range(len(lines) // 2, 1, -1):
        if lines[-k:] == lines[-2 * k:-k]:
            return "\n".join(lines[:-k])
    return "\n".join(lines)
