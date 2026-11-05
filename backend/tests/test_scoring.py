import pytest

from app.intelligence.scoring import expected_ctr
from app.intelligence.scoring import EFFORT_FACTOR, confidence_from_samples, impact_from_clicks, priority_score


def test_priority_formula_is_transparent():
    score, breakdown = priority_score(80, 0.9, 2)
    assert score == round(80 * 0.9 * EFFORT_FACTOR[2], 1)
    assert breakdown["formula"] == "impact × confidence × effort_factor"
    assert breakdown["effort_factor"] == 0.9 and breakdown["priority"] == score


def test_priority_clamps_inputs():
    score, b = priority_score(500, 3, 9)
    assert b["impact"] == 100 and b["confidence"] == 1 and b["effort"] == 5
    assert score == round(100 * EFFORT_FACTOR[5], 1)


def test_impact_from_clicks_saturates():
    assert impact_from_clicks(0) == 0
    assert impact_from_clicks(50) == 50.0
    assert 90 < impact_from_clicks(5000) <= 100


@pytest.mark.parametrize("n,expected", [(1, 0.5), (3, 0.7), (10, 0.95)])
def test_confidence_from_samples(n, expected):
    assert confidence_from_samples(n) == expected


def test_expected_ctr_curve_is_monotonic():
    values = [expected_ctr(p) for p in range(1, 25)]
    assert all(a >= b for a, b in zip(values, values[1:], strict=False))
