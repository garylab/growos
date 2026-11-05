"""Shared helpers for brand sources."""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

# "6d ago", "2 days ago", "Streamed 3 weeks ago", "1 year ago" — the only date YouTube search results carry.
RELATIVE_RE = re.compile(r"(\d+)\s*(s|sec|second|m|min|minute|h|hr|hour|d|day|w|wk|week|mo|month|y|yr|year)s?\b", re.I)
UNIT_SECONDS = {"s": 1, "sec": 1, "second": 1, "m": 60, "min": 60, "minute": 60, "h": 3600, "hr": 3600, "hour": 3600,
                "d": 86400, "day": 86400, "w": 604800, "wk": 604800, "week": 604800,
                "mo": 2_592_000, "month": 2_592_000, "y": 31_536_000, "yr": 31_536_000, "year": 31_536_000}


def parse_relative_date(value: str | None, *, now: datetime | None = None) -> datetime | None:
    """Turn "3 weeks ago" into a timestamp, or None when there is nothing to read.

    Deliberately approximate, because the input is: YouTube reports an age, not a date, and "1 year ago" covers
    twelve months. The result is good enough to sort and filter a mentions feed by recency and should not be read
    as a publication date. An absolute ISO date is passed through unchanged when a provider happens to send one.
    """
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    match = RELATIVE_RE.search(text)
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2).lower()
    seconds = UNIT_SECONDS.get(unit)
    if not seconds:
        return None
    return (now or datetime.now(UTC)) - timedelta(seconds=amount * seconds)


def extracted_int(value: object) -> int | None:
    """A count from either `extracted_views: 12345` or `views: "12K views"`."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip().lower()
    if not text:
        return None
    match = re.search(r"([\d.,]+)\s*([kmb])?", text)
    if not match:
        return None
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return int(number * {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(match.group(2) or "", 1))
