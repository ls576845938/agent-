"""
bias_check.py — Cognitive Bias Detection

Identifies common cognitive biases in research: single-source dependency,
confirmation bias, hindsight bias, hot-topic chasing, and absence of
failure-condition planning.
"""

from typing import Any

from .scoring import CheckResult


def _get_field(item, field_name: str, default=None):
    """Get a field from either a dataclass instance or a dict."""
    if isinstance(item, dict):
        return item.get(field_name, default)
    return getattr(item, field_name, default)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _evidence_items(target: Any) -> list[dict]:
    return getattr(target, "evidence_items", None) or []


def _thesis(target: Any) -> str:
    return getattr(target, "thesis", None) or ""


def _metadata(target: Any) -> dict:
    return getattr(target, "metadata", None) or {}


def _unique_source_count(items: list[dict]) -> int:
    return len({_get_field(item, "source_name") for item in items if _get_field(item, "source_name")})


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_single_source_dependency(target: Any) -> CheckResult:
    """Check if all evidence comes from a single source."""
    items = _evidence_items(target)
    n = _unique_source_count(items)

    if n >= 3:
        return CheckResult(
            check_name="single_source_dependency",
            passed=True,
            score=1.0,
            details=f"Evidence from {n} independent sources — low dependency risk",
        )
    elif n == 2:
        return CheckResult(
            check_name="single_source_dependency",
            passed=True,
            score=0.5,
            details=f"Evidence from 2 sources — adequate but limited diversity",
        )
    else:
        return CheckResult(
            check_name="single_source_dependency",
            passed=False,
            score=0.0,
            details=f"All evidence from a single source ({next(iter({_get_field(item, "source_name") for item in items if _get_field(item, "source_name")}), 'unknown')})",
            risk_flags=["SINGLE_SOURCE_BIAS"],
        )


def _check_confirmatory_evidence_only(target: Any) -> CheckResult:
    """Check if evidence directions are all the same (confirmation bias)."""
    items = _evidence_items(target)
    if not items:
        return CheckResult(
            check_name="confirmatory_evidence_only",
            passed=True,
            score=1.0,
            details="No evidence items to assess",
        )

    directions = {_get_field(item, "direction") for item in items if _get_field(item, "direction")}
    # Ignore "neutral" for this check — only consider positive vs negative
    signed_directions = {d for d in directions if d in ("positive", "negative")}

    if len(signed_directions) > 1:
        return CheckResult(
            check_name="confirmatory_evidence_only",
            passed=True,
            score=1.0,
            details=f"Mixed evidence directions ({', '.join(signed_directions)}) — no confirmation bias",
        )
    elif len(signed_directions) == 1:
        direction = next(iter(signed_directions))
        source_count = _unique_source_count(items)
        if source_count >= 3:
            return CheckResult(
                check_name="confirmatory_evidence_only",
                passed=False,
                score=0.3,
                details=f"All evidence is {direction}, but from {source_count} independent sources — moderate concern",
                risk_flags=["CONFIRMATION_BIAS"],
            )
        else:
            return CheckResult(
                check_name="confirmatory_evidence_only",
                passed=False,
                score=0.0,
                details=f"All evidence is {direction} from a single/limited source — strong confirmation bias signal",
                risk_flags=["CONFIRMATION_BIAS"],
            )
    else:
        # No signed directions (only neutral or no direction field)
        return CheckResult(
            check_name="confirmatory_evidence_only",
            passed=True,
            score=1.0,
            details="No directional evidence to assess (neutral only)",
        )


_HINDSIGHT_PATTERNS = (
    "果然", "正如预期", "as expected", "验证了", "confirmed",
    "事后", "回顾", "回头看", "in retrospect", "hindsight",
    "早就说过", "一直认为",
)


def _check_hindsight_bias(target: Any) -> CheckResult:
    """Check for post-hoc rationalization patterns in the thesis and evidence timeline."""
    thesis = _thesis(target)
    items = _evidence_items(target)

    # Part 1: Thesis text patterns
    thesis_hindsight = any(p in thesis for p in _HINDSIGHT_PATTERNS)

    # Part 2: Evidence timeline (is publish_time mostly AFTER signal time?)
    # Attempt to look for signal_date in target metadata
    signal_date = None
    meta = _metadata(target)
    if isinstance(meta, dict):
        signal_date = meta.get("signal_date") or meta.get("created_at")

    evidence_after_signal = 0
    if signal_date:
        for item in items:
            pub_time = _get_field(item, "publish_time")
            if pub_time and isinstance(pub_time, str) and isinstance(signal_date, str):
                # Simple string comparison works for ISO-format dates
                if pub_time >= signal_date:
                    evidence_after_signal += 1

    total_with_time = sum(1 for item in items if _get_field(item, "publish_time"))
    # If most evidence came after the signal, it suggests hindsight
    timeline_concern = (
        total_with_time > 0
        and signal_date is not None
        and evidence_after_signal / total_with_time > 0.8
    )

    if thesis_hindsight and timeline_concern:
        return CheckResult(
            check_name="hindsight_bias",
            passed=False,
            score=0.0,
            details=f"Thesis uses hindsight language and {evidence_after_signal}/{total_with_time} evidence items postdate the signal",
            risk_flags=["HINDSIGHT_BIAS"],
        )
    elif thesis_hindsight:
        return CheckResult(
            check_name="hindsight_bias",
            passed=False,
            score=0.5,
            details="Thesis contains hindsight/post-hoc rationalization language",
            risk_flags=["HINDSIGHT_BIAS"],
        )
    elif timeline_concern:
        return CheckResult(
            check_name="hindsight_bias",
            passed=False,
            score=0.5,
            details=f"Most evidence ({evidence_after_signal}/{total_with_time}) postdates the signal — potential hindsight bias",
            risk_flags=["HINDSIGHT_BIAS"],
        )
    else:
        return CheckResult(
            check_name="hindsight_bias",
            passed=True,
            score=1.0,
            details="No hindsight bias patterns detected in thesis or evidence timeline",
        )


