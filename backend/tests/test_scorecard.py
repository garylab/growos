import pytest

from app.intelligence.scorecard import Component, Index, grade, position_score, ratio_score, saturate, trend_score


def test_saturate_curve():
    assert saturate(0, 100) == 0
    assert saturate(100, 100) == 50.0      # the half point scores 50 by definition
    assert saturate(900, 100) == 90.0
    assert saturate(10**9, 100) < 100      # never reaches 100
    assert saturate(50, 0) == 0


def test_ratio_and_position_scores():
    assert ratio_score(0.03, 0.03) == 100
    assert ratio_score(0.015, 0.03) == 50
    assert ratio_score(0.10, 0.03) == 100  # clamped
    assert position_score(1) == 100
    assert position_score(21) == 0
    assert position_score(11) == 50
    assert position_score(0) == 0


def test_trend_score_is_50_when_flat():
    assert trend_score(100, 100) == 50
    assert trend_score(150, 100) == 100    # +50% is full swing
    assert trend_score(50, 100) == 0
    assert trend_score(125, 100) == 75
    assert trend_score(10, 0) == 65        # new signal where there was none
    assert trend_score(0, 0) == 50


def test_index_excludes_missing_components_and_reports_coverage():
    idx = Index("t", "T", "?")
    idx.components = [
        Component("a", "A", 0.5, 80.0),
        Component("b", "B", 0.3, 40.0),
        Component("c", "C", 0.2, None),   # no data
    ]
    r = idx.result()
    # weights renormalised over the 0.8 that had data: (80*0.5 + 40*0.3) / 0.8
    assert r["score"] == 65.0
    assert r["coverage"] == 0.8
    assert r["confidence"] == "high"
    assert r["missing"] == ["C"]


def test_index_with_no_data_scores_none():
    idx = Index("t", "T", "?")
    idx.components = [Component("a", "A", 1.0, None)]
    r = idx.result()
    assert r["score"] is None and r["coverage"] == 0.0 and r["grade"] == "n/a"


def test_low_coverage_is_withheld_not_flattered():
    """30% coverage with a 95 on the one available component must not publish 95."""
    idx = Index("t", "T", "?")
    idx.components = [Component("a", "A", 0.3, 95.0), Component("b", "B", 0.7, None)]
    r = idx.result()
    assert r["score"] is None and r["confidence"] == "low"
    assert r["insufficient_data"] is True and r["provisional_score"] == 95.0


@pytest.mark.parametrize("score,expected", [(90, "A"), (85, "A"), (70, "B"), (56, "C"), (40, "D"), (10, "E"), (None, "n/a")])
def test_grade_bands(score, expected):
    assert grade(score) == expected


def test_thin_coverage_is_not_published_as_a_score():
    """A single component scoring 100 must never present itself as an A grade."""
    idx = Index("t", "T", "?")
    idx.components = [Component("a", "A", 0.15, 100.0)] + [
        Component(k, k.upper(), 0.85 / 4, None) for k in ("b", "c", "d", "e")]
    r = idx.result()
    assert r["score"] is None and r["grade"] == "n/a"
    assert r["insufficient_data"] is True
    assert r["provisional_score"] == 100.0        # still visible, clearly labelled
    assert "required" in r["insufficient_reason"]


def test_sufficient_coverage_publishes_the_score():
    idx = Index("t", "T", "?")
    idx.components = [Component("a", "A", 0.6, 70.0), Component("b", "B", 0.4, None)]
    r = idx.result()
    assert r["score"] == 70.0 and r["insufficient_data"] is False and r["provisional_score"] is None


def test_zero_is_only_scored_after_data_was_actually_collected():
    """A project that never ran mention collection must show 'no data', not a score of zero."""
    from app.intelligence.scorecard import brand_influence

    class P:
        brand_name = "Acme"
        brand_aliases: list[str] = []

    never = brand_influence(P(), {"mentions": [], "mentions_collected": False})
    comp = next(c for c in never.components if c.key == "public_mentions")
    assert comp.score is None and not comp.available

    collected = brand_influence(P(), {"mentions": [], "mentions_collected": True})
    comp2 = next(c for c in collected.components if c.key == "public_mentions")
    assert comp2.score == 0.0 and comp2.available


def test_overall_is_geometric_weakest_link():
    from app.intelligence.scorecard import overall_score
    # geometric mean punishes imbalance harder than the arithmetic mean would
    assert overall_score([]) is None
    g = overall_score([10, 80, 60])
    assert g is not None and g < sum([10, 80, 60]) / 3      # 36.3 < 50
    assert abs(g - 36.3) < 0.2
    # a single weak dimension drags the whole down
    assert overall_score([90, 90, 10]) < overall_score([90, 90, 60])


def test_overall_zero_dimension_is_zero():
    from app.intelligence.scorecard import overall_score
    # a genuinely zero dimension makes the overall 0 — the honest answer (no awareness = no business)
    assert overall_score([80, 80, 0]) == 0
    assert overall_score([0, 0, 0]) == 0
    assert overall_score([50, 50, 50]) == 50.0
