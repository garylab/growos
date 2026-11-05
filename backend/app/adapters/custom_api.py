"""One custom JSON endpoint, filed under whichever job it was configured for.

A real vendor's capabilities are a fact about its API: DataForSEO prices keywords whether you want it to or not. A
custom endpoint is the opposite — it is whatever you point it at — so here the capability is a choice, and it
decides three things at once: which fields the form asks for, which category the connection is filed under, and
therefore which collection task picks it up.

That is why this replaced two separate providers. "Custom source" and "Custom backlinks API" were the same idea
twice, sharing a URL, a secret, a path to the list and a block of field mappings, and differing only in what the
rows meant at the end. Now there is one provider with a capability switch.

The two jobs' implementations are unchanged and still live in their own modules — this delegates to them rather
than reimplementing their parsing, so the mapping behaviour that existing connections rely on is exactly the
behaviour that was already tested.
"""
from __future__ import annotations

from typing import Any, ClassVar

from app.adapters.backlinks.custom_backlinks import CustomBacklinksAdapter
from app.adapters.base import (Capabilities, CollectResult, ConfigField, CredentialField, HealthResult,
                               ProviderAdapter, ProviderError, UsageEstimate)
from app.adapters.brand.custom_source import CustomSourceAdapter

# capability -> (category it is filed under, what it can do, which implementation runs it)
MODES: dict[str, dict[str, Any]] = {
    "mentions": {
        "category": "brand",
        "features": ["mentions", "engagement"],
        "impl": CustomSourceAdapter,
        "label": "Brand & competitor mentions",
    },
    "referring_domains": {
        "category": "backlinks",
        "features": ["referring_domains", "backlinks"],
        "impl": CustomBacklinksAdapter,
        "label": "Backlinks & referring domains",
    },
}
DEFAULT_MODE = "mentions"

_MENTIONS = {"show_if": {"capability": ["mentions"]}}
_BACKLINKS = {"show_if": {"capability": ["referring_domains"]}}


