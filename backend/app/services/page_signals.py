"""Brand / conversion / technical signals extracted from a page's HTML.

SiteOne's extra-column xpath only sees the document body, so head-level facts (canonical, robots meta, JSON-LD,
Open Graph) cannot come from the crawler. We fetch a small set of key pages ourselves through the SSRF-safe client
and parse them with selectolax. Everything here is observed evidence: a signal is only reported when the page was
actually fetched and parsed (`checked: true`).
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser

from app.core.safe_http import UnsafeURLError, safe_get

# A renderer takes a URL and returns resolved HTML. Injected rather than imported so these extractors stay free of
# database and provider concerns, and remain testable with a two-line stub.
Renderer = Callable[[str], str]

SOCIAL_DOMAINS = ("linkedin.com", "x.com", "twitter.com", "youtube.com", "facebook.com", "instagram.com",
                  "tiktok.com", "github.com", "threads.net", "bsky.app", "pinterest.com")
FREE_EMAIL_DOMAINS = ("gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "aol.com",
                      "icloud.com", "qq.com", "163.com", "126.com", "mail.ru", "yandex.ru", "proton.me", "protonmail.com",
                      "gmx.com", "zoho.com", "yeah.net", "foxmail.com")
CHAT_PATTERNS = re.compile(r"(wa\.me|api\.whatsapp\.com|web\.whatsapp\.com|t\.me|m\.me|messenger\.com)", re.I)

# Analytics / product-analytics tags we can recognise in page HTML.
ANALYTICS_PATTERNS = {
    "google_analytics": r"googletagmanager\.com/gtag/js|gtag\(|google-analytics\.com/analytics\.js|googletagmanager\.com/gtm\.js",
    "plausible": r"plausible\.io/js", "umami": r"umami[^\"']*\.js|data-website-id",
    "posthog": r"posthog\.(com|init)", "matomo": r"matomo\.(js|php)|piwik",
    "fathom": r"usefathom\.com", "clarity": r"clarity\.ms", "hotjar": r"hotjar\.com",
    "mixpanel": r"mixpanel", "amplitude": r"amplitude\.com", "segment": r"segment\.(com|io)/analytics",
    "meta_pixel": r"connect\.facebook\.net[^\"']*fbevents", "linkedin_insight": r"snap\.licdn\.com",
}
EMAIL_CAPTURE_HINTS = re.compile(r"(newsletter|subscribe|sign ?up for|join .{0,20}list|get updates|free trial|waitlist|early access)", re.I)

# Emails printed as visible text rather than wrapped in a mailto: link.
EMAIL_RE = re.compile(r"[a-z0-9][a-z0-9._%+-]*@[a-z0-9.-]+\.[a-z]{2,24}", re.I)
# File extensions that otherwise look like a TLD, so retina asset names (logo@2x.png) are not mistaken for addresses.
_ASSET_EXTS = frozenset(("png", "jpg", "jpeg", "gif", "svg", "webp", "avif", "ico", "css", "js", "mjs",
                         "json", "map", "html", "htm", "woff", "woff2", "ttf", "eot", "pdf", "mp4", "webm"))


def _decode_cfemail(hex_str: str) -> str | None:
    """Reverse Cloudflare's email obfuscation (`data-cfemail` / `/cdn-cgi/l/email-protection#<hex>`).

    The first byte is an XOR key; every following byte XOR'd with it yields the original ASCII. Cloudflare rewrites
    on-page addresses into this form and decodes them in the browser, so without this an otherwise-public contact
    email is invisible to a static fetch.
    """
    try:
        raw = bytes.fromhex(hex_str.strip())
    except ValueError:
        return None
    if len(raw) < 2:
        return None
    key = raw[0]
    addr = "".join(chr(b ^ key) for b in raw[1:])
    return addr.lower() if "@" in addr and "." in addr.split("@")[-1] else None

# Elements a client-side framework mounts into. Empty in the HTML we receive, filled in by the browser.
SPA_MOUNTS = ("#root", "#app", "#__next", "#__nuxt", "#q-app", "[data-reactroot]", "[data-server-rendered]")


def serves_brotli(url: str) -> bool | None:
    """Whether the server returns Brotli when a client explicitly asks for it. None if the check could not run.

    SiteOne's crawler (and our default fetch) do not advertise `Accept-Encoding: br`, so a site that serves Brotli
    — e.g. anything behind Cloudflare, where it is on by default — is wrongly reported as not supporting it. We ask
    for it directly and read the response's content-encoding. The body may come back still-encoded (httpx has no
    brotli decoder in this image), but the header is all we need, and safe_get passes the raw bytes through.
    """
    try:
        resp = safe_get(url, timeout=15, headers={"Accept-Encoding": "br"})
    except Exception:  # noqa: BLE001 — a failed probe must never break signal collection
        return None
    return resp.headers.get("content-encoding", "").lower() == "br"


def serves_image_format(image_url: str, mime: str) -> bool | None:
    """Whether the server returns `mime` (e.g. image/webp) for an image when the client asks for it. None on error.

    Like the Brotli check, SiteOne reports a site as lacking modern image formats when its probe does not negotiate
    them. We request the page's own sample image with an explicit Accept and read the content-type; an image
    optimizer (Next.js, Cloudflare Polish, Cloudinary, imgix) answers with the negotiated format when it supports it.
    """
    try:
        resp = safe_get(image_url, timeout=15, headers={"Accept": f"{mime},image/*"})
    except Exception:  # noqa: BLE001 — a failed probe must never break signal collection
        return None
    if resp.status_code != 200:
        return None
    return resp.headers.get("content-type", "").split(";")[0].strip().lower() == mime


def looks_unrendered(html: str) -> bool:
    """True when a page arrived as an app shell: markup present, content absent.

    Deliberately hard to trigger. A true answer has two consequences — the page is sent to a paid renderer, and if
    no renderer is connected it is dropped from inspection instead of being reported as broken — so a false
    positive would quietly hide real findings. A thin-but-real page (a sparse contact page carrying an analytics
    tag) must therefore come out false, which rules out "short text plus a script" as the test: almost every page
    on the web has a script.

    What actually distinguishes a shell is that there is nothing in the body to look at. So either a framework
    mount element is present and empty, or the body has no content elements at all and nearly no text. Script and
    style text is stripped before measuring, because selectolax counts it as body text — an inline bundle would
    otherwise make the emptiest page in the world look full.
    """
    if not html or len(html) > 400_000:        # a document that large has already rendered something
        return False
    tree = HTMLParser(html)
    if tree.body is None:
        return False
    for sel in SPA_MOUNTS:
        node = tree.css_first(sel)
        if node is not None and not (node.text(strip=True) or "").strip() and not node.css("img,svg,iframe"):
            return True
    if tree.body.css("h1,h2,h3,h4,h5,h6,p,li,article,img,table,input"):
        return False
    tree.strip_tags(["script", "style", "noscript", "template"])
    text = " ".join((tree.body.text(separator=" ") or "").split())
    return len(text) < 400


def extract_signals(html: str, page_url: str) -> dict[str, Any]:
    tree = HTMLParser(html)
    head_meta: dict[str, str] = {}
    for n in tree.css("meta"):
        key = (n.attributes.get("property") or n.attributes.get("name") or "").lower()
        if key and n.attributes.get("content"):
            head_meta.setdefault(key, n.attributes["content"])

    canonical = None
    for n in tree.css("link[rel]"):
        if "canonical" in (n.attributes.get("rel") or "").lower() and n.attributes.get("href"):
            canonical = urljoin(page_url, n.attributes["href"])
            break

    jsonld_types: list[str] = []
    for n in tree.css('script[type="application/ld+json"]'):
        try:
            payload = json.loads(n.text(strip=True) or "{}")
        except ValueError:
            jsonld_types.append("invalid-json")
            continue
        for obj in _iter_ld(payload):
            t = obj.get("@type")
            if isinstance(t, list):
                jsonld_types.extend(str(x) for x in t)
            elif t:
                jsonld_types.append(str(t))

    chat, tel, mailto, social = None, None, None, []
    emails: list[str] = []
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href:
            continue
        low = href.lower()
        if chat is None and CHAT_PATTERNS.search(low):
            chat = href
        elif low.startswith("tel:") and tel is None:
            tel = href
        elif low.startswith("mailto:"):
            if mailto is None:
                mailto = href
            addr = href[7:].split("?")[0].strip().lower()
            if "@" in addr and addr not in emails:
                emails.append(addr)
        elif "/cdn-cgi/l/email-protection#" in low:
            decoded = _decode_cfemail(href.split("#", 1)[1])
            if decoded and decoded not in emails:
                if mailto is None:
                    mailto = f"mailto:{decoded}"
                emails.append(decoded)
        else:
            host = (urlsplit(href).hostname or "").lower().removeprefix("www.")
            if host and any(host == d or host.endswith("." + d) for d in SOCIAL_DOMAINS) and href not in social:
                social.append(href)

    # --- logo / visual identity
    site_host = (urlsplit(page_url).hostname or "").lower().removeprefix("www.")
    icons = [n.attributes.get("href") for n in tree.css("link[rel]")
             if "icon" in (n.attributes.get("rel") or "").lower() and n.attributes.get("href")]
    logo_img = None
    for n in tree.css("header img, nav img, img"):
        blob = " ".join(filter(None, [n.attributes.get("class"), n.attributes.get("id"), n.attributes.get("alt"),
                                      n.attributes.get("src")])).lower()
        if "logo" in blob or "brand" in blob:
            logo_img = urljoin(page_url, n.attributes.get("src") or n.attributes.get("data-src") or "")
            break
    header_svg = bool(tree.css("header svg, nav svg"))
    # A representative image to probe for modern-format support. Prefer what the page actually requests — an
    # optimizer URL (/_next/image, Cloudinary f_auto, imgix) negotiates format; a raw .svg or data: URI cannot.
    sample_image = None
    for n in tree.css("img"):
        src = (n.attributes.get("src") or n.attributes.get("data-src") or "").strip()
        if not src or src.startswith("data:"):
            continue
        resolved = urljoin(page_url, src)
        if resolved.lower().split("?")[0].endswith(".svg"):
            continue
        sample_image = resolved
        break
    ld_logo = None
    for obj in _iter_ld_all(tree):
        lg = obj.get("logo")
        if isinstance(lg, str):
            ld_logo = lg
        elif isinstance(lg, dict) and lg.get("url"):
            ld_logo = lg["url"]
        if ld_logo:
            break

    # --- email addresses that are not mailto: links
    body_text = tree.body.text(separator=" ", strip=True)[:20000] if tree.body else ""
    # Cloudflare-obfuscated spans (the anchor-less form, decoded in the href loop above when wrapped in a link).
    for span in tree.css(".__cf_email__"):
        decoded = _decode_cfemail(span.attributes.get("data-cfemail") or "")
        if decoded and decoded not in emails:
            emails.append(decoded)
    # Addresses printed as plain visible text ("reach us at hello@brand.com"). Body text only, so we skip emails
    # buried in scripts, tracking DSNs or JSON blobs.
    for addr in EMAIL_RE.findall(body_text):
        addr = addr.lower()
        if addr.rsplit(".", 1)[-1] not in _ASSET_EXTS and addr not in emails:
            emails.append(addr)

    # --- email on the company's own domain vs a free provider
    own_domain_emails = [e for e in emails if e.split("@")[-1] in (site_host, f"www.{site_host}") or e.split("@")[-1].endswith("." + site_host)]
    free_emails = [e for e in emails if e.split("@")[-1] in FREE_EMAIL_DOMAINS]

    # --- hreflang (international SEO)
    hreflangs = sorted({(n.attributes.get("hreflang") or "").lower() for n in tree.css("link[hreflang]") if n.attributes.get("hreflang")})

    # --- analytics / conversion tracking
    analytics = sorted({name for name, pat in ANALYTICS_PATTERNS.items() if re.search(pat, html, re.I)})

    # --- email capture (newsletter / waitlist / trial signup)
    email_input = bool(tree.css('input[type="email"]')) or any(
        "email" in ((n.attributes.get("name") or "") + (n.attributes.get("id") or "") + (n.attributes.get("placeholder") or "")).lower()
        for n in tree.css("input"))
    email_capture = email_input and bool(EMAIL_CAPTURE_HINTS.search(body_text))

    # --- physical presence (Google Business Profile relevance)
    address = None
    for obj in _iter_ld_all(tree):
        addr = obj.get("address")
        if isinstance(addr, dict):
            address = ", ".join(str(addr[k]) for k in ("streetAddress", "addressLocality", "addressRegion", "addressCountry") if addr.get(k)) or None
        elif isinstance(addr, str):
            address = addr
        if address:
            break

    robots = (head_meta.get("robots") or "").lower()
    return {
        "checked": True,
        "canonical": canonical,
        "robots": robots or None,
        "noindex": "noindex" in robots,
        "jsonld_types": sorted(set(jsonld_types)),
        "has_organization_schema": any(t in ("Organization", "Corporation", "LocalBusiness", "WebSite") for t in jsonld_types),
        "og_title": head_meta.get("og:title"),
        "og_image": head_meta.get("og:image"),
        "twitter_card": head_meta.get("twitter:card"),
        "chat_link": chat,
        "tel": tel,
        "mailto": mailto,
        "social_links": social[:12],
        "has_form": bool(tree.css("form")),
        "emails": emails[:10],
        "own_domain_emails": own_domain_emails[:5],
        "free_emails": free_emails[:5],
        "logo_img": logo_img,
        "sample_image": sample_image,
        "logo_in_schema": ld_logo,
        "favicon": urljoin(page_url, icons[0]) if icons else None,
        "has_logo": bool(logo_img or ld_logo or header_svg),
        "header_svg_logo": header_svg,
        "hreflang": hreflangs,
        "analytics": analytics,
        "email_capture": email_capture,
        "address": address,
        "has_local_schema": any(t in ("LocalBusiness", "Store", "Restaurant", "ProfessionalService") for t in jsonld_types),
    }


def _iter_ld_all(tree: HTMLParser):
    for n in tree.css('script[type="application/ld+json"]'):
        try:
            payload = json.loads(n.text(strip=True) or "{}")
        except ValueError:
            continue
        yield from _iter_ld(payload)


def _iter_ld(payload: Any):
    if isinstance(payload, dict):
        if "@graph" in payload and isinstance(payload["@graph"], list):
            for item in payload["@graph"]:
                yield from _iter_ld(item)
        else:
            yield payload
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_ld(item)


def fetch_signals(url: str, renderer: Renderer | None = None) -> dict[str, Any]:
    """Fetch one page safely and extract its signals. Returns {'checked': False, 'error': …} on failure.

    `renderer` is an optional paid fallback (SerpApi Extract) used only when the page came back as an app shell.
    Every signal here is a head- or body-level fact a framework writes after first paint, so on a client-rendered
    site the direct fetch does not report "no canonical, no H1, no schema" — it reports nothing at all, which the
    audit would otherwise present as a pile of real problems.
    """
    try:
        resp = safe_get(url, timeout=20)
    except (UnsafeURLError, Exception) as exc:  # noqa: BLE001
        return {"checked": False, "error": str(exc)[:300]}
    if resp.status_code != 200 or "html" not in resp.headers.get("content-type", ""):
        return {"checked": False, "error": f"HTTP {resp.status_code}"}
    html, rendered = resp.text, False
    if renderer is not None and looks_unrendered(html):
        try:
            html, rendered = renderer(resp.final_url), True
        except Exception as exc:  # noqa: BLE001 — the shell is still better evidence than no evidence
            sig = extract_signals(resp.text, resp.final_url)
            sig.update({"fetched_url": resp.final_url, "unrendered": True, "render_error": str(exc)[:200]})
            return sig
    sig = extract_signals(html, resp.final_url)
    sig["fetched_url"] = resp.final_url
    if rendered:
        sig["rendered"] = True
    elif renderer is None and looks_unrendered(resp.text):
        # Say so rather than silently reporting an empty page as a badly built one.
        sig["unrendered"] = True
    return sig
