"""SerpApi adapters: the three jobs one key does here, and the parsing each one depends on.

Payloads mirror SerpApi's documented responses and are the contract this code was written against — when a real
key returns something different, fix the adapter and update the fixture here.
"""
import pytest

from app.adapters.ai.serpapi_surfaces import SerpApiAISurfacesAdapter
from app.adapters.base import CollectResult, ProviderError
from app.adapters.crawling.serpapi_extract import SerpApiExtractAdapter
from app.adapters.registry import provider_features, providers_with_feature
from app.adapters.search_data.serpapi import SerpApiSearchDataAdapter
from app.adapters.serpapi_client import SerpApiClient, account_summary, flatten_text_blocks, reference_links
from app.services.page_signals import looks_unrendered

KEY = {"api_key": "test-key"}


class FakeClient:
    """Stands in for SerpApiClient; records the engines asked for so billing can be asserted."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def search(self, params):
        self.calls.append(params.get("engine"))
        if not self.responses:
            raise AssertionError("unexpected extra search")
        payload = self.responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload


def with_client(adapter, *responses):
    fake = FakeClient(*responses)
    adapter._client = lambda: fake          # noqa: SLF001 — the seam these adapters are designed around
    return fake


# ------------------------------------------------------------------ shared AI block parsing
def test_text_blocks_flatten_in_reading_order_including_nested_blocks():
    blocks = [
        {"type": "paragraph", "snippet": "Short answer."},
        {"type": "list", "list": [{"title": "One", "snippet": "first"}, {"snippet": "second"}]},
        {"type": "expandable", "title": "More", "text_blocks": [{"type": "paragraph", "snippet": "deeper"}]},
        {"type": "paragraph"},                                     # no text at all, contributes nothing
    ]
    assert flatten_text_blocks(blocks) == ["Short answer.", "One", "first", "second", "More", "deeper"]


def test_text_blocks_tolerate_junk_and_cannot_recurse_forever():
    nested = {"text_blocks": []}
    cur = nested
    for _ in range(12):
        cur["text_blocks"] = [{"snippet": "x", "text_blocks": []}]
        cur = cur["text_blocks"][0]
    assert flatten_text_blocks("not a list") == []
    assert flatten_text_blocks([None, 3, "x"]) == []
    assert len(flatten_text_blocks([nested])) < 12


def test_references_without_a_link_are_not_citations():
    refs = [{"title": "A", "link": "https://a.test/x", "source": "A Co"}, {"title": "no link"}]
    assert reference_links(refs) == [{"link": "https://a.test/x", "title": "A", "source": "A Co"}]


def test_account_summary_reports_the_quota_a_user_can_act_on():
    msg = account_summary({"plan_name": "Free", "total_searches_left": 180, "this_month_usage": 70,
                           "searches_per_month": 250})
    assert "Free" in msg and "180 searches left" in msg and "70/250" in msg


def test_client_rejects_a_missing_key_before_spending_a_request():
    with pytest.raises(ProviderError, match="API key is required"):
        SerpApiClient(None)


# ------------------------------------------------------------------ AI surfaces (GEO)
OVERVIEW_BLOCK = {
    "text_blocks": [{"type": "paragraph", "snippet": "Growth tools compared."}],
    "references": [{"title": "Us", "link": "https://ours.test/guide", "source": "Ours"},
                   {"title": "Them", "link": "https://rival.test/post", "source": "Rival"}],
}


def test_ai_overview_inline_costs_one_search():
    a = SerpApiAISurfacesAdapter(credentials=KEY, config={"surface": "google_ai_overview"})
    fake = with_client(a, {"ai_overview": OVERVIEW_BLOCK})
    answer = a.normalize(a.collect({"prompt": "best growth tools", "language": "en", "country": "US"}))
    assert fake.calls == ["google"]
    assert answer.usage == {"searches": 1}
    assert answer.text == "Growth tools compared."
    assert [c.domain for c in answer.citations] == ["ours.test", "rival.test"]
    assert answer.grounded and answer.grounding_type == "provider_search"
    assert answer.model == "google_ai_overview"


def test_ai_overview_behind_a_page_token_is_fetched_immediately_and_costs_two():
    a = SerpApiAISurfacesAdapter(credentials=KEY, config={"surface": "google_ai_overview"})
    fake = with_client(a, {"ai_overview": {"page_token": "tok"}}, {"ai_overview": OVERVIEW_BLOCK})
    answer = a.normalize(a.collect({"prompt": "best growth tools", "language": "en", "country": "US"}))
    assert fake.calls == ["google", "google_ai_overview"]
    assert answer.usage == {"searches": 2} and answer.text == "Growth tools compared."


def test_a_failed_token_exchange_still_reports_the_search_it_cost():
    a = SerpApiAISurfacesAdapter(credentials=KEY, config={"surface": "google_ai_overview"})
    with_client(a, {"ai_overview": {"page_token": "tok"}}, ProviderError("token expired"))
    result = a.collect({"prompt": "x", "language": "en", "country": "US"})
    assert result.meta["searches"] == 2
    with pytest.raises(ProviderError, match="unavailable for this prompt"):
        a.normalize(result)


def test_a_serp_with_no_overview_is_an_observation_not_an_error():
    """'Google showed no AI Overview here' is the answer to a GEO question, so it must not raise."""
    a = SerpApiAISurfacesAdapter(credentials=KEY, config={"surface": "google_ai_overview"})
    with_client(a, {"organic_results": [{"position": 1, "link": "https://x.test"}]})
    answer = a.normalize(a.collect({"prompt": "x", "language": "en", "country": "US"}))
    assert answer.text == "" and answer.citations == [] and answer.usage == {"searches": 1}


def test_bing_copilot_leads_with_its_header_and_is_a_single_call():
    a = SerpApiAISurfacesAdapter(credentials=KEY, config={"surface": "bing_copilot"})
    fake = with_client(a, {"header": "Here is a summary.",
                           "text_blocks": [{"type": "paragraph", "snippet": "Detail."}],
                           "references": [{"title": "S", "link": "https://s.test/a"}]})
    answer = a.normalize(a.collect({"prompt": "x", "language": "en", "country": "GB"}))
    assert fake.calls == ["bing_copilot"]
    assert answer.text.startswith("Here is a summary.") and "Detail." in answer.text
    assert answer.model == "bing_copilot"


def test_ai_mode_passes_the_prompt_locale_through():
    a = SerpApiAISurfacesAdapter(credentials=KEY, config={"surface": "google_ai_mode"})
    fake = with_client(a, {"text_blocks": [{"snippet": "hi"}]})
    a.collect({"prompt": "q", "language": "DE", "country": "DE"})
    assert fake.calls == ["google_ai_mode"]
    a2 = SerpApiAISurfacesAdapter(credentials=KEY, config={"surface": "google_ai_mode"})
    fake2 = FakeClient({"text_blocks": [{"snippet": "hi"}]})
    a2._client = lambda: fake2          # noqa: SLF001
    res = a2.collect({"prompt": "q", "language": "DE", "country": "DE"})
    assert res.meta["request"]["gl"] == "de" and res.meta["request"]["hl"] == "de"


def test_an_unknown_surface_falls_back_to_ai_overview_rather_than_calling_a_bad_engine():
    a = SerpApiAISurfacesAdapter(credentials=KEY, config={"surface": "nonsense"})
    assert a._surface() == "google_ai_overview"          # noqa: SLF001


def test_ai_overview_is_budgeted_at_two_searches_per_sample():
    a = SerpApiAISurfacesAdapter(credentials=KEY, config={"surface": "google_ai_overview"})
    assert a.estimate_usage({"samples": 3}).requests == 6
    b = SerpApiAISurfacesAdapter(credentials=KEY, config={"surface": "bing_copilot"})
    assert b.estimate_usage({"samples": 3}).requests == 3


# ------------------------------------------------------------------ rank tracking
def serp(**extra):
    return {"search_metadata": {"id": "x"}, "search_parameters": {"q": "mock interview"},
            "organic_results": [{"position": 1, "link": "https://rival.test/a"},
                                {"position": 2, "link": "https://blog.ours.test/guide"}],
            **extra}


def rank(raw, host="ours.test", keyword="mock interview", **cfg):
    a = SerpApiSearchDataAdapter(credentials=KEY, config=cfg)
    return a.normalize_rank(CollectResult(raw=raw, meta={"keyword": keyword, "host": host}))


def test_rank_matches_our_subdomains_and_ignores_metadata_keys():
    row = rank(serp())
    assert row["position"] == 2 and row["url"] == "https://blog.ours.test/guide"
    assert row["serp_features"] == []          # nothing but metadata and organic results in this payload


def test_rank_reports_checked_but_absent_rather_than_nothing():
    row = rank(serp(), host="absent.test")
    assert row["position"] is None and row["keyword"] == "mock interview"


def test_www_is_stripped_from_both_sides_of_the_comparison():
    raw = serp()
    raw["organic_results"] = [{"position": 4, "link": "https://www.ours.test/"}]
    assert rank(raw, host="www.ours.test")["position"] == 4


def test_serp_feature_blocks_are_reported_without_a_stale_allowlist():
    row = rank(serp(related_questions=[{"question": "q"}], local_results={"places": [1]},
                    something_google_invented_later=[{"a": 1}], filters=[{"x": 1}], pagination={"next": "u"}))
    assert row["serp_features"] == ["local_results", "related_questions", "something_google_invented_later"]


def test_ai_overview_citation_of_our_domain_is_flagged_on_the_rank_row():
    row = rank(serp(ai_overview=OVERVIEW_BLOCK))
    assert "ai_overview_present" in row["serp_features"]
    assert "ai_overview_cites_you" in row["serp_features"]


def test_an_overview_that_ignores_us_is_distinguishable_from_no_overview_at_all():
    ignored = {"text_blocks": [{"snippet": "x"}],
               "references": [{"title": "Them", "link": "https://rival.test/post"}]}
    with_us = rank(serp(ai_overview=ignored))["serp_features"]
    assert "ai_overview_present" in with_us and "ai_overview_cites_you" not in with_us
    assert "ai_overview_present" not in rank(serp())["serp_features"]


def test_the_light_engine_is_the_default_and_google_is_opt_in():
    a = SerpApiSearchDataAdapter(credentials=KEY)
    light = with_client(a, serp())
    a.collect_rank({"keyword": "k"})
    assert light.calls == ["google_light"]
    b = SerpApiSearchDataAdapter(credentials=KEY, config={"engine": "google", "ai_overview": True})
    full = with_client(b, serp(ai_overview={"page_token": "t"}), {"ai_overview": OVERVIEW_BLOCK})
    result = b.collect_rank({"keyword": "k"})
    assert full.calls == ["google", "google_ai_overview"] and result.meta["searches"] == 2


def test_the_light_engine_never_pays_for_an_overview_it_cannot_receive():
    a = SerpApiSearchDataAdapter(credentials=KEY, config={"ai_overview": True})
    fake = with_client(a, serp(ai_overview={"page_token": "t"}))
    assert a.collect_rank({"keyword": "k"}).meta["searches"] == 1
    assert fake.calls == ["google_light"]


def test_serpapi_declares_no_keyword_database_capability():
    """The whole point of feature-based selection: this provider must not be handed a pricing job."""
    assert not hasattr(SerpApiSearchDataAdapter, "collect_keyword_metrics")
    assert not hasattr(SerpApiSearchDataAdapter, "collect_ranked_keywords")
    assert "keyword_metrics" not in provider_features("serpapi_serp")
    assert "ranked_keywords" not in provider_features("serpapi_serp")
    assert provider_features("serpapi_serp") >= {"rank_tracking", "keyword_discovery", "keyword_trends"}


def test_rank_tracking_is_no_longer_a_single_provider_capability():
    able = providers_with_feature("rank_tracking", category="search_data")
    assert {"dataforseo_labs", "serpapi_serp"} <= set(able)
    assert "answer_sampling" in provider_features("serpapi_ai")
    assert "javascript_rendering" in provider_features("serpapi_extract")


# ------------------------------------------------------------------ discovery
def ideas(raw, source):
    a = SerpApiSearchDataAdapter(credentials=KEY)
    return a.normalize_ideas(CollectResult(raw=raw, meta={"source": source, "seed": "s"}))


def test_autocomplete_keeps_its_relevance_score():
    rows = ideas({"suggestions": [{"value": "Mock Interview AI", "relevance": 802},
                                  {"value": "  ", "relevance": 10}]}, "autocomplete")
    assert rows == [{"keyword": "mock interview ai", "source": "autocomplete", "score": 802.0}]


def test_a_serp_read_yields_related_searches_and_people_also_ask():
    rows = ideas({"related_searches": [{"query": "Free Mock Interview"}],
                  "related_questions": [{"question": "How do I practise interviews?"}]}, "serp")
    assert [r["keyword"] for r in rows] == ["free mock interview", "how do i practise interviews?"]
    assert all(r["score"] is None for r in rows)


def test_trends_contributes_rising_and_top_queries_once_each():
    rows = ideas({"related_queries": {"rising": [{"query": "ai interview", "extracted_value": 250}],
                                      "top": [{"query": "AI Interview", "value": 100}]}}, "trends")
    assert rows == [{"keyword": "ai interview", "source": "trends", "score": 250.0}]


def test_a_scoreless_or_broken_value_does_not_lose_the_candidate():
    rows = ideas({"suggestions": [{"value": "a b"}, {"value": "c d", "relevance": "nope"}]}, "autocomplete")
    assert [(r["keyword"], r["score"]) for r in rows] == [("a b", None), ("c d", None)]


# ------------------------------------------------------------------ seasonality
def test_interest_over_time_summarises_direction_without_implying_volume():
    timeline = [{"date": f"w{i}", "values": [{"query": "widgets", "extracted_value": v}]}
                for i, v in enumerate([10, 12, 11, 10, 12, 11, 13, 12, 11, 12, 10, 11, 40, 55, 60, 70])]
    a = SerpApiSearchDataAdapter(credentials=KEY)
    rows = a.normalize_interest_over_time(
        CollectResult(raw={"interest_over_time": {"timeline_data": timeline}}, meta={"keywords": ["widgets"]}))
    assert len(rows) == 1
    r = rows[0]
    assert r["keyword"] == "widgets" and r["peak"] == 70 and r["peak_at"] == "w15" and r["latest"] == 70
    assert r["direction"] == "up" and r["trend_pct"] > 100
    assert len(r["points"]) == 16


def test_a_flat_series_is_reported_as_flat():
    timeline = [{"date": f"w{i}", "values": [{"query": "widgets", "extracted_value": 50}]} for i in range(16)]
    a = SerpApiSearchDataAdapter(credentials=KEY)
    row = a.normalize_interest_over_time(
        CollectResult(raw={"interest_over_time": {"timeline_data": timeline}}, meta={}))[0]
    assert row["direction"] == "flat" and row["trend_pct"] == 0.0


def test_trends_compares_at_most_five_terms_per_request():
    a = SerpApiSearchDataAdapter(credentials=KEY)
    fake = with_client(a, {"interest_over_time": {"timeline_data": []}})
    result = a.collect_interest_over_time({"keywords": ["a", "b", "c", "d", "e", "f"]})
    assert result.meta["keywords"] == ["a", "b", "c", "d", "e"]
    assert fake.calls == ["google_trends"]
    with pytest.raises(ProviderError, match="No keywords"):
        a.collect_interest_over_time({"keywords": []})


# ------------------------------------------------------------------ the render fallback
SHELL = '<html><body><div id="root"></div><script src="/bundle.js"></script></body></html>'
INLINE_SHELL = ('<html><body><div id="app"></div><script>window.__DATA__="' + "x" * 3000 + '";</script></body></html>')
REAL = "<html><body><h1>Pricing</h1><p>" + ("Real sentences about the product. " * 40) + "</p></body></html>"


def test_an_app_shell_is_recognised_as_unrendered():
    assert looks_unrendered(SHELL)


def test_an_inline_bundle_does_not_count_as_page_content():
    """selectolax counts script text as body text, so this is the case the heuristic exists to survive."""
    assert looks_unrendered(INLINE_SHELL)


def test_a_real_page_is_never_sent_to_a_paid_renderer():
    assert not looks_unrendered(REAL)
    assert not looks_unrendered("")
    assert not looks_unrendered("<html><body><h1>Tiny but server-rendered</h1></body></html>")


def test_extract_demands_html_rather_than_quietly_returning_a_shell():
    a = SerpApiExtractAdapter(credentials=KEY)
    a._client = lambda: type("C", (), {"fetch_text": lambda _s, _p, output: ""})()   # noqa: SLF001
    with pytest.raises(ProviderError, match="no HTML"):
        a.render_html("https://x.test/")


# ------------------------------------------------------------------ feature-based provider selection
class FakeConn:
    """Just enough of a ProviderConnection for the selection logic, which reads four attributes."""

    def __init__(self, provider_key, project_id=None, created_at=0, is_enabled=True):
        self.provider_key = provider_key
        self.project_id = project_id
        self.created_at = created_at
        self.is_enabled = is_enabled


class FakeDB:
    def __init__(self, conns):
        self._conns = conns

    def scalars(self, _stmt):
        return type("R", (), {"all": lambda _s: self._conns})()


def test_the_first_connection_no_longer_gets_handed_every_job_in_the_category():
    """The bug feature selection exists to prevent: SerpApi added first used to capture keyword pricing too."""
    from app.tasks.search_data import connected_provider
    db = FakeDB([FakeConn("serpapi_serp", created_at=1), FakeConn("dataforseo_labs", created_at=2)])
    assert connected_provider(db, None, "rank_tracking") == "serpapi_serp"
    assert connected_provider(db, None, "keyword_metrics") == "dataforseo_labs"
    assert connected_provider(db, None, "ranked_keywords") == "dataforseo_labs"
    assert connected_provider(db, None) == "serpapi_serp"          # no feature asked: oldest wins, as before


def test_a_project_scoped_connection_still_outranks_a_global_one():
    from app.tasks.search_data import connected_provider
    db = FakeDB([FakeConn("dataforseo_labs", project_id=None, created_at=1),
                 FakeConn("serpapi_serp", project_id="p", created_at=2)])
    assert connected_provider(db, "p", "rank_tracking") == "serpapi_serp"


def test_a_disabled_or_foreign_connection_is_not_selected():
    from app.tasks.search_data import connected_provider
    db = FakeDB([FakeConn("serpapi_serp", is_enabled=False), FakeConn("dataforseo_labs", project_id="other")])
    assert connected_provider(db, "p", "rank_tracking") is None


def test_no_capable_provider_returns_none_rather_than_a_provider_that_will_fail():
    from app.tasks.search_data import connected_provider
    db = FakeDB([FakeConn("ahrefs_keywords")])
    assert connected_provider(db, None, "rank_tracking") is None
    assert connected_provider(db, None, "keyword_metrics") == "ahrefs_keywords"


# ------------------------------------------------------------------ the renderer in the inspectors
class FakeResp:
    def __init__(self, text, headers=None):
        self.text = text
        self.final_url = "https://x.test/p"
        self.status_code = 200
        self.headers = headers or {"content-type": "text/html"}


def test_a_shell_page_is_not_reported_as_missing_an_h1_when_it_cannot_be_rendered(monkeypatch):
    """Without a renderer these pages are skipped: "no H1" on an unrendered shell is a finding about our fetcher."""
    import app.services.page_inspect as pi
    monkeypatch.setattr(pi, "safe_get", lambda *_a, **_k: FakeResp(SHELL))
    out = pi.inspect_pages(["https://x.test/p"], "missing_h1")
    assert out["issues"] == [] and out["pages_skipped_unrendered"] == 1 and out["pages_clean"] == 0


def test_a_rendered_shell_is_inspected_on_its_real_content(monkeypatch):
    import app.services.page_inspect as pi
    monkeypatch.setattr(pi, "safe_get", lambda *_a, **_k: FakeResp(SHELL))
    out = pi.inspect_pages(["https://x.test/p"], "missing_h1", lambda _u: REAL, render_budget=1)
    assert out["pages_rendered"] == 1 and out["pages_clean"] == 1 and out["issues"] == []


def test_the_render_budget_is_a_hard_ceiling(monkeypatch):
    import app.services.page_inspect as pi
    monkeypatch.setattr(pi, "safe_get", lambda *_a, **_k: FakeResp(SHELL))
    calls = []
    out = pi.inspect_pages(["https://x.test/1", "https://x.test/2", "https://x.test/3"], "missing_h1",
                           lambda u: (calls.append(u), REAL)[1], render_budget=2)
    assert len(calls) == 2 and out["pages_rendered"] == 2 and out["pages_skipped_unrendered"] == 1


def test_the_compression_check_is_never_served_from_rendered_html(monkeypatch):
    """It is a fact about how the bytes arrived, which a third-party fetch has by definition changed."""
    import app.services.page_inspect as pi
    monkeypatch.setattr(pi, "safe_get", lambda *_a, **_k: FakeResp(SHELL, {"content-type": "text/html",
                                                                          "content-encoding": "br"}))
    rendered = []
    out = pi.inspect_pages(["https://x.test/p"], "compression", lambda u: rendered.append(u) or REAL, render_budget=5)
    assert rendered == [] and out["issues"] == [] and not out["pages_skipped_unrendered"]


def test_signals_from_a_shell_are_flagged_rather_than_reported_as_a_bare_page(monkeypatch):
    import app.services.page_signals as ps
    monkeypatch.setattr(ps, "safe_get", lambda *_a, **_k: FakeResp(SHELL))
    assert ps.fetch_signals("https://x.test/p").get("unrendered") is True
    sig = ps.fetch_signals("https://x.test/p", lambda _u: REAL)
    assert sig.get("rendered") is True and sig.get("unrendered") is None


def test_a_renderer_failure_falls_back_to_the_shell_instead_of_losing_the_page(monkeypatch):
    import app.services.page_signals as ps
    monkeypatch.setattr(ps, "safe_get", lambda *_a, **_k: FakeResp(SHELL))

    def boom(_u):
        raise ProviderError("out of credits")

    sig = ps.fetch_signals("https://x.test/p", boom)
    assert sig["unrendered"] is True and "out of credits" in sig["render_error"] and sig.get("checked") is not False


def test_a_normal_page_never_calls_the_renderer(monkeypatch):
    import app.services.page_signals as ps
    monkeypatch.setattr(ps, "safe_get", lambda *_a, **_k: FakeResp(REAL))
    sig = ps.fetch_signals("https://x.test/p", lambda _u: (_ for _ in ()).throw(AssertionError("must not render")))
    assert sig.get("rendered") is None and sig.get("unrendered") is None


THIN_BUT_REAL = ('<html><body><h1>Contact</h1><p>Call us.</p>'
                 '<script src="https://www.googletagmanager.com/gtag/js"></script></body></html>')
SHELL_NO_MOUNT = '<html><body><div class="wrap"><div></div></div><script src="/bundle.js"></script></body></html>'


def test_a_thin_real_page_with_an_analytics_tag_is_not_mistaken_for_a_shell():
    """The false positive that matters: it would hide a real missing-H1 finding instead of reporting it."""
    assert not looks_unrendered(THIN_BUT_REAL)


def test_a_shell_without_a_recognised_mount_element_is_still_caught():
    assert looks_unrendered(SHELL_NO_MOUNT)


def test_a_mount_element_that_the_server_already_filled_is_not_a_shell():
    assert not looks_unrendered('<html><body><div id="root"><h1>Server rendered</h1></div>'
                                '<script src="/b.js"></script></body></html>')


# ------------------------------------------------------------------ the key in the environment
class FakeSettings:
    def __init__(self, **values):
        self.serpapi_api_key = ""
        self.google_api_key = ""
        self.gemini_api_key = ""
        for k, v in values.items():
            setattr(self, k, v)


def use_settings(monkeypatch, **values):
    import app.services.providers as sp
    monkeypatch.setattr(sp, "get_settings", lambda: FakeSettings(**values))
    return sp


class FakeConnection:
    def __init__(self, provider_key, credentials=None, config=None):
        from app.core.secrets import encrypt_credentials
        self.provider_key = provider_key
        self.credentials_encrypted = encrypt_credentials(credentials) if credentials else None
        self.config = config or {}


def test_an_unset_variable_is_not_reported_as_available(monkeypatch):
    sp = use_settings(monkeypatch)
    assert sp.env_credential_vars("serpapi_serp") == {}
    assert sp.env_credentials("serpapi_serp") == {}


def test_a_set_variable_is_offered_to_every_provider_that_shares_it(monkeypatch):
    sp = use_settings(monkeypatch, serpapi_api_key="env-key")
    for key in ("serpapi_serp", "serpapi_ai", "serpapi_extract"):
        assert sp.env_credential_vars(key) == {"api_key": "SERPAPI_API_KEY"}
        assert sp.env_credentials(key) == {"api_key": "env-key"}
    assert sp.env_credential_vars("dataforseo_labs") == {}          # no env path for this provider


def test_a_connection_with_no_stored_key_uses_the_environment(monkeypatch):
    sp = use_settings(monkeypatch, serpapi_api_key="env-key")
    adapter = sp.build_adapter(FakeConnection("serpapi_serp", config={"engine": "google"}))
    assert adapter.credentials["api_key"] == "env-key"
    assert adapter.config["engine"] == "google"                     # config still comes from the connection


def test_a_key_typed_on_the_connection_overrides_the_environment(monkeypatch):
    sp = use_settings(monkeypatch, serpapi_api_key="env-key")
    adapter = sp.build_adapter(FakeConnection("serpapi_ai", credentials={"api_key": "own-key"}))
    assert adapter.credentials["api_key"] == "own-key"


def test_the_environment_fills_only_the_fields_left_empty(monkeypatch):
    """A connection storing an empty string must not shadow the environment with nothing."""
    sp = use_settings(monkeypatch, serpapi_api_key="env-key")
    adapter = sp.build_adapter(FakeConnection("serpapi_extract", credentials={"api_key": ""}))
    assert adapter.credentials["api_key"] == "env-key"


def test_the_google_api_key_path_still_behaves_as_it_did(monkeypatch):
    """PageSpeed and CrUX were the original case; they now go through the same mechanism."""
    sp = use_settings(monkeypatch, google_api_key="g-key")
    assert sp.build_adapter(FakeConnection("crux")).credentials["api_key"] == "g-key"
    assert sp.build_connectionless_adapter("pagespeed_insights").credentials["api_key"] == "g-key"
    sp2 = use_settings(monkeypatch)
    assert sp2.build_connectionless_adapter("pagespeed_insights").credentials == {}


def test_the_preview_names_the_variable_rather_than_showing_the_secret(monkeypatch):
    sp = use_settings(monkeypatch, serpapi_api_key="env-key-1234567890")
    assert sp.credential_preview(FakeConnection("serpapi_serp")) == {"api_key": "from SERPAPI_API_KEY"}
    stored = sp.credential_preview(FakeConnection("serpapi_serp", credentials={"api_key": "abcdef1234567890"}))
    assert stored == {"api_key": "abc…7890"}                        # stored keys are masked, as before


def test_a_blank_required_credential_is_only_accepted_when_the_environment_has_it(monkeypatch):
    """The check `create_connection` runs, so a blank key stops being an error exactly when it stops being missing."""
    sp = use_settings(monkeypatch, serpapi_api_key="env-key")
    cls = __import__("app.adapters.registry", fromlist=["ADAPTERS"]).ADAPTERS["serpapi_serp"]
    required = [f.key for f in cls.credential_fields if f.required]
    assert required == ["api_key"]
    assert [k for k in required if k not in sp.env_credential_vars(cls.key)] == []
    sp2 = use_settings(monkeypatch)
    assert [k for k in required if k not in sp2.env_credential_vars(cls.key)] == ["api_key"]


# ------------------------------------------------------------------ running every engine, not just the first
def fake_ctx(db, **params):
    import types
    return types.SimpleNamespace(db=db, params=params)


def test_rank_tracking_runs_on_every_connected_engine(monkeypatch):
    """Google and Bing are different result pages, so both are measured — unlike pricing, which runs once."""
    import app.tasks.search_data as sd
    monkeypatch.setattr(sd, "get_adapter", lambda _db, _pid, key: (f"adapter:{key}", None))
    db = FakeDB([FakeConn("serpapi_serp", created_at=1), FakeConn("serpapi_bing", created_at=2),
                 FakeConn("ahrefs_keywords", created_at=3)])
    assert [p for p, _a, _c in sd._providers(fake_ctx(db), None, "rank_tracking")] == ["serpapi_serp", "serpapi_bing"]
    # Pricing a keyword list twice would just cost twice, so that job still resolves to exactly one provider.
    assert sd.connected_provider(db, None, "keyword_metrics") == "ahrefs_keywords"


def test_a_run_can_be_narrowed_to_one_engine(monkeypatch):
    import app.tasks.search_data as sd
    monkeypatch.setattr(sd, "get_adapter", lambda _db, _pid, key: (f"adapter:{key}", None))
    db = FakeDB([FakeConn("serpapi_serp"), FakeConn("serpapi_bing")])
    ctx = fake_ctx(db, provider_keys=["serpapi_bing"])
    assert [p for p, _a, _c in sd._providers(ctx, None, "rank_tracking")] == ["serpapi_bing"]


def test_asking_for_an_engine_that_cannot_rank_track_explains_which_ones_can(monkeypatch):
    import app.tasks.search_data as sd
    monkeypatch.setattr(sd, "get_adapter", lambda _db, _pid, key: (f"adapter:{key}", None))
    db = FakeDB([FakeConn("ahrefs_keywords")])
    with pytest.raises(ValueError, match="serpapi_bing|serpapi_serp"):
        sd._providers(fake_ctx(db), None, "rank_tracking")
    with pytest.raises(ValueError, match="No keyword provider is connected"):
        sd._providers(fake_ctx(FakeDB([])), None, "rank_tracking")


def test_gemini_takes_its_key_from_its_own_variable_not_the_cloud_one(monkeypatch):
    """GOOGLE_API_KEY is a Cloud console key normally restricted to PageSpeed and CrUX, so it cannot serve Gemini."""
    sp = use_settings(monkeypatch, google_api_key="cloud-key", gemini_api_key="studio-key")
    assert sp.env_credential_vars("gemini") == {"api_key": "GEMINI_API_KEY"}
    assert sp.build_adapter(FakeConnection("gemini")).credentials["api_key"] == "studio-key"
    assert sp.build_adapter(FakeConnection("crux")).credentials["api_key"] == "cloud-key"
    # Setting only the Cloud key must not quietly hand it to Gemini.
    only_cloud = use_settings(monkeypatch, google_api_key="cloud-key")
    assert only_cloud.env_credential_vars("gemini") == {}
    assert only_cloud.build_adapter(FakeConnection("gemini")).credentials == {}
