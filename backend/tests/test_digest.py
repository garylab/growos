from types import SimpleNamespace

from app.services.digest import _fmt_delta, digest_text


def test_fmt_delta_week_over_week():
    assert _fmt_delta(150, 100) == "150 (▲50% WoW)"
    assert _fmt_delta(80, 100) == "80 (▼20% WoW)"
    assert _fmt_delta(100, 100) == "100 (•0% WoW)"
    assert _fmt_delta(50, 0) == "50"


def test_digest_text_handles_missing_integrations():
    p = SimpleNamespace(name="Acme")
    d = {"search": None, "geo": None, "geo_prev": None, "open_fixes": 4, "routines_due": 3,
         "top_to_do": [{"title": "Fix titles", "priority": 70}], "new_mentions": 0, "competitor_changes": 0}
    text = digest_text(p, d)
    assert "Search Console not connected" in text
    assert "4 things to fix" in text and "Fix titles" in text


def test_digest_text_with_data():
    p = SimpleNamespace(name="Acme")
    d = {"search": {"clicks": 120, "clicks_prev": 100, "impressions": 3000, "impressions_prev": 3200},
         "geo": {"brand_mention_rate": 0.4}, "geo_prev": {"brand_mention_rate": 0.3},
         "open_fixes": 2, "routines_due": 1, "top_to_do": [], "new_mentions": 5, "competitor_changes": 1}
    text = digest_text(p, d)
    assert "Search clicks: 120 (▲20% WoW)" in text
    assert "AI mention rate: 40% (was 30%)" in text
    assert "5 new brand mentions" in text