class CustomAPIAdapter(ProviderAdapter):
    # The key is unchanged from the brand-only provider this grew out of, so connections created before the merge
    # keep working untouched: a stored config with no `capability` picks up the default through the normal
    # field-default merge, and the default is the job those connections were already doing.
    key: ClassVar[str] = "custom_source"
    category: ClassVar[str] = "brand"
    vendor: ClassVar[str] = "Custom JSON API"
    display_name: ClassVar[str] = "Custom JSON API"
    description: ClassVar[str] = ("Point GrowOS at any JSON HTTP endpoint — an Apify dataset, a RapidAPI endpoint, "
                                  "your own aggregator — and map its fields. Choose what the endpoint returns and "
                                  "the form asks for the rest. You are responsible for the source's terms.")
    docs_url: ClassVar[str] = ""
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_key", "API key / token", secret=True, required=False,
                        help="Optional secret. Use {api_key} in the URL or headers to inject it (kept encrypted)."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("capability", "This endpoint returns", "select", DEFAULT_MODE, list(MODES),
                    help="What the response contains. This decides which fields are asked for below and which job "
                         "uses the connection — mentions feed brand monitoring, referring domains feed backlinks."),
        # ---- shared transport
        ConfigField("request_url", "Request URL", "string", "",
                    help="Use {api_key} for the secret. For mentions, {query} is the search term (URL-encoded); "
                         "for referring domains, {target} is the site being checked. "
                         "e.g. https://api.example.com/search?q={query}&key={api_key}"),
        ConfigField("items_path", "Path to the list of items", "string", "",
                    help="Dotted path to the array in the response, e.g. 'data' for an Apify dataset or "
                         "'data.refdomains'. Leave blank if the response is itself an array."),
        ConfigField("timeout_seconds", "Request timeout (seconds)", "number", 30,
                    help="Raise this for endpoints that run a scrape on demand — an Apify run-sync URL can take "
                         "60-120s."),
        # ---- mentions
        ConfigField("method", "Method", "select", "GET", ["GET", "POST"], **_MENTIONS),
        ConfigField("headers_json", "Headers (JSON)", "string", "",
                    help='Optional. e.g. {"X-RapidAPI-Key": "{api_key}", "X-RapidAPI-Host": "example.p.rapidapi.com"}',
                    **_MENTIONS),
        ConfigField("body_template", "POST body (JSON, for POST)", "string", "",
                    help='Use {query}. e.g. {"query": "{query}", "count": 25}', **_MENTIONS),
        ConfigField("map_id", "Field: id", "string", "id", **_MENTIONS),
        ConfigField("map_url", "Field: post URL", "string", "url", **_MENTIONS),
        ConfigField("map_text", "Field: text/content", "string", "text", **_MENTIONS),
        ConfigField("map_author", "Field: author", "string", "author", **_MENTIONS),
        ConfigField("map_published", "Field: published time", "string", "created_at", **_MENTIONS),
        ConfigField("map_language", "Field: language", "string", "lang", **_MENTIONS),
        ConfigField("map_likes", "Field: likes (optional)", "string", "", **_MENTIONS),
        ConfigField("map_reposts", "Field: reposts (optional)", "string", "", **_MENTIONS),
        ConfigField("map_replies", "Field: replies (optional)", "string", "", **_MENTIONS),
        ConfigField("source_label", "Source label", "string", "Custom", **_MENTIONS),
        ConfigField("limit_per_query", "Max items per query", "number", 25, **_MENTIONS),
        # ---- referring domains
        ConfigField("auth_header", "Auth header", "select", "none", ["none", "Authorization: Bearer", "X-API-Key"],
                    help="How to send the key, if it is not already in the URL.", **_BACKLINKS),
        ConfigField("map_domain", "Field: referring domain", "string", "domain", **_BACKLINKS),
        ConfigField("map_backlinks", "Field: backlinks", "string", "backlinks", **_BACKLINKS),
        ConfigField("map_dofollow", "Field: dofollow links", "string", "", **_BACKLINKS),
        ConfigField("map_rating", "Field: domain rating", "string", "", **_BACKLINKS),
        ConfigField("map_first_seen", "Field: first seen", "string", "", **_BACKLINKS),
        ConfigField("map_last_seen", "Field: last seen", "string", "", **_BACKLINKS),
        ConfigField("map_example_url", "Field: example linking URL", "string", "", **_BACKLINKS),
        ConfigField("limit", "Referring domains per sync", "number", 500, **_BACKLINKS),
        ConfigField("links_url", "Individual links: request URL", "string", "",
                    help="Optional second endpoint listing single links. {target} and {api_key} work here too.",
                    **_BACKLINKS),
        ConfigField("links_items_path", "Individual links: path to the list", "string", "", **_BACKLINKS),
        ConfigField("map_url_from", "Field: linking page URL", "string", "url_from", **_BACKLINKS),
        ConfigField("map_url_to", "Field: target URL", "string", "url_to", **_BACKLINKS),
        ConfigField("map_anchor", "Field: anchor text", "string", "anchor", **_BACKLINKS),
        ConfigField("map_page_title", "Field: linking page title", "string", "", **_BACKLINKS),
        ConfigField("map_nofollow", "Field: nofollow flag", "string", "",
                    help="A truthy value here marks the link nofollow. Leave blank to treat every link as dofollow.",
                    **_BACKLINKS),
    ]

    # ---------------------------------------------------------------- capability plumbing
    @staticmethod
    def mode_of(config: dict[str, Any] | None) -> str:
        mode = str((config or {}).get("capability") or DEFAULT_MODE)
        return mode if mode in MODES else DEFAULT_MODE

    @classmethod
    def category_for_config(cls, config: dict[str, Any] | None = None) -> str:
        return MODES[cls.mode_of(config)]["category"]

    @classmethod
    def declared_features(cls) -> list[str]:
        """Everything this provider could do, across every capability.

        The class-level answer is a union, while `get_capabilities()` reports only what *this* connection is set up
        for. Job selection uses the per-connection answer; the Integrations page and the "providers that can do
        this" hints in error messages use the union, which is what makes a blank-slate provider discoverable.
        """
        return sorted({f for m in MODES.values() for f in m["features"]})

    @property
    def mode(self) -> str:
        return self.mode_of(self.config)

    def _impl(self) -> ProviderAdapter:
        """The implementation for the chosen capability, built from this connection's credentials and config."""
        return MODES[self.mode]["impl"](credentials=self.credentials, config=self.config)

    def get_capabilities(self) -> Capabilities:
        mode = MODES[self.mode]
        inner = self._impl().get_capabilities()
        return Capabilities(category=mode["category"], measurement_type=inner.measurement_type,
                            features=list(mode["features"]), notes=inner.notes)

    # ---------------------------------------------------------------- delegation
    def health_check(self) -> HealthResult:
        if not str(self.config.get("request_url") or "").strip():
            return HealthResult(False, "No request URL configured")
        res = self._impl().health_check()
        return HealthResult(res.ok, f"{MODES[self.mode]['label']}: {res.message}", res.details)

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return self._impl().estimate_usage(request)

    def collect(self, request: dict[str, Any]) -> CollectResult:
        return self._impl().collect(request)

    def normalize(self, result: CollectResult) -> Any:
        return self._impl().normalize(result)

    def collect_links(self, request: dict[str, Any]) -> CollectResult:
        impl = self._impl()
        if not hasattr(impl, "collect_links"):
            raise ProviderError("This connection is not configured to return individual links")
        return impl.collect_links(request)

    def normalize_links(self, result: CollectResult) -> Any:
        return self._impl().normalize_links(result)   # type: ignore[attr-defined]
