"""
narrative_check.py — Narrative Logic

Evaluates the logical structure of a research thesis: chain path clarity,
upstream/downstream positioning, profit driver identification, direction
clarity, and avoidance of grand narratives.
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

def _thesis(target: Any) -> str:
    return getattr(target, "thesis", None) or ""


def _chain_nodes(target: Any) -> list:
    return getattr(target, "related_chain_nodes", None) or []


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_chain_path_clarity(target: Any) -> CheckResult:
    """Check that the transmission path from catalyst to target is clear."""
    thesis = _thesis(target)
    nodes = _chain_nodes(target)

    path_keywords = (
        "→", "->", "传导", "影响", "带动", "驱动", "上游", "中游", "下游",
        "transmission", "pass-through", "spillover",
    )
    thesis_has_path = any(kw in thesis for kw in path_keywords)
    nodes_non_empty = len(nodes) > 0

    if nodes_non_empty and thesis_has_path:
        return CheckResult(
            check_name="chain_path_clarity",
            passed=True,
            score=1.0,
            details=f"Chain nodes ({len(nodes)}) defined and thesis describes transmission path",
        )
    elif nodes_non_empty or thesis_has_path:
        return CheckResult(
            check_name="chain_path_clarity",
            passed=True,
            score=0.5,
            details="Partial chain path definition: "
                    + ("chain nodes exist but thesis lacks path keywords"
                       if nodes_non_empty
                       else "thesis has path keywords but no explicit chain nodes"),
        )
    else:
        return CheckResult(
            check_name="chain_path_clarity",
            passed=False,
            score=0.0,
            details="No chain nodes defined and thesis does not describe any transmission path",
            risk_flags=["UNCLEAR_CHAIN_PATH"],
        )


def _check_upstream_downstream_clarity(target: Any) -> CheckResult:
    """Check that upstream/midstream/downstream relationships are identifiable."""
    thesis = _thesis(target)
    nodes = _chain_nodes(target)

    up_down_kw = {"上游", "upstream", "中游", "midstream", "下游", "downstream",
                  "供应商", "supplier", "客户", "customer", "渠道", "channel"}
    thesis_has_position = any(kw in thesis for kw in up_down_kw)

    # Check if any chain_node contains positional labels
    node_has_position = any(
        any(kw in (str(node) if isinstance(node, str) else str(node.get("label", node)))
            for kw in up_down_kw)
        for node in nodes
    )

    if thesis_has_position or node_has_position:
        # Assess clarity
        clear_indicators = {"上游", "下游", "upstream", "downstream"}
        thesis_clear = any(kw in thesis for kw in clear_indicators)
        nodes_clear = any(
            any(kw in (str(node) if isinstance(node, str) else str(node.get("label", node)))
                for kw in clear_indicators)
            for node in nodes
        )

        if thesis_clear or nodes_clear:
            return CheckResult(
                check_name="upstream_downstream_clarity",
                passed=True,
                score=1.0,
                details="Clear upstream/downstream position identified in thesis or chain nodes",
            )
        else:
            return CheckResult(
                check_name="upstream_downstream_clarity",
                passed=True,
                score=0.5,
                details="Partial supply-chain positioning (related terms present but no explicit upstream/downstream label)",
            )
    else:
        return CheckResult(
            check_name="upstream_downstream_clarity",
            passed=False,
            score=0.0,
            details="No upstream/midstream/downstream relationship identifiable",
            risk_flags=["UNCLEAR_SUPPLY_CHAIN_POSITION"],
        )


def _check_profit_driver_identified(target: Any) -> CheckResult:
    """Check that the thesis identifies what drives profit."""
    thesis = _thesis(target)
    if not thesis:
        return CheckResult(
            check_name="profit_driver_identified",
            passed=False,
            score=0.0,
            details="No thesis provided",
            risk_flags=["PROFIT_DRIVER_UNIDENTIFIED"],
        )

    explicit_kw = (
        "利润", "profit", "revenue", "收入", "margin", "毛利率", "净利率",
        "成本", "cost", "pricing", "定价", "volume", "产能", "价格",
        "营收", "净利润", "营业利润",
    )
    vague_kw = ("增长", "growth", "提升", "改善", "improvement", "expansion")

    has_explicit = any(kw in thesis for kw in explicit_kw)
    has_vague = any(kw in thesis for kw in vague_kw)

    if has_explicit:
        return CheckResult(
            check_name="profit_driver_identified",
            passed=True,
            score=1.0,
            details="Profit driver(s) explicitly identified in thesis",
        )
    elif has_vague:
        return CheckResult(
            check_name="profit_driver_identified",
            passed=True,
            score=0.3,
            details="Thesis references growth/improvement but does not name specific profit drivers",
        )
    else:
        return CheckResult(
            check_name="profit_driver_identified",
            passed=False,
            score=0.0,
            details="No profit driver identified in thesis",
            risk_flags=["PROFIT_DRIVER_UNIDENTIFIED"],
        )


def _check_direction_clarity(target: Any) -> CheckResult:
    """Check that the thesis clearly states impact direction."""
    thesis = _thesis(target)
    if not thesis:
        return CheckResult(
            check_name="direction_clarity",
            passed=False,
            score=0.0,
            details="No thesis provided",
            risk_flags=["UNCLEAR_DIRECTION"],
        )

    explicit_kw = (
        "利好", "利空", "positive", "negative", "受益", "受损",
        "增厚", "摊薄", "提升", "下降", "利多", "利淡",
    )
    ambiguous_kw = ("影响", "impact", "关联", "相关", "关联性", "correlation", "波动", "volatility")

    has_explicit = any(kw in thesis for kw in explicit_kw)
    has_ambiguous = any(kw in thesis for kw in ambiguous_kw)

    if has_explicit:
        return CheckResult(
            check_name="direction_clarity",
            passed=True,
            score=1.0,
            details="Clear impact direction stated in thesis",
        )
    elif has_ambiguous:
        return CheckResult(
            check_name="direction_clarity",
            passed=True,
            score=0.5,
            details="Direction implied but ambiguous (impact/volatility language without sign)",
        )
    else:
        return CheckResult(
            check_name="direction_clarity",
            passed=False,
            score=0.0,
            details="No impact direction identifiable in thesis",
            risk_flags=["UNCLEAR_DIRECTION"],
        )


_GRAND_NARRATIVE_PHRASES = {
    "毫无疑问", "必然", "绝对", "definitely", "always", "never",
    "革命", "颠覆", "revolution", "颠覆性", "重塑",
    "deterministic", "inevitable", "inevitably",
}
_GRAND_NARRATIVE_SUPERLATIVES = {
    "史上", "前所未有", "空前", "unprecedented", "史无前例",
    "彻底", "completely", "entirely",
}


def _check_no_grand_narrative(target: Any) -> CheckResult:
    """Check for over-generalization and grand narrative patterns."""
    thesis = _thesis(target)
    if not thesis:
        return CheckResult(
            check_name="no_grand_narrative",
            passed=True,
            score=1.0,
            details="No thesis provided — cannot assess grand narrative",
        )

    too_long = len(thesis) > 500
    has_absolutes = any(p in thesis for p in _GRAND_NARRATIVE_PHRASES)
    has_superlatives = any(p in thesis for p in _GRAND_NARRATIVE_SUPERLATIVES)

    # Count severity
    flags = sum([too_long, has_absolutes, has_superlatives])

    if flags == 0:
        return CheckResult(
            check_name="no_grand_narrative",
            passed=True,
            score=1.0,
            details="Thesis is measured and specific",
        )
    elif flags == 1:
        # Single minor issue
        issue = "thesis exceeds 500 characters" if too_long else \
                "uses absolute language" if has_absolutes else \
                "uses superlatives"
        return CheckResult(
            check_name="no_grand_narrative",
            passed=True,
            score=0.5,
            details=f"Thesis is mostly measured but {issue}",
        )
    else:
        issues = []
        if too_long:
            issues.append("length > 500 chars")
        if has_absolutes:
            issues.append("absolute/deterministic language")
        if has_superlatives:
            issues.append("excessive superlatives")
        return CheckResult(
            check_name="no_grand_narrative",
            passed=False,
            score=0.0,
            details=f"Thesis exhibits grand narrative patterns: {', '.join(issues)}",
            risk_flags=["GRAND_NARRATIVE"],
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_narrative_checks(target: Any) -> list[CheckResult]:
    """Run all narrative logic checks against a research target.

    Args:
        target: An object with optional attributes:
            .thesis (str), .related_chain_nodes (list).

    Returns:
        list[CheckResult]: Results for all 5 narrative checks.
    """
    return [
        _check_chain_path_clarity(target),
        _check_upstream_downstream_clarity(target),
        _check_profit_driver_identified(target),
        _check_direction_clarity(target),
        _check_no_grand_narrative(target),
    ]
