"""Vendor grouping and per-connection capabilities — the two things the Integrations page is now built on."""
import pytest

from app.adapters.base import ConfigField, ProviderAdapter
from app.adapters.custom_api import MODES, CustomAPIAdapter
from app.adapters.registry import ADAPTERS, provider_features, providers_with_feature
from app.core.secrets import encrypt_credentials
from app.services.providers import connection_features


class FakeConnection:
    def __init__(self, provider_key, config=None, credentials=None):
        self.provider_key = provider_key
        self.config = config or {}
        self.credentials_encrypted = encrypt_credentials(credentials) if credentials else None


# ------------------------------------------------------------------ vendor grouping
def test_every_provider_names_a_vendor_so_nothing_falls_out_of_the_page():
    missing = [k for k, c in ADAPTERS.items() if not (c.vendor or "").strip()]
    assert missing == []


def test_one_key_one_vendor_row():
    """The complaint this was built for: SerpApi used to appear six times under four category headings."""
    serpapi = [k for k, c in ADAPTERS.items() if c.vendor == "SerpApi"]
    assert len(serpapi) >= 6
    assert len({ADAPTERS[k].category for k in serpapi}) >= 4          # spread across categories
    assert len({ADAPTERS[k].vendor for k in serpapi}) == 1            # but one row


def test_vendors_that_sell_across_categories_are_grouped_not_duplicated():
    from collections import defaultdict
    by_vendor = defaultdict(list)
    for k, c in ADAPTERS.items():
        by_vendor[c.vendor].append(k)
    multi = {v: ks for v, ks in by_vendor.items() if len(ks) > 1}
    assert {"SerpApi", "Google", "DataForSEO", "Ahrefs", "Semrush"} <= set(multi)
    # Fewer vendor rows than adapters is the whole point.
    assert len(by_vendor) < len(ADAPTERS)


def test_the_subclassed_ai_providers_are_their_own_vendors():
    """Perplexity and Ollama inherit from the generic OpenAI-compatible adapter but are not that vendor."""
    assert ADAPTERS["perplexity"].vendor == "Perplexity"
    assert ADAPTERS["ollama"].vendor == "Ollama"
    assert ADAPTERS["openai_compatible"].vendor == "OpenAI-compatible API"


def test_describe_carries_what_the_page_groups_and_labels_by():
    d = ADAPTERS["serpapi_bing"].describe()
    assert d["vendor"] == "SerpApi" and d["vendor_url"].startswith("https://")
    assert "rank_tracking" in d["features"]


def test_apify_semrush_is_a_backlink_provider_with_an_optional_env_token():
    d = ADAPTERS["apify_semrush_backlinks"].describe()
    assert d["category"] == "backlinks" and d["vendor"] == "Apify"
    assert {"referring_domains", "backlinks", "profile_totals"} <= set(d["features"])


# ------------------------------------------------------------------ per-connection capability
def test_a_custom_endpoint_is_whatever_it_was_configured_as():
    mentions = FakeConnection("custom_source", {"capability": "mentions"})
    backlinks = FakeConnection("custom_source", {"capability": "referring_domains"})
    assert "mentions" in connection_features(mentions)
    assert "referring_domains" not in connection_features(mentions)
    assert "referring_domains" in connection_features(backlinks)
    assert "mentions" not in connection_features(backlinks)


def test_an_existing_connection_without_a_capability_keeps_doing_its_old_job():
    """The merge must not strand connections created before it: the default is what they were already doing."""
    legacy = FakeConnection("custom_source", {"request_url": "https://api.example.com/s?q={query}", "map_id": "id"})
    assert "mentions" in connection_features(legacy)
    assert CustomAPIAdapter.category_for_config(legacy.config) == "brand"


def test_the_category_follows_the_capability_so_the_right_task_collects_it():
    assert CustomAPIAdapter.category_for_config({"capability": "mentions"}) == "brand"
    assert CustomAPIAdapter.category_for_config({"capability": "referring_domains"}) == "backlinks"
    assert CustomAPIAdapter.category_for_config({}) == "brand"
    assert CustomAPIAdapter.category_for_config({"capability": "nonsense"}) == "brand"


def test_the_class_reports_the_union_and_the_connection_reports_the_choice():
    """Error messages and the page need "could do"; job selection needs "is set up to do"."""
    assert set(provider_features("custom_source")) == {"mentions", "engagement", "referring_domains", "backlinks"}
    assert "custom_source" in providers_with_feature("referring_domains")
    assert "custom_source" in providers_with_feature("mentions")
    assert connection_features(FakeConnection("custom_source", {"capability": "referring_domains"})) == \
        {"referring_domains", "backlinks"}


def test_a_real_vendors_capabilities_do_not_depend_on_config():
    """Only blank-slate providers get a capability switch; an API does what it does."""
    for key in ("dataforseo_labs", "serpapi_bing", "openai"):
        plain = connection_features(FakeConnection(key))
        odd = connection_features(FakeConnection(key, {"capability": "referring_domains"}))
        assert plain == odd == set(provider_features(key))


def test_an_unknown_provider_key_yields_no_capabilities_rather_than_raising():
    assert connection_features(FakeConnection("deleted_provider")) == set()


def test_the_merged_provider_delegates_to_the_implementation_for_its_mode():
    mentions = CustomAPIAdapter(config={"capability": "mentions"})
    backlinks = CustomAPIAdapter(config={"capability": "referring_domains"})
    assert type(mentions._impl()).__name__ == "CustomSourceAdapter"      # noqa: SLF001
    assert type(backlinks._impl()).__name__ == "CustomBacklinksAdapter"  # noqa: SLF001
    assert mentions.get_capabilities().category == "brand"
    assert backlinks.get_capabilities().category == "backlinks"


def test_the_merged_provider_reports_a_missing_url_before_trying_to_use_it():
    res = CustomAPIAdapter(config={"capability": "referring_domains"}).health_check()
    assert res.ok is False and "request URL" in res.message


def test_individual_link_harvesting_is_refused_in_mentions_mode():
    from app.adapters.base import ProviderError
    a = CustomAPIAdapter(config={"capability": "mentions", "request_url": "https://x.test/{query}"})
    with pytest.raises(ProviderError, match="not configured to return individual links"):
        a.collect_links({"target": "x.test"})


def test_both_capabilities_are_reachable_and_file_under_different_categories():
    assert set(MODES) == {"mentions", "referring_domains"}
    assert {m["category"] for m in MODES.values()} == {"brand", "backlinks"}


# ------------------------------------------------------------------ conditional fields
def test_mode_specific_fields_are_marked_and_shared_ones_are_not():
    fields = {f.key: f for f in CustomAPIAdapter.config_fields}
    assert fields["request_url"].show_if == {}                        # always asked for
    assert fields["items_path"].show_if == {}
    assert fields["map_text"].show_if == {"capability": ["mentions"]}
    assert fields["map_domain"].show_if == {"capability": ["referring_domains"]}
    # The switch itself must never be conditional on anything, or the form could not be changed.
    assert fields["capability"].show_if == {} and fields["capability"].type == "select"
    assert set(fields["capability"].options) == set(MODES)


def test_show_if_defaults_to_empty_so_existing_adapters_are_unaffected():
    assert ConfigField("x", "X").show_if == {}
    assert all(f.show_if == {} for f in ADAPTERS["serpapi_bing"].config_fields)


def test_category_for_config_defaults_to_the_class_for_every_normal_provider():
    for key, cls in ADAPTERS.items():
        if key == "custom_source":
            continue
        assert cls.category_for_config({"capability": "referring_domains"}) == cls.category
    assert ProviderAdapter.category_for_config() == "base"