_HOT_BUZZWORDS = (
    "AI", "人工智能", "chatgpt", "ChatGPT", "大模型", "LLM",
    "元宇宙", "metaverse", "web3", "Web3", "碳中和", "carbon neutral",
    "区块链", "blockchain", "NFT", "量子计算", "quantum",
)


def _check_hot_chasing(target: Any) -> CheckResult:
    """Check if target is chasing hot topics without substantive analysis."""
    thesis = _thesis(target)
    items = _evidence_items(target)

    buzzwords_found = [kw for kw in _HOT_BUZZWORDS if kw in thesis]
    if not buzzwords_found:
        return CheckResult(
            check_name="hot_chasing",
            passed=True,
            score=1.0,
            details="No hot-topic buzzwords detected in thesis",
        )

    # Assess depth: short thesis (< 100 chars) or thin evidence (< 2 items) is suspicious
    shallow_thesis = len(thesis) < 100
    thin_evidence = len(items) < 2
    multiple_sources = _unique_source_count(items) >= 2

    if not shallow_thesis and not thin_evidence:
        return CheckResult(
            check_name="hot_chasing",
            passed=True,
            score=1.0,
            details=f"Thesis mentions hot topic(s) ({', '.join(buzzwords_found[:3])}) but is substantiated with analysis and evidence",
        )
    elif shallow_thesis and thin_evidence:
        return CheckResult(
            check_name="hot_chasing",
            passed=False,
            score=0.0,
            details=f"Thesis chases hot topic(s) ({', '.join(buzzwords_found[:3])}) with shallow thesis and insufficient evidence",
            risk_flags=["HOT_CHASING"],
        )
    else:
        return CheckResult(
            check_name="hot_chasing",
            passed=True,
            score=0.5,
            details=f"Hot topic(s) mentioned ({', '.join(buzzwords_found[:3])}) but borderline depth",
        )


_FAILURE_CONDITION_KEYS = {"failure_conditions", "stop_conditions", "invalidation_points"}
_THESIS_FAILURE_PATTERNS = (
    "如果...则", "unless", "风险", "risk", "失败条件",
    "止损", "stop loss", "退出条件", "exit condition",
    "如果", "若", "一旦", "invalidation",
)


def _check_no_failure_conditions(target: Any) -> CheckResult:
    """Check if the thesis defines conditions under which it would be wrong."""
    thesis = _thesis(target)
    meta = _metadata(target)

    # Check metadata for explicit failure condition keys
    if isinstance(meta, dict):
        meta_has_failure = any(k in meta for k in _FAILURE_CONDITION_KEYS)
    else:
        meta_has_failure = False

    # Check thesis for failure/risk language
    thesis_has_failure = any(p in thesis for p in _THESIS_FAILURE_PATTERNS)

    if meta_has_failure:
        return CheckResult(
            check_name="no_failure_conditions",
            passed=True,
            score=1.0,
            details="Explicit failure conditions defined in metadata",
        )
    elif thesis_has_failure:
        # Differentiate between explicit invalidation and generic risk mention
        explicit_invalidation = any(p in thesis for p in ("如果", "若", "一旦", "unless", "invalidation"))
        if explicit_invalidation:
            return CheckResult(
                check_name="no_failure_conditions",
                passed=True,
                score=0.5,
                details="Thesis contains conditional invalidation logic (if/then patterns)",
            )
        else:
            return CheckResult(
                check_name="no_failure_conditions",
                passed=True,
                score=0.5,
                details="Thesis mentions risk but lacks explicit failure/invalidation conditions",
            )
    else:
        return CheckResult(
            check_name="no_failure_conditions",
            passed=False,
            score=0.0,
            details="No failure conditions, stop conditions, or invalidation points defined",
            risk_flags=["NO_FAILURE_CONDITIONS"],
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_bias_checks(target: Any) -> list[CheckResult]:
    """Run all cognitive bias checks against a research target.

    Args:
        target: An object with optional attributes:
            .evidence_items (list[dict]), .thesis (str),
            .metadata (dict).

    Returns:
        list[CheckResult]: Results for all 5 bias checks.
    """
    return [
        _check_single_source_dependency(target),
        _check_confirmatory_evidence_only(target),
        _check_hindsight_bias(target),
        _check_hot_chasing(target),
        _check_no_failure_conditions(target),
    ]
