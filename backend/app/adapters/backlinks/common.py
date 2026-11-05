"""Shared shape for backlink providers.

Every adapter normalises to the same row so the rest of the app never learns a vendor's field names:

    {"referring_domain": str, "backlinks": int, "dofollow": int,
     "domain_rating": float|None, "first_seen": date|None, "last_seen": date|None, "example_url": str|None}

Coverage differs between indexes, so the provider key is kept on every stored row and never mixed in a total.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit


def host_only(value: Any) -> str:
    """'https://www.Example.com/a?b' -> 'example.com'. Returns '' for anything unusable."""
    s = str(value or "").strip().lower()
    if not s:
        return ""
    if "://" in s:
        s = urlsplit(s).hostname or ""
    else:
        s = s.split("/")[0]
    return s.removeprefix("www.")[:255]


def as_int(value: Any) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def as_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # drop NaN


def as_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for parse in (lambda t: datetime.fromisoformat(t).date(), lambda t: datetime.strptime(t, "%Y-%m-%d").date()):
        try:
            return parse(text)
        except ValueError:
            continue
    return None


def row(referring_domain: Any, *, backlinks: Any = 0, dofollow: Any = 0, domain_rating: Any = None,
        first_seen: Any = None, last_seen: Any = None, example_url: Any = None) -> dict[str, Any] | None:
    """Build one normalised row, or None when the domain is unusable."""
    host = host_only(referring_domain)
    if not host:
        return None
    links = as_int(backlinks)
    follow = as_int(dofollow)
    return {
        "referring_domain": host,
        "backlinks": links,
        # A provider that does not split follow/nofollow reports 0; never claim more dofollow than total links.
        "dofollow": min(follow, links) if links else follow,
        "domain_rating": as_float(domain_rating),
        "first_seen": as_date(first_seen),
        "last_seen": as_date(last_seen),
        "example_url": (str(example_url)[:2000] or None) if example_url else None,
    }


def dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per referring domain, keeping the entry with the most backlinks."""
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        prev = best.get(r["referring_domain"])
        if prev is None or r["backlinks"] > prev["backlinks"]:
            best[r["referring_domain"]] = r
    return sorted(best.values(), key=lambda r: (-r["backlinks"], r["referring_domain"]))


def link_row(url_from: Any, url_to: Any, *, anchor: Any = None, page_title: Any = None, dofollow: Any = True,
             domain_rating: Any = None, first_seen: Any = None, last_seen: Any = None) -> dict[str, Any] | None:
    """One individual backlink: the page that links, the page it links to, and the clickable text.

    Returns None when the source URL is unusable — a link we cannot point the user at is not worth storing.
    """
    src = str(url_from or "").strip()
    host = host_only(src)
    if not src or not host:
        return None
    return {
        "url_from": src[:2000],
        "url_to": str(url_to or "").strip()[:2000],
        "referring_domain": host,
        "anchor": (str(anchor).strip()[:500] or None) if anchor else None,
        "page_title": (str(page_title).strip()[:500] or None) if page_title else None,
        "dofollow": bool(dofollow),
        "domain_rating": as_float(domain_rating),
        "first_seen": as_date(first_seen),
        "last_seen": as_date(last_seen),
    }


def link_hash(r: dict[str, Any]) -> str:
    """Stable identity for a link: source page + target page + anchor text."""
    import hashlib
    key = f"{r['url_from']}\n{r['url_to']}\n{r.get('anchor') or ''}"
    return hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()


def dedupe_links(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop exact duplicates, keeping document order (providers already sort by importance)."""
    seen: set[str] = set()
    out = []
    for r in rows:
        h = link_hash(r)
        if h not in seen:
            seen.add(h)
            out.append(r)
    return out
