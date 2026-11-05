"""Raven's Semrush Apify Actor — backlink profile totals plus selected links/domains."""
from __future__ import annotations

from typing import Any, ClassVar

import httpx

from app.adapters.backlinks.common import dedupe, dedupe_links, link_row, row
from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)

ACTOR = "pro100chok~semrush-scraper"
API = "https://api.apify.com/v2"


def _item(raw: Any) -> dict[str, Any]:
    if isinstance(raw, list):
        return next((x for x in raw if isinstance(x, dict) and x.get("type") == "domain_overview"),
                    next((x for x in raw if isinstance(x, dict)), {}))
    return raw if isinstance(raw, dict) else {}


class ApifySemrushBacklinksAdapter(ProviderAdapter):
    key: ClassVar[str] = "apify_semrush_backlinks"
    category: ClassVar[str] = "backlinks"
    vendor: ClassVar[str] = "Apify"
    vendor_url: ClassVar[str] = "https://apify.com"
    display_name: ClassVar[str] = "Semrush Backlinks"
    description: ClassVar[str] = ("Semrush profile totals plus up to 80 selected backlinks and 60 selected referring "
                                  "domains from Raven's third-party Apify Actor. Requires a paid Apify account; "
                                  "this is scraped data, not the official Semrush API.")
    docs_url: ClassVar[str] = "https://apify.com/pro100chok/semrush-scraper"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("apify_token", "Apify API token", secret=True, required=True,
                        help="Apify Console → Settings → Integrations → API tokens."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("database", "Semrush database", "select", "worldwide",
                    ["worldwide", "us", "uk", "ca", "au", "ae", "de", "fr", "es", "it", "nl", "in", "sg"],
                    help="Use worldwide for backlinks; backlink lists themselves are not country-specific."),
        ConfigField("backlinks_limit", "Selected backlinks", "number", 80,
                    help="1–80 selected top/new/recent links, not the complete index."),
        ConfigField("referring_domains_limit", "Selected referring domains", "number", 60,
                    help="1–60 selected domains, not the complete index."),
        ConfigField("max_charge_usd", "Maximum charge per sync (USD)", "number", 1.0,
                    help="Apify stops the run rather than exceeding this safety cap."),
        ConfigField("timeout_seconds", "Run timeout (seconds)", "number", 300),
    ]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="backlinks", measurement_type="estimated",
                            features=["referring_domains", "backlinks", "domain_rating", "profile_totals"],
                            notes="Third-party scraped Semrush data; link/domain lists are selected samples.")

    def _token(self) -> str:
        token = str(self.credentials.get("apify_token") or "").strip()
        if not token:
            raise ProviderError("An Apify API token is required")
        return token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}

    def health_check(self) -> HealthResult:
        try:
            resp = httpx.get(f"{API}/users/me", headers=self._headers(), timeout=30)
            if resp.status_code != 200:
                return HealthResult(False, f"Apify rejected that token ({resp.status_code}): {resp.text[:160]}")
            return HealthResult(True, "Apify token accepted. A backlink sync will run the paid Semrush Actor.")
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Apify check failed: {exc}")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return UsageEstimate(requests=1, unit_type="Actor runs",
                             note=f"One paid Actor result, capped at ${float(self.config.get('max_charge_usd') or 1):.2f}")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        target = str(request["target"]).strip()
        body = {
            "mode": "domain", "domains": [target], "database": str(self.config.get("database") or "worldwide"),
            "include_moz": False, "include_organic_keywords": False, "include_backlinks": True,
            "backlinks_limit": max(1, min(int(self.config.get("backlinks_limit") or 80), 80)),
            "include_referring_domains": True,
            "referring_domains_limit": max(1, min(int(self.config.get("referring_domains_limit") or 60), 60)),
            "concurrency": 1,
        }
        params = {"maxItems": 1, "maxTotalChargeUsd": float(self.config.get("max_charge_usd") or 1.0)}
        timeout = max(60, min(int(self.config.get("timeout_seconds") or 300), 300))
        resp = httpx.post(f"{API}/actors/{ACTOR}/run-sync-get-dataset-items", params=params, json=body,
                          headers=self._headers(), timeout=timeout + 15)
        if not 200 <= resp.status_code < 300:
            raise ProviderError(f"Apify Semrush Actor failed ({resp.status_code}): {resp.text[:300]}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderError(f"Apify returned invalid JSON: {resp.text[:200]}") from exc
        item = _item(payload)
        if not item or not item.get("domain"):
            raise ProviderError("The Actor completed but returned no domain record")
        result = CollectResult(raw=payload, meta={"target": target, "provider": self.key, "actor": ACTOR,
                                                  "sampled": True, "input": body})
        self._last_result = result
        return result

    def normalize(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for rec in _item(result.raw).get("referring_domains_list") or []:
            r = row(rec.get("referring_domain"), backlinks=rec.get("backlinks_count"),
                    domain_rating=rec.get("domain_authority_score"), first_seen=rec.get("first_seen"),
                    last_seen=rec.get("last_seen"))
            if r:
                out.append(r)
        return dedupe(out)

    def collect_links(self, request: dict[str, Any]) -> CollectResult:
        # sync_backlinks calls this immediately after collect() on the same instance, so the paid run is reused.
        return getattr(self, "_last_result", None) or self.collect(request)

    def normalize_links(self, result: CollectResult) -> list[dict[str, Any]]:
        out = []
        for rec in _item(result.raw).get("backlinks_list") or []:
            r = link_row(rec.get("source_url"), rec.get("target_url"), anchor=rec.get("anchor"),
                         page_title=rec.get("source_title"), dofollow=not bool(rec.get("nofollow")),
                         domain_rating=rec.get("source_domain_authority_score"),
                         first_seen=rec.get("first_seen"), last_seen=rec.get("last_seen"))
            if r:
                out.append(r)
        return dedupe_links(out)

    def profile_totals(self, result: CollectResult) -> dict[str, Any]:
        item = _item(result.raw)
        return {"authority_score": item.get("authority_score"), "backlinks": item.get("backlinks"),
                "referring_domains": item.get("referring_domains"), "dofollow": item.get("follow_backlinks"),
                "nofollow": item.get("nofollow_backlinks"), "sampled_backlinks": item.get("backlinks_list_count"),
                "sampled_referring_domains": item.get("referring_domains_list_count"), "note": item.get("lists_note")}
