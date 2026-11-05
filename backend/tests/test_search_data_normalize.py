"""Keyword/SERP providers all collapse to the same three row shapes.

Payloads mirror each vendor's documented response. They are the contract this code was written against — when a
real key returns something different, fix the adapter and update the fixture here.
"""
import pytest

from app.adapters.base import CollectResult, ProviderError
from app.adapters.search_data.ahrefs import AhrefsSearchDataAdapter
from app.adapters.search_data.common import best_per_keyword, clean_keyword, metric_row, rank_row, ranked_row
from app.adapters.search_data.dataforseo import DataForSEOSearchDataAdapter
from app.adapters.search_data.semrush import SemrushSearchDataAdapter

METRIC_FIELDS = {"keyword", "search_volume", "difficulty", "cpc", "competition", "intent"}
RANKED_FIELDS = {"keyword", "position", "url", "search_volume", "traffic", "difficulty"}


# ------------------------------------------------------------------ shared shapes
def test_keywords_are_normalised_for_matching():
    assert clean_keyword("  Mock   INTERVIEW  ") == "mock interview"
    assert clean_keyword(None) == ""


def test_metric_row_distinguishes_zero_volume_from_unknown():
    assert metric_row("a", search_volume=0)["search_volume"] == 0
    assert metric_row("a")["search_volume"] is None
    assert metric_row("   ") is None


def test_ranked_row_drops_rows_without_a_position():
    assert ranked_row("a", 0) is None and ranked_row("a", None) is None
    assert ranked_row("a", "3")["position"] == 3


def test_rank_row_keeps_checked_but_absent():
    r = rank_row("a", position=None, serp_features=["ai_overview", "people_also_ask"])
    assert r["position"] is None and r["serp_features"] == ["ai_overview", "people_also_ask"]


def test_best_per_keyword_keeps_the_strongest_position():
    rows = [ranked_row("a", 9), ranked_row("a", 3), ranked_row("b", 5)]
    assert [(r["keyword"], r["position"]) for r in best_per_keyword(rows)] == [("a", 3), ("b", 5)]


# ------------------------------------------------------------------ DataForSEO
def test_dataforseo_keyword_metrics():
    raw = {"tasks": [{"result": [{"items": [
        {"keyword": "Mock Interview", "keyword_info": {"search_volume": 18100, "cpc": 3.12, "competition": 0.44},
         "keyword_properties": {"keyword_difficulty": 42},
         "search_intent_info": {"main_intent": "informational"}},
        {"keyword": "", "keyword_info": {"search_volume": 10}},               # unusable, dropped
    ]}]}]}
    rows = DataForSEOSearchDataAdapter().normalize_keyword_metrics(CollectResult(raw=raw, meta={}))
    assert len(rows) == 1 and set(rows[0]) == METRIC_FIELDS
    assert rows[0] == {"keyword": "mock interview", "search_volume": 18100, "difficulty": 42.0,
                       "cpc": 3.12, "competition": 0.44, "intent": "informational"}


def test_dataforseo_ranked_keywords():
    raw = {"tasks": [{"result": [{"items": [
        {"keyword_data": {"keyword": "AI Interview Prep", "keyword_info": {"search_volume": 4400},
                          "keyword_properties": {"keyword_difficulty": 31}},
         "ranked_serp_element": {"serp_item": {"rank_group": 7, "url": "https://me.com/prep", "etv": 120.5}}},
        {"keyword_data": {"keyword": "no position"}, "ranked_serp_element": {"serp_item": {}}},   # dropped
    ]}]}]}
    rows = DataForSEOSearchDataAdapter().normalize_ranked_keywords(CollectResult(raw=raw, meta={}))
    assert len(rows) == 1 and set(rows[0]) == RANKED_FIELDS
    assert rows[0]["keyword"] == "ai interview prep" and rows[0]["position"] == 7
    assert rows[0]["traffic"] == 120.5 and rows[0]["difficulty"] == 31.0


def _serp(items):
    return CollectResult(raw={"tasks": [{"result": [{"items": items}]}]},
                         meta={"keyword": "mock interview", "host": "me.com"})


