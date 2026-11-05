"""Transparent priority scoring for checklist items.

priority = impact (0..100) × confidence (0..1) × effort_factor(effort)

- impact: estimated business impact, computed by each rule from evidence (e.g. potential extra clicks).
- confidence: how certain we are the opportunity is real. First-party data (GSC) → high; repeated AI samples →
  depends on sample size; heuristics → lower.
- effort: 1 (trivial change) … 5 (major project). effort_factor discounts hard work.
Every opportunity stores the inputs so the score can be audited in the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EFFORT_FACTOR = {1: 1.0, 2: 0.9, 3: 0.75, 4: 0.6, 5: 0.45}
EFFORT_LABELS = {1: "trivial (< 1 hour)", 2: "small (hours)", 3: "medium (days)", 4: "large (weeks)", 5: "major project"}


@dataclass
class Evidence:
    type: str            # e.g. search_observation, ai_answer_observation, audit_finding, brand_mention
    table: str           # DB table name for traceability
    record_ids: list[str] = field(default_factory=list)
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    measurement_type: str = "observed"  # first_party | observed | estimated | lab | field

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "table": self.table, "record_ids": self.record_ids[:50], "summary": self.summary,
                "data": self.data, "measurement_type": self.measurement_type}


@dataclass
class OpportunityDraft:
    kind: str
    module: str
    title: str
    description: str
    why: str
    evidence: list[Evidence]
    impact: float
    confidence: float
    effort: int
    recommended_action: str
    dedupe_key: str
    target_urls: list[str] = field(default_factory=list)
    target_keywords: list[str] = field(default_factory=list)
    score_inputs: dict[str, Any] = field(default_factory=dict)


# Expected organic click-through by average position (industry-wide approximations). Used to spot pages that rank
# well but are not winning the click, and to size the upside in the revenue model.
EXPECTED_CTR = {1: 0.28, 2: 0.15, 3: 0.11, 4: 0.08, 5: 0.07, 6: 0.05, 7: 0.04, 8: 0.035, 9: 0.03, 10: 0.025}


def expected_ctr(position: float) -> float:
    p = max(1, int(round(position)))
    return EXPECTED_CTR.get(p, 0.015 if p <= 20 else 0.005)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def priority_score(impact: float, confidence: float, effort: int) -> tuple[float, dict[str, Any]]:
    impact = clamp(float(impact), 0, 100)
    confidence = clamp(float(confidence), 0, 1)
    effort = int(clamp(effort, 1, 5))
    factor = EFFORT_FACTOR[effort]
    score = round(impact * confidence * factor, 1)
    return score, {"formula": "impact × confidence × effort_factor", "impact": impact, "confidence": confidence,
                   "effort": effort, "effort_label": EFFORT_LABELS[effort], "effort_factor": factor, "priority": score}


def confidence_from_samples(n: int, base: float = 0.5, cap: float = 0.95) -> float:
    """More repeated AI samples → more confidence, with diminishing returns."""
    return round(clamp(base + 0.1 * (n - 1), 0, cap), 2)


def impact_from_clicks(potential_clicks: float, scale: float = 50.0) -> float:
    """Map potential monthly clicks to 0..100 using a saturating curve (50 clicks/month ≈ 50 impact)."""
    return round(clamp(100 * potential_clicks / (potential_clicks + scale), 0, 100), 1)
