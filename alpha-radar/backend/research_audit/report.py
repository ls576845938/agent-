"""report.py — Research Audit Report Generation

Produces structured JSON and human-readable Markdown reports summarising
all check results, dimension scores, risk flags, and the final audit
status recommendation.
"""

from typing import Any

from .schemas import ResearchAuditTarget, ResearchAuditResult
from .scoring import CheckResult


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------

def _check_to_dict(c: CheckResult) -> dict[str, Any]:
    return {
        "check_name": c.check_name,
        "passed": c.passed,
        "score": c.score,
        "details": c.details,
        "risk_flags": list(c.risk_flags),
    }


def _build_report_json(
    target: ResearchAuditTarget,
    result: ResearchAuditResult,
    evidence_checks: list[CheckResult],
    signal_checks: list[CheckResult],
    narrative_checks: list[CheckResult],
    bias_checks: list[CheckResult],
) -> dict[str, Any]:
    return {
        "audit_id": result.audit_id,
        "created_at": result.created_at,
        "target": {
            "type": target.target_type,
            "id": target.target_id,
            "title": target.title,
            "thesis": target.thesis,
            "symbols": list(target.related_symbols),
            "industries": list(target.related_industries),
            "chain_nodes": list(target.related_chain_nodes),
        },
        "scores": {
            "overall": result.audit_score,
            "evidence": result.evidence_score,
            "signal": result.signal_score,
            "narrative": result.narrative_score,
            "bias": result.bias_score,
        },
        "status": result.audit_status,
        "checks": {
            "passed": list(result.passed_checks),
            "failed": list(result.failed_checks),
        },
        "risk_flags": list(result.risk_flags),
        "warnings": list(result.warnings),
        "dimensions": {
            "evidence": [_check_to_dict(c) for c in evidence_checks],
            "signal": [_check_to_dict(c) for c in signal_checks],
            "narrative": [_check_to_dict(c) for c in narrative_checks],
            "bias": [_check_to_dict(c) for c in bias_checks],
        },
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def _dimension_table_row(name: str, score: float, max_val: float = 1.0) -> str:
    bar_len = 20
    filled = int(round(score / max_val * bar_len))
    bar = "|" * filled + "." * (bar_len - filled)
    return f"| {name:<12} | {score:<8.4f} | {bar} |"


def _build_report_markdown(
    target: ResearchAuditTarget,
    result: ResearchAuditResult,
    evidence_checks: list[CheckResult],
    signal_checks: list[CheckResult],
    narrative_checks: list[CheckResult],
    bias_checks: list[CheckResult],
) -> str:
    lines: list[str] = []

    # ---- Header ----
    lines.append("# Research Audit Report")
    lines.append("")
    lines.append(f"**Target:** {target.title or target.target_id}")
    lines.append(f"**Type:** `{target.target_type}`  |  **ID:** `{target.target_id}`")
    lines.append(f"**Audit ID:** `{result.audit_id}`")
    lines.append(f"**Created:** {result.created_at}")
    lines.append("")
    lines.append(f"**Status:** `{result.audit_status}`")
    lines.append(f"**Overall Score:** **{result.audit_score}/100**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- 1. Evidence Chain ----
    lines.append("## 1. Evidence Chain")
    lines.append("")
    for c in evidence_checks:
        status_mark = "[PASS]" if c.passed else "[FAIL]"
        lines.append(f"- {status_mark} **{c.check_name}** (score={c.score:.2f}) — {c.details}")
    lines.append("")

    # ---- 2. Signal Quality ----
    lines.append("## 2. Signal Quality")
    lines.append("")
    for c in signal_checks:
        status_mark = "[PASS]" if c.passed else "[FAIL]"
        lines.append(f"- {status_mark} **{c.check_name}** (score={c.score:.2f}) — {c.details}")
    lines.append("")

    # ---- 3. Narrative Logic ----
    lines.append("## 3. Narrative Logic")
    lines.append("")
    for c in narrative_checks:
        status_mark = "[PASS]" if c.passed else "[FAIL]"
        lines.append(f"- {status_mark} **{c.check_name}** (score={c.score:.2f}) — {c.details}")
    lines.append("")

    # ---- 4. Bias Assessment ----
    lines.append("## 4. Bias Assessment")
    lines.append("")
    for c in bias_checks:
        status_mark = "[PASS]" if c.passed else "[FAIL]"
        lines.append(f"- {status_mark} **{c.check_name}** (score={c.score:.2f}) — {c.details}")
    lines.append("")

    # ---- 5. Overall Score ----
    lines.append("## 5. Overall Score")
    lines.append("")
    lines.append("| Dimension      | Score      | Distribution        |")
    lines.append("|---------------|------------|---------------------|")
    lines.append(_dimension_table_row("Evidence", result.evidence_score))
    lines.append(_dimension_table_row("Signal", result.signal_score))
    lines.append(_dimension_table_row("Narrative", result.narrative_score))
    lines.append(_dimension_table_row("Bias", result.bias_score))
    lines.append(f"| **Composite** | **{result.audit_score:<8.2f}** | **{'█' * int(result.audit_score // 5):20}** |")
    lines.append("")

    # ---- 6. Risk Flags ----
    if result.risk_flags:
        lines.append("## 6. Risk Flags")
        lines.append("")
        for flag in result.risk_flags:
            lines.append(f"- `{flag}`")
        lines.append("")

    # ---- 7. Warnings ----
    if result.warnings:
        lines.append("## 7. Warnings")
        lines.append("")
        for w in result.warnings:
            lines.append(f"- {w}")
        lines.append("")

    # ---- 8. Recommendation ----
    lines.append("## 8. Recommendation")
    lines.append("")
    rec = _recommendation(result.audit_status, result.audit_score, result.risk_flags)
    lines.append(rec)
    lines.append("")

    return "\n".join(lines)


def _recommendation(status: str, score: float, risk_flags: list[str]) -> str:
    if status == "BLOCKED":
        return (
            "**Do not act on this research.** Critical evidence gaps or fundamental "
            "credibility failures must be resolved before further consideration. "
            "Address the flagged evidence deficiencies and re-audit."
        )
    if status == "WATCHLIST":
        return (
            f"Research quality is below research-ready threshold (score={score:.1f}). "
            "Consider gathering more evidence and refining the thesis before basing "
            "portfolio decisions on this analysis."
        )
    if status == "NEED_MORE_EVIDENCE":
        return (
            "The thesis logic and signal construction appear reasonable, but the "
            "evidence base is insufficient. Strengthen the evidence chain with "
            "additional independent sources before proceeding."
        )
    if status == "RESEARCH_READY":
        return (
            f"Research meets minimum credibility standards (score={score:.1f}). "
            "Suitable for consideration in portfolio decisions, but continue "
            "monitoring for emerging counter-evidence."
        )
    if status == "HIGH_CONVICTION":
        return (
            f"Research demonstrates high credibility across all dimensions "
            f"(score={score:.1f}). Strong confidence in the thesis quality "
            "and evidence integrity."
        )
    return f"Audit status '{status}' — review the detailed checks above."


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_report(
    target: ResearchAuditTarget,
    result: ResearchAuditResult,
    evidence_checks: list[CheckResult],
    signal_checks: list[CheckResult],
    narrative_checks: list[CheckResult],
    bias_checks: list[CheckResult],
) -> tuple[dict[str, Any], str]:
    """Generate both JSON and Markdown reports for a completed audit.

    Args:
        target: The research target that was audited.
        result: The completed audit result (scores, status, flags).
        evidence_checks: All evidence-dimension check results.
        signal_checks: All signal-dimension check results.
        narrative_checks: All narrative-dimension check results.
        bias_checks: All bias-dimension check results.

    Returns:
        Tuple of (report_json: dict, report_markdown: str).
    """
    report_json = _build_report_json(
        target, result,
        evidence_checks, signal_checks, narrative_checks, bias_checks,
    )
    report_md = _build_report_markdown(
        target, result,
        evidence_checks, signal_checks, narrative_checks, bias_checks,
    )
    return report_json, report_md