def test_dataforseo_rank_finds_the_host_and_collects_serp_features():
    row = DataForSEOSearchDataAdapter().normalize_rank(_serp([
        {"type": "ai_overview"},
        {"type": "organic", "rank_group": 1, "url": "https://rival.com/a"},
        {"type": "people_also_ask"},
        {"type": "organic", "rank_group": 4, "url": "https://www.me.com/page"},
    ]))
    assert row["position"] == 4 and row["url"] == "https://www.me.com/page"
    assert row["serp_features"] == ["ai_overview", "people_also_ask"]


def test_dataforseo_rank_reports_absent_rather_than_failing():
    row = DataForSEOSearchDataAdapter().normalize_rank(_serp([
        {"type": "organic", "rank_group": 1, "url": "https://rival.com/a"}]))
    assert row["position"] is None and row["url"] is None


def test_dataforseo_rank_matches_a_subdomain_but_not_a_lookalike():
    assert DataForSEOSearchDataAdapter().normalize_rank(_serp([
        {"type": "organic", "rank_group": 2, "url": "https://blog.me.com/x"}]))["position"] == 2
    assert DataForSEOSearchDataAdapter().normalize_rank(_serp([
        {"type": "organic", "rank_group": 2, "url": "https://notme.com/x"}]))["position"] is None


# ------------------------------------------------------------------ Ahrefs
def test_ahrefs_keyword_metrics_and_ranked_keywords():
    a = AhrefsSearchDataAdapter()
    metrics = a.normalize_keyword_metrics(CollectResult(
        raw={"keywords": [{"keyword": "Mock Interview", "volume_monthly": 18100, "difficulty": 42, "cpc": 3.1}]},
        meta={}))
    assert metrics[0]["keyword"] == "mock interview" and metrics[0]["search_volume"] == 18100

    ranked = a.normalize_ranked_keywords(CollectResult(
        raw={"keywords": [{"keyword": "AI prep", "best_position": 5, "best_position_url": "https://me.com/x",
                           "volume": 900, "keyword_difficulty": 20, "sum_traffic": 44}]}, meta={}))
    assert ranked[0]["position"] == 5 and ranked[0]["traffic"] == 44.0


def test_ahrefs_has_no_live_serp_endpoint():
    assert not hasattr(AhrefsSearchDataAdapter, "collect_rank")


# ------------------------------------------------------------------ Semrush
def test_semrush_keyword_metrics_and_ranked_keywords():
    a = SemrushSearchDataAdapter()
    metrics = a.normalize_keyword_metrics(CollectResult(
        raw={"body": "Keyword;Search Volume;CPC;Competition;Number of Results\nMock Interview;18100;3.10;0.44;120000\n"},
        meta={}))
    assert metrics[0] == {"keyword": "mock interview", "search_volume": 18100, "difficulty": None,
                          "cpc": 3.10, "competition": 0.44, "intent": None}

    ranked = a.normalize_ranked_keywords(CollectResult(
        raw={"body": "Keyword;Position;Search Volume;Url;Traffic (%)\nai prep;5;900;https://me.com/x;1.2\nbroken;row\n"},
        meta={}))
    assert len(ranked) == 1 and ranked[0]["position"] == 5 and ranked[0]["url"] == "https://me.com/x"


def test_semrush_empty_body():
    a = SemrushSearchDataAdapter()
    assert a.normalize_keyword_metrics(CollectResult(raw={"body": ""}, meta={})) == []
    assert a.normalize_ranked_keywords(CollectResult(raw={}, meta={})) == []


# ------------------------------------------------------------------ SQL ordering regression
def test_nulls_last_ordering_compiles_to_valid_postgres():
    """`desc(col.nullslast())` emits 'col NULLS LAST DESC', which Postgres rejects. The modifiers must nest the
    other way round. This has bitten twice, so it is pinned here."""
    from sqlalchemy import Column, Integer, MetaData, Table, select
    from sqlalchemy.dialects import postgresql

    t = Table("t", MetaData(), Column("v", Integer))
    good = str(select(t.c.v).order_by(t.c.v.desc().nullslast()).compile(dialect=postgresql.dialect()))
    assert "v DESC NULLS LAST" in good

    from sqlalchemy import desc
    bad = str(select(t.c.v).order_by(desc(t.c.v.nullslast())).compile(dialect=postgresql.dialect()))
    assert "NULLS LAST DESC" in bad        # the shape to never ship
