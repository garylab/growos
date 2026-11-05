from datetime import date

from app.adapters.base import CollectResult
from app.adapters.search_performance.bing import (DAILY, PAGES, QUERIES, BingWebmasterAdapter, last_reported_date)


def _adapter():
    return BingWebmasterAdapter(credentials={"api_key": "k"})


def _result(rows, dataset, **meta):
    return CollectResult(raw={"rows": rows, "dataset": dataset, "site_url": "https://example.com"},
                         meta={"site_url": "https://example.com", "dataset": dataset, **meta})


def test_daily_rows_parse_dotnet_dates_and_compute_ctr():
    rows = [{"Date": "/Date(1762300800000)/", "Impressions": 1000, "Clicks": 25},
            {"Date": "/Date(1762387200000+0000)/", "Impressions": 0, "Clicks": 0}]
    out = _adapter().normalize(_result(rows, DAILY))
    assert out[0]["date"] == date(2025, 11, 5)
    assert out[0]["clicks"] == 25 and out[0]["impressions"] == 1000
    assert out[0]["ctr"] == 0.025
    # A day with no impressions must be 0 CTR, not a division error.
    assert out[1]["ctr"] == 0.0


def test_undated_rows_are_stamped_with_the_window_we_were_told():
    rows = [{"Query": "growos pricing", "Impressions": 400, "Clicks": 12, "AvgImpressionPosition": 4.5}]
    out = _adapter().normalize(_result(rows, QUERIES, as_of="2026-10-31"))
    assert out[0]["date"] == date(2026, 10, 31)
    assert out[0]["query"] == "growos pricing" and out[0]["page"] == ""
    assert out[0]["position"] == 4.5


def test_impression_position_is_preferred_over_click_position():
    """Mixing the two would put an incomparable number on the same chart as GSC's position."""
    rows = [{"Query": "a", "Impressions": 10, "Clicks": 1, "AvgImpressionPosition": 9.0, "AvgClickPosition": 2.0}]
    assert _adapter().normalize(_result(rows, QUERIES, as_of="2026-10-31"))[0]["position"] == 9.0
    # Click position is used only when the impression-weighted figure is absent.
    rows2 = [{"Query": "a", "Impressions": 10, "Clicks": 1, "AvgClickPosition": 2.0}]
    assert _adapter().normalize(_result(rows2, QUERIES, as_of="2026-10-31"))[0]["position"] == 2.0


def test_page_rows_read_the_url_bing_puts_in_the_query_field():
    rows = [{"Query": "https://example.com/pricing", "Impressions": 90, "Clicks": 4}]
    out = _adapter().normalize(_result(rows, PAGES, as_of="2026-10-31"))
    assert out[0]["page"] == "https://example.com/pricing" and out[0]["query"] == ""


def test_junk_rows_are_dropped_not_stored_as_blanks():
    out = _adapter().normalize(_result([{"Impressions": 5}, "not a dict", {"Query": "  "}], QUERIES, as_of="2026-10-31"))
    assert out == []
    assert _adapter().normalize(_result([{"Date": None, "Clicks": 3}], DAILY)) == []


def test_row_limit_is_respected():
    rows = [{"Query": f"q{i}", "Impressions": i} for i in range(1, 60)]
    adapter = BingWebmasterAdapter(credentials={"api_key": "k"}, config={"row_limit": 10})
    assert len(adapter.normalize(_result(rows, QUERIES, as_of="2026-10-31"))) == 10


def test_last_reported_date_falls_back_instead_of_discarding_rows():
    assert last_reported_date([{"date": date(2026, 10, 1)}, {"date": date(2026, 10, 9)}]) == date(2026, 10, 9)
    assert last_reported_date([]) < date.today()


def test_declared_capabilities_do_not_claim_country_or_device():
    features = BingWebmasterAdapter.declared_features()
    assert "query" in features and "page" in features and "impressions" in features
    assert "country" not in features and "device" not in features
