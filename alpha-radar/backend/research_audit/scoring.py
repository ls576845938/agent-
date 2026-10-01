"""Check result dataclass and scoring utilities for the research audit engine.

Defines the canonical CheckResult type used by all audit check modules,
and functions for computing dimension-level and composite audit scores.
"""

from dataclasses import dataclass, field


@dataclass
class CheckResult:
    """Standard result for a single research credibility check.

    Fields:
        check_name: Human-readable identifier for the check.
        passed: Whether the check's minimum bar was met.
        score: Numeric quality score in [0.0, 1.0].
        details: Free-text explanation of the outcome.
        risk_flags: Zero or more machine-readable flag strings for alerting.
    """
    check_name: str
    passed: bool
    score: float
    details: str = ""
    risk_flags: list[str] = field(default_factory=list)


def compute_dimension_score(check_results: list[CheckResult]) -> float:
    """Average score across checks in a dimension, 0.0-1.0.

    An empty check list produces 0.0 (no evidence to score).
    """
    if not check_results:
        return 0.0
    return round(sum(cr.score for cr in check_results) / len(check_results), 4)


def compute_audit_score(
    evidence_score: float,
    signal_score: float,
    narrative_score: float,
    bias_score: float,
) -> float:
    """Weighted composite score 0.0-100.0.

    Weights reflect relative importance in research credibility:
        evidence    35%   (foundation — can the thesis be trusted?)
        signal      30%   (methodology — is the signal construction sound?)
        narrative   20%   (logic — does the thesis hold together?)
        bias        15%   (objectivity — are known biases mitigated?)
    """
    total = (
        evidence_score * 35.0
        + signal_score * 30.0
        + narrative_score * 20.0
        + bias_score * 15.0
    )
    return round(max(0.0, min(100.0, total)), 2)
