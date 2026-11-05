"""Shared shapes for keyword and SERP providers.

Three row types, one per capability, so the rest of the app never learns a vendor's field names:

  metric_row  — what a keyword is worth:      {keyword, search_volume, difficulty, cpc, competition, intent}
  ranked_row  — what a domain ranks for:      {keyword, position, search_volume, url, traffic, difficulty}
  rank_row    — where we sit for a keyword:   {keyword, position, url, serp_features}

Vendors disagree on volume and difficulty for the same term, so provider_key is stored on every row and numbers
from different providers are never averaged together.
"""
from __future__ import annotations

from typing import Any


def as_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return default


def as_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def clean_keyword(value: Any) -> str:
    return " ".join(str(value or "").split()).lower()[:300]


def metric_row(keyword: Any, *, search_volume: Any = None, difficulty: Any = None, cpc: Any = None,
               competition: Any = None, intent: Any = None) -> dict[str, Any] | None:
    """What a keyword is worth. None when the term itself is unusable."""
    kw = clean_keyword(keyword)
    if not kw:
        return None
    return {
        "keyword": kw,
        "search_volume": as_int(search_volume) if search_volume is not None else None,
        "difficulty": as_float(difficulty),
        "cpc": as_float(cpc),
        "competition": as_float(competition),
        "intent": (str(intent)[:40] or None) if intent else None,
    }


def ranked_row(keyword: Any, position: Any, *, url: Any = None, search_volume: Any = None,
               traffic: Any = None, difficulty: Any = None) -> dict[str, Any] | None:
    """One keyword a domain ranks for. A row without a position tells us nothing, so it is dropped."""
    kw = clean_keyword(keyword)
    pos = as_int(position, default=0)
    if not kw or pos <= 0:
        return None
    return {
        "keyword": kw,
        "position": pos,
        "url": (str(url)[:2000] or None) if url else None,
        "search_volume": as_int(search_volume) if search_volume is not None else None,
        "traffic": as_float(traffic),
        "difficulty": as_float(difficulty),
    }


def rank_row(keyword: Any, *, position: Any = None, url: Any = None,
             serp_features: Any = None) -> dict[str, Any] | None:
    """Where we sit for a tracked keyword. position None means 'checked, not found' — that is a real result."""
    kw = clean_keyword(keyword)
    if not kw:
        return None
    pos = as_int(position, default=0) if position is not None else 0
    features = [str(f)[:60] for f in serp_features] if isinstance(serp_features, (list, tuple)) else []
    return {
        "keyword": kw,
        "position": pos or None,
        "url": (str(url)[:2000] or None) if url else None,
        "serp_features": features,
    }


def best_per_keyword(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per keyword, keeping the best (lowest) position."""
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        prev = best.get(r["keyword"])
        if prev is None or r["position"] < prev["position"]:
            best[r["keyword"]] = r
    return sorted(best.values(), key=lambda r: (r["position"], r["keyword"]))


def dedupe_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per keyword, preferring the entry that actually carries a volume."""
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        prev = best.get(r["keyword"])
        if prev is None or (prev["search_volume"] is None and r["search_volume"] is not None):
            best[r["keyword"]] = r
    return list(best.values())
