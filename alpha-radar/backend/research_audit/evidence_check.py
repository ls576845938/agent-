"""
evidence_check.py — Evidence Chain Integrity

Checks the quality, diversity, and traceability of evidence backing a research target.
"""

from typing import Any

from .scoring import CheckResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_field(item, field_name: str, default=None):
    """Get a field from either a dataclass instance or a dict."""
    if isinstance(item, dict):
        return item.get(field_name, default)
    return getattr(item, field_name, default)


def _get_evidence_items(target: Any) -> list:
    """Safely retrieve evidence_items from target, defaulting to empty list."""
    return getattr(target, "evidence_items", None) or []


def _unique_source_count(evidence_items: list) -> int:
    """Count distinct source_name values in evidence items."""
    sources = {_get_field(item, "source_name") for item in evidence_items if _get_field(item, "source_name")}
    return len(sources)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_min_independent_sources(target: Any) -> CheckResult:
    """Check that evidence comes from at least 2 independent sources."""
    items = _get_evidence_items(target)
    n = _unique_source_count(items)

    if n >= 3:
        return CheckResult(
            check_name="min_independent_sources",
            passed=True,
            score=1.0,
            details=f"{n} independent sources found (threshold: 2)",
        )
    elif n == 2:
        return CheckResult(
            check_name="min_independent_sources",
            passed=True,
            score=0.5,
            details=f"Exactly 2 independent sources — meets minimum but thin",
        )
    else:
        return CheckResult(
            check_name="min_independent_sources",
            passed=False,
            score=0.0,
            details=f"Only {n} independent source(s); at least 2 required",
            risk_flags=["SINGLE_SOURCE_DEPENDENCY"],
        )


def _check_non_ai_source_present(target: Any) -> CheckResult:
    """Check that at least one evidence item is not ai_generated."""
    items = _get_evidence_items(target)
    # Independent source means not AI-generated and not a manual note
    has_non_ai = any(
        _get_field(item, "source_type") not in ("ai_generated", "manual_note")
        for item in items
    )
    has_manual = any(_get_field(item, "source_type") == "manual_note" for item in items)
    has_ai_only = all(_get_field(item, "source_type") == "ai_generated" for item in items) if items else True

    if has_non_ai:
        return CheckResult(
            check_name="non_ai_source_present",
            passed=True,
            score=1.0,
            details="At least one non-AI evidence source present",
        )
    elif has_manual:
        return CheckResult(
            check_name="non_ai_source_present",
            passed=False,
            score=0.3,
            details="Only AI-generated and manual notes; no independent news/filing source",
            risk_flags=["AI_ONLY_EVIDENCE"],
        )
    else:
        return CheckResult(
            check_name="non_ai_source_present",
            passed=False,
            score=0.0,
            details="All evidence is AI-generated with no human or external source",
            risk_flags=["AI_ONLY_EVIDENCE"],
        )


_EXPECT_PUBLISH_TIME_TYPES = {"news", "filing", "financial"}


def _check_publish_time_traceability(target: Any) -> CheckResult:
    """Check that time-sensitive evidence items carry a publish_time."""
    items = _get_evidence_items(target)
    time_expected = [
        item for item in items
        if _get_field(item, "source_type") in _EXPECT_PUBLISH_TIME_TYPES
    ]
    if not time_expected:
        return CheckResult(
            check_name="publish_time_traceability",
            passed=True,
            score=1.0,
            details="No time-sensitive evidence types (news/filing/financial) to check",
        )

    with_time = [item for item in time_expected if _get_field(item, "publish_time")]
    ratio = len(with_time) / len(time_expected)
    passed = ratio == 1.0

    return CheckResult(
        check_name="publish_time_traceability",
        passed=passed,
        score=ratio,
        details=f"{len(with_time)}/{len(time_expected)} time-expected items have publish_time",
        risk_flags=[] if passed else ["UNTIMESTAMPED_EVIDENCE"],
    )


