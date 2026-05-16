"""promotion_gate.py — Audit Status Determination

Maps dimension scores, failed checks, and warnings to one of five audit
status levels:

    BLOCKED              Fundamental evidence failure or critical check failed.
    WATCHLIST            Below research-readiness but not blocked.
    NEED_MORE_EVIDENCE   Evidence is the bottleneck; other dimensions may be OK.
    RESEARCH_READY       All dimensions meet minimum quality thresholds.
    HIGH_CONVICTION      Top-tier across all dimensions with zero failures.
"""

from typing import AbstractSet


_CRITICAL_CHECK_NAMES: AbstractSet[str] = frozenset({
    "min_independent_sources",
    "non_ai_source_present",
})


def determine_status(
    evidence_score: float,
    signal_score: float,
    narrative_score: float,
    bias_score: float,
    failed_checks: list[str],
    warnings: list[str],  # kept for future use by caller
) -> str:
    """Determine audit status from dimension scores and check outcomes.

    Evaluation order (first match wins):
        1. BLOCKED           — evidence < 0.3 or a critical check failed.
        2. HIGH_CONVICTION   — all >= 0.8, composite >= 80, no failed checks.
        3. RESEARCH_READY    — all >= 0.6, composite >= 60.
        4. NEED_MORE_EVIDENCE — evidence < 0.5 (and not blocked).
        5. WATCHLIST         — default / catch-all.

    Args:
        evidence_score:  Evidence dimension score [0.0, 1.0].
        signal_score:    Signal dimension score [0.0, 1.0].
        narrative_score: Narrative dimension score [0.0, 1.0].
        bias_score:      Bias dimension score [0.0, 1.0].
        failed_checks:   List of check_name strings that did not pass.
        warnings:        List of warning strings (informational; may be used for
                         future refinement).

    Returns:
        One of: BLOCKED | WATCHLIST | NEED_MORE_EVIDENCE |
                RESEARCH_READY | HIGH_CONVICTION
    """
    # ---------- 1. BLOCKED ----------
    if evidence_score < 0.3:
        return "BLOCKED"

    if _CRITICAL_CHECK_NAMES & set(failed_checks):
        return "BLOCKED"

    # Composite score (same weighting as scoring.compute_audit_score)
    composite = (
        evidence_score * 35.0
        + signal_score * 30.0
        + narrative_score * 20.0
        + bias_score * 15.0
    )

    # ---------- 2. HIGH_CONVICTION ----------
    if (
        evidence_score >= 0.8
        and signal_score >= 0.8
        and narrative_score >= 0.8
        and bias_score >= 0.8
        and composite >= 80.0
        and not failed_checks
    ):
        return "HIGH_CONVICTION"

    # ---------- 3. RESEARCH_READY ----------
    if (
        evidence_score >= 0.6
        and signal_score >= 0.6
        and narrative_score >= 0.6
        and bias_score >= 0.6
        and composite >= 60.0
    ):
        return "RESEARCH_READY"

    # ---------- 4. NEED_MORE_EVIDENCE ----------
    if evidence_score < 0.5:
        return "NEED_MORE_EVIDENCE"

    # ---------- 5. WATCHLIST (default) ----------
    return "WATCHLIST"
