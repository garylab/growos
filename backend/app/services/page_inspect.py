"""On-demand page inspection for site-level findings.

SiteOne reports aggregates such as "434 page(s) do not support Brotli" without saying which pages or where the
problem is. These inspectors fetch the affected pages through the SSRF-safe client and return concrete evidence:
the URL, what is wrong and the exact element or text involved.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from selectolax.parser import HTMLParser

from app.core.safe_http import UnsafeURLError, safe_get
from app.services.page_signals import Renderer, looks_unrendered

PHONE_RE = re.compile(r"(?<![\w/])(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{1,4}\)[\s.-]?)?\d{2,4}[\s.-]\d{2,4}(?:[\s.-]\d{2,4})?(?![\w/])")
INTERACTIVE = ("a", "button", "label")


@dataclass
class PageIssue:
    url: str
    detail: str
    element: str | None = None
    snippet: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------- inspectors
def _missing_h1(tree: HTMLParser, url: str, _resp) -> list[PageIssue]:
    return [] if tree.css("h1") else [PageIssue(url, "No <h1> heading on the page",
                                                snippet=(tree.css_first("title").text(strip=True) if tree.css_first("title") else None))]


def _skipped_heading_levels(tree: HTMLParser, url: str, _resp) -> list[PageIssue]:
    heads = [(int(n.tag[1]), n.text(strip=True)[:70]) for n in tree.css("h1,h2,h3,h4,h5,h6")]
    out: list[PageIssue] = []
    prev = 0
    for level, text in heads:
        if prev and level > prev + 1:
            out.append(PageIssue(url, f"Heading jumps from H{prev} to H{level} (H{prev + 1} is missing)",
                                 element=f"h{level}", snippet=text,
                                 extra={"sequence": " → ".join(f"H{l}" for l, _ in heads[:12])}))
        prev = level
    return out


def _non_clickable_phone(tree: HTMLParser, url: str, _resp) -> list[PageIssue]:
    linked = {a.attributes.get("href", "")[4:].strip() for a in tree.css('a[href^="tel:"]')}
    linked_digits = {re.sub(r"\D", "", p) for p in linked}
    out: list[PageIssue] = []
    seen: set[str] = set()
    for node in tree.css("p, span, div, li, td, address, footer"):
        if node.css("a, button"):
            continue
        text = node.text(separator=" ", strip=True)
        if not text or len(text) > 400:
            continue
        for m in PHONE_RE.finditer(text):
            raw = m.group(0).strip()
            digits = re.sub(r"\D", "", raw)
            if len(digits) < 7 or digits in linked_digits or digits in seen:
                continue
            seen.add(digits)
            out.append(PageIssue(url, "Phone number shown as plain text — not tappable on mobile",
                                 element=f"<{node.tag}>", snippet=raw,
                                 extra={"fix": f'<a href="tel:+{digits}">{raw}</a>'}))
    return out[:10]


def _form_labels(tree: HTMLParser, url: str, _resp) -> list[PageIssue]:
    labelled = {n.attributes.get("for") for n in tree.css("label[for]") if n.attributes.get("for")}
    out: list[PageIssue] = []
    for n in tree.css("input, select, textarea"):
        itype = (n.attributes.get("type") or "text").lower()
        if itype in ("hidden", "submit", "button", "image", "reset"):
            continue
        has_label = (n.attributes.get("id") in labelled) or n.attributes.get("aria-label") or n.attributes.get("aria-labelledby") or n.attributes.get("title")
        if not has_label:
            ident = n.attributes.get("name") or n.attributes.get("id") or n.attributes.get("placeholder") or "(unnamed)"
            out.append(PageIssue(url, "Form field has no label a screen reader can read",
                                 element=f"<{n.tag} type={itype}>", snippet=str(ident)[:60],
                                 extra={"fix": f'<label for="{n.attributes.get("id") or ident}">…</label> or aria-label="…"'}))
    return out[:10]


def _main_landmark(tree: HTMLParser, url: str, _resp) -> list[PageIssue]:
    if tree.css("main") or tree.css('[role="main"]'):
        return []
    return [PageIssue(url, "No <main> landmark — screen readers cannot skip to the content",
                      extra={"fix": "Wrap the primary content in <main> … </main> (one per page)"})]


def _image_alt(tree: HTMLParser, url: str, _resp) -> list[PageIssue]:
    out = []
    for n in tree.css("img"):
        # selectolax reports alt="" as None, so distinguish a missing attribute from an intentionally empty one.
        if "alt" not in n.attributes and not n.attributes.get("aria-hidden") and (n.attributes.get("role") or "") != "presentation":
            out.append(PageIssue(url, "Image has no alt attribute", element="<img>",
                                 snippet=(n.attributes.get("src") or "")[:120]))
    return out[:10]


def _compression(_tree, url: str, resp) -> list[PageIssue]:
    enc = (resp.headers.get("content-encoding") or "").lower() if resp else ""
    if "br" in enc:
        return []
    return [PageIssue(url, f"Served as {enc or 'uncompressed'} — Brotli is not enabled for this page",
                      extra={"content_encoding": enc or "(none)", "vary": resp.headers.get("vary") if resp else None,
                             "fix": "Enable Brotli on the CDN/web server and send Vary: Accept-Encoding"})]


# `dom` marks an inspector that reads the document itself, so it can be served from rendered HTML. The compression
# check is about how the bytes arrived, which a third-party renderer has by definition changed — it stays on the
# direct fetch.
INSPECTORS: dict[str, dict[str, Any]] = {
    "missing_h1": {"fn": _missing_h1, "label": "Pages without an H1", "headers": None, "dom": True},
    "skipped_heading_levels": {"fn": _skipped_heading_levels, "label": "Skipped heading levels", "headers": None, "dom": True},
    "non_clickable_phone": {"fn": _non_clickable_phone, "label": "Phone numbers that are not clickable", "headers": None, "dom": True},
    "form_labels": {"fn": _form_labels, "label": "Form fields without labels", "headers": None, "dom": True},
    "main_landmark": {"fn": _main_landmark, "label": "Pages without a main landmark", "headers": None, "dom": True},
    "image_alt": {"fn": _image_alt, "label": "Images without alt text", "headers": None, "dom": True},
    "compression": {"fn": _compression, "label": "Pages without Brotli compression", "headers": {"Accept-Encoding": "br, gzip"}, "dom": False},
}

# Site-level finding codes (SiteOne summary items) → the inspector that explains them page by page.
CODE_TO_INSPECTOR = {
    "site_pages_without_h1": "missing_h1",
    "missing_h1": "missing_h1",
    "site_pages_with_skipped_heading_levels": "skipped_heading_levels",
    "heading_structure": "skipped_heading_levels",
    "site_pages_with_non_clickable_phone_numbers": "non_clickable_phone",
    "site_pages_without_form_labels": "form_labels",
    "site_pages_without_main_landmark": "main_landmark",
    "site_missing_image_alt_attributes": "image_alt",
    "site_brotli_support": "compression",
}


def inspect_pages(urls: list[str], inspector: str, renderer: Renderer | None = None,
                  render_budget: int = 0) -> dict[str, Any]:
    """Run one inspector over a sample of pages, re-fetched live.

    `renderer` is a paid fallback for pages that arrive as an app shell; `render_budget` caps how many of them one
    call may spend, because a whole client-rendered site would otherwise be rendered page by page. Only DOM-reading
    inspectors use it — a rendered page says nothing about how the original bytes were compressed.
    """
    cfg = INSPECTORS.get(inspector)
    if cfg is None:
        raise ValueError(f"Unknown inspector '{inspector}'")
    fn: Callable = cfg["fn"]
    issues: list[PageIssue] = []
    errors: list[dict[str, str]] = []
    clean = 0
    rendered = 0
    skipped_unrendered = 0
    for url in urls:
        try:
            resp = safe_get(url, timeout=20, headers=cfg["headers"] or None)
        except (UnsafeURLError, Exception) as exc:  # noqa: BLE001
            errors.append({"url": url, "error": str(exc)[:200]})
            continue
        if resp.status_code != 200 or "html" not in resp.headers.get("content-type", ""):
            errors.append({"url": url, "error": f"HTTP {resp.status_code}"})
            continue
        html = resp.text
        if cfg["dom"] and looks_unrendered(html):
            if renderer is not None and rendered < render_budget:
                try:
                    html = renderer(resp.final_url)
                    rendered += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append({"url": url, "error": f"render failed: {str(exc)[:160]}"})
                    continue
            else:
                # Reporting "no H1" on a shell we never rendered would be a finding about our own fetcher.
                skipped_unrendered += 1
                continue
        found = fn(HTMLParser(html), url, resp)
        if found:
            issues.extend(found)
        else:
            clean += 1
    return {"inspector": inspector, "label": cfg["label"], "checked": len(urls), "pages_with_issues": len({i.url for i in issues}),
            "pages_clean": clean, "issues": [i.__dict__ for i in issues[:200]], "errors": errors,
            "pages_rendered": rendered or None,
            "pages_skipped_unrendered": skipped_unrendered or None}