def _check_target_mapping(target: Any) -> CheckResult:
    """Check that evidence affected_targets map to the target's declared scope."""
    items = _get_evidence_items(target)
    if not items:
        return CheckResult(
            check_name="target_mapping",
            passed=True,
            score=1.0,
            details="No evidence items to map",
        )

    symbols = set(getattr(target, "related_symbols", None) or [])
    industries = set(getattr(target, "related_industries", None) or [])
    chain_nodes = set(getattr(target, "related_chain_nodes", None) or [])
    all_related = symbols | industries | chain_nodes

    if not all_related:
        # No target scope defined — cannot assess mapping
        return CheckResult(
            check_name="target_mapping",
            passed=True,
            score=1.0,
            details="No related symbols/industries/chain-nodes defined; mapping not applicable",
        )

    mapped_count = 0
    unmapped_details: list[str] = []

    for item in items:
        affected = set(_get_field(item, "affected_targets") or [])
        if affected & all_related:
            mapped_count += 1
        else:
            affected_str = ", ".join(affected) if affected else "(none)"
            unmapped_details.append(affected_str)

    ratio = mapped_count / len(items)
    passed = ratio >= 0.5

    details = (
        f"{mapped_count}/{len(items)} evidence items map to target scope (ratio={ratio:.0%})"
    )
    if not passed and unmapped_details:
        details += f"; unmapped targets: {', '.join(unmapped_details[:3])}"

    return CheckResult(
        check_name="target_mapping",
        passed=passed,
        score=ratio,
        details=details,
        risk_flags=[] if passed else ["EVIDENCE_TARGET_MISMATCH"],
    )


def _check_counter_evidence_present(target: Any) -> CheckResult:
    """Check that evidence includes both positive and negative directions."""
    items = _get_evidence_items(target)
    if not items:
        return CheckResult(
            check_name="counter_evidence_present",
            passed=True,
            score=1.0,
            details="No evidence items — neutral assessment",
        )

    directions = {_get_field(item, "direction") for item in items if _get_field(item, "direction")}
    has_positive = "positive" in directions
    has_negative = "negative" in directions
    thesis = getattr(target, "thesis", "") or ""
    thesis_is_neutral = thesis and any(
        phrase in thesis for phrase in ("中性", "neutral", "观望", "无明确方向")
    )

    if (has_positive and has_negative) or thesis_is_neutral:
        return CheckResult(
            check_name="counter_evidence_present",
            passed=True,
            score=1.0,
            details="Both positive and negative evidence directions present" if has_positive and has_negative
            else "Thesis is explicitly neutral; counter-evidence not required",
        )

    # Only one direction (or none — no directional claims to assess)
    if not directions:
        return CheckResult(
            check_name="counter_evidence_present",
            passed=True,
            score=1.0,
            details="No directional evidence — cannot assess counter-evidence balance",
        )

    single_direction = next(iter(directions))
    source_count = _unique_source_count(items)
    if len(items) >= 3 and source_count >= 3:
        return CheckResult(
            check_name="counter_evidence_present",
            passed=False,
            score=0.5,
            details=f"Only {single_direction} evidence from {source_count} sources, but multi-source depth partially mitigates",
            risk_flags=["NO_COUNTER_EVIDENCE"],
        )
    else:
        return CheckResult(
            check_name="counter_evidence_present",
            passed=False,
            score=0.0,
            details=f"Only {single_direction} evidence from single/limited source — confirmation bias risk",
            risk_flags=["NO_COUNTER_EVIDENCE"],
        )


def _check_source_freshness(target: Any) -> CheckResult:
    """Check freshness of evidence sources."""
    items = _get_evidence_items(target)
    if not items:
        return CheckResult(
            check_name="source_freshness",
            passed=True,
            score=1.0,
            details="No evidence items to assess freshness",
        )

    total = len(items)
    non_stale = sum(
        1 for item in items
        if _get_field(item, "freshness", "unknown") in ("recent", "moderate", "unknown")
    )
    ratio = non_stale / total
    passed = ratio >= 0.5

    stale_count = total - non_stale
    return CheckResult(
        check_name="source_freshness",
        passed=passed,
        score=ratio,
        details=f"{non_stale}/{total} items are non-stale (ratio={ratio:.0%})",
        risk_flags=[] if passed else ["STALE_EVIDENCE"],
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_evidence_checks(target: Any) -> list[CheckResult]:
    """Run all evidence chain integrity checks against a research target.

    Args:
        target: An object with optional attributes:
            .evidence_items (list[dict]), .related_symbols (list[str]),
            .related_industries (list[str]), .related_chain_nodes (list[str]),
            .thesis (str).

    Returns:
        list[CheckResult]: Results for all 6 evidence checks.
    """
    return [
        _check_min_independent_sources(target),
        _check_non_ai_source_present(target),
        _check_publish_time_traceability(target),
        _check_target_mapping(target),
        _check_counter_evidence_present(target),
        _check_source_freshness(target),
    ]
