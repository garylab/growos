"""Shared SerpApi transport.

One account and one key serve three unrelated jobs in GrowOS — AI answer surfaces (GEO), live SERP positions and
keyword discovery (SEO), and JavaScript rendering for page inspection — so the HTTP call, the error mapping and the
quota report live here and each adapter only decides which `engine` to ask for.

Billing is uniform: one successful search is one credit on every engine, and cached repeats are free. Caching is
therefore left at SerpApi's default (`no_cache` unset) — a SERP from a few minutes ago is the same SERP, and paying
twice for it buys nothing. `json_restrictor` is passed through where an adapter only needs a few fields, because the
responses are large and the worker holds them in memory.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.adapters.base import ProviderError

SEARCH_URL = "https://serpapi.com/search.json"
RAW_SEARCH_URL = "https://serpapi.com/search"
ACCOUNT_URL = "https://serpapi.com/account.json"


class SerpApiClient:
    """Thin wrapper over the single /search endpoint every SerpApi engine is served from."""

    def __init__(self, api_key: str | None, *, timeout: float = 90.0):
        if not api_key:
            raise ProviderError("A SerpApi API key is required (serpapi.com → Dashboard → Your Private API Key)")
        self.api_key = api_key
        self.timeout = timeout

    # SerpApi reports failures three different ways: an HTTP status, a 200 carrying {"error": …}, and a
    # search_metadata.status of "Error". All three mean the same thing to a caller, so they collapse here.
    def _check(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 401:
            raise ProviderError("SerpApi rejected that API key (401)")
        if resp.status_code == 429:
            raise ProviderError("SerpApi rate limit or monthly quota reached (429) — check your plan's searches left")
        if resp.status_code != 200:
            raise ProviderError(f"SerpApi returned HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderError(f"SerpApi returned a non-JSON response: {resp.text[:200]}") from exc
        if isinstance(payload, dict) and payload.get("error"):
            raise ProviderError(f"SerpApi: {str(payload['error'])[:300]}")
        return payload

    def search(self, params: dict[str, Any]) -> dict[str, Any]:
        """One billed search. `params` must carry `engine`; empty values are dropped so defaults apply."""
        query = {k: v for k, v in params.items() if v not in (None, "", [])}
        query["api_key"] = self.api_key
        try:
            resp = httpx.get(SEARCH_URL, params=query, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise ProviderError(f"SerpApi request failed: {exc}") from exc
        return self._check(resp)

    def fetch_text(self, params: dict[str, Any], output: str) -> str:
        """A search asking for `output=html|md` instead of JSON — used by the Extract engine."""
        query = {k: v for k, v in params.items() if v not in (None, "", [])}
        query.update({"api_key": self.api_key, "output": output})
        try:
            resp = httpx.get(RAW_SEARCH_URL, params=query, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise ProviderError(f"SerpApi request failed: {exc}") from exc
        if resp.status_code == 401:
            raise ProviderError("SerpApi rejected that API key (401)")
        if resp.status_code != 200:
            raise ProviderError(f"SerpApi returned HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.text

    def account(self) -> dict[str, Any]:
        """Plan and remaining quota. Free of charge and not counted against the monthly allowance."""
        try:
            resp = httpx.get(ACCOUNT_URL, params={"api_key": self.api_key}, timeout=30)
        except httpx.HTTPError as exc:
            raise ProviderError(f"SerpApi account check failed: {exc}") from exc
        return self._check(resp)


def account_summary(account: dict[str, Any]) -> str:
    """Human-readable quota line for a health check."""
    plan = account.get("plan_name") or "unknown plan"
    left = account.get("total_searches_left")
    per_month = account.get("searches_per_month")
    used = account.get("this_month_usage")
    parts = [f"SerpApi reachable on {plan}"]
    if left is not None:
        parts.append(f"{left} searches left")
    if used is not None and per_month is not None:
        parts.append(f"{used}/{per_month} used this month")
    return " — ".join([parts[0], ", ".join(parts[1:])]) if len(parts) > 1 else parts[0]


def quota_details(account: dict[str, Any]) -> dict[str, Any]:
    keep = ("plan_name", "searches_per_month", "plan_searches_left", "extra_credits", "total_searches_left",
            "this_month_usage", "account_rate_limit_per_hour")
    return {k: account.get(k) for k in keep if account.get(k) is not None}


# --------------------------------------------------------------------------- AI blocks
# SerpApi returns the same `text_blocks` / `references` shape for every AI surface — the inline `ai_overview` on a
# Google SERP, the dedicated AI Overview engine, AI Mode and Bing Copilot — so both the GEO adapter (which wants the
# answer) and the SERP adapter (which only wants to know who is cited) parse it with these.
def flatten_text_blocks(blocks: Any, depth: int = 0) -> list[str]:
    """Answer prose in reading order. Handles paragraph, list and the nested `expandable` block."""
    if depth > 6 or not isinstance(blocks, list):
        return []
    out: list[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if title := b.get("title"):
            out.append(str(title))
        if snippet := b.get("snippet"):
            out.append(str(snippet))
        for key in ("list", "text_blocks"):
            if b.get(key):
                out.extend(flatten_text_blocks(b[key], depth + 1))
    return [s for s in (p.strip() for p in out) if s]


def reference_links(references: Any) -> list[dict[str, str]]:
    """Cited sources as {link, title, source}. Entries without a link are useless as citations and are dropped."""
    out = []
    for r in references if isinstance(references, list) else []:
        if isinstance(r, dict) and r.get("link"):
            out.append({"link": str(r["link"]), "title": str(r.get("title") or "")[:500],
                        "source": str(r.get("source") or "")[:200]})
    return out
