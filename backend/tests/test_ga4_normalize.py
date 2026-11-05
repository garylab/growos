from datetime import date

from app.adapters.analytics.ga4 import GoogleAnalytics4Adapter
from app.adapters.base import CollectResult


def test_ga4_runreport_normalize():
    raw = {"rows": [
        {"dimensionValues": [{"value": "20260101"}, {"value": "/pricing"}, {"value": "google"}, {"value": "organic"}],
         "metricValues": [{"value": "120"}, {"value": "100"}, {"value": "7"}, {"value": "199.5"}, {"value": "48"}, {"value": "3600"}]},
        {"dimensionValues": [{"value": "20260101"}, {"value": "(not set)"}, {"value": "(direct)"}, {"value": "(none)"}],
         "metricValues": [{"value": "3"}, {"value": "3"}, {"value": "0"}, {"value": "0"}, {"value": "0"}, {"value": "0"}]},
        {"dimensionValues": [{"value": "bad"}, {"value": "/x"}, {"value": "a"}, {"value": "b"}], "metricValues": [{"value": "1"}] * 6},
    ]}
    rows = GoogleAnalytics4Adapter().normalize(CollectResult(raw=raw, meta={}))
    assert len(rows) == 2
    assert rows[0] == {"date": date(2026, 1, 1), "landing_page": "/pricing", "source": "google", "medium": "organic",
                       "sessions": 120, "users": 100, "conversions": 7, "revenue": 199.5,
                       "engaged_sessions": 48, "engagement_time_sec": 3600.0}
    assert rows[1]["medium"] == "" and rows[1]["source"] == "(direct)"


def test_ga4_normalize_without_engagement_metrics():
    """A stored artifact from before engagement was requested must still replay, with engagement at zero."""
    raw = {"rows": [
        {"dimensionValues": [{"value": "20260101"}, {"value": "/old"}, {"value": "google"}, {"value": "organic"}],
         "metricValues": [{"value": "10"}, {"value": "9"}, {"value": "1"}, {"value": "5"}]},
    ]}
    rows = GoogleAnalytics4Adapter().normalize(CollectResult(raw=raw, meta={}))
    assert len(rows) == 1
    assert rows[0]["sessions"] == 10
    assert rows[0]["engaged_sessions"] == 0 and rows[0]["engagement_time_sec"] == 0.0


def test_ga4_requests_the_engagement_metrics():
    from app.adapters.analytics import ga4
    import inspect
    src = inspect.getsource(ga4.GoogleAnalytics4Adapter.collect)
    assert "engagedSessions" in src and "userEngagementDuration" in src


def test_ga4_registered_and_describes_credentials():
    from app.adapters.registry import ADAPTERS, PLANNED_ADAPTERS
    assert "google_analytics_4" in ADAPTERS
    assert all(p["key"] != "google_analytics_4" for p in PLANNED_ADAPTERS)
    desc = ADAPTERS["google_analytics_4"].describe()
    assert {f["key"] for f in desc["credential_fields"]} == {"service_account_json", "client_id", "client_secret", "refresh_token"}
