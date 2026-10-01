"""runner.py — Alpha Radar Research Audit Orchestrator

Unified entry point that coordinates the full audit pipeline:

    1. Run evidence chain checks
    2. Run signal quality checks
    3. Run narrative logic checks
    4. Run cognitive bias checks
    5. Compute dimension and composite scores
    6. Determine audit status via promotion gate
    7. Generate JSON and Markdown reports
    8. Persist to disk if a persist_dir is given
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import (
    evidence_check,
    signal_check,
    narrative_check,
    bias_check,
    promotion_gate,
    report as report_mod,
)
from .schemas import ResearchAuditTarget, ResearchAuditResult
from .scoring import CheckResult, compute_dimension_score, compute_audit_score

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DIMENSION_NAMES = ("evidence", "signal", "narrative", "bias")


def _normalize_evidence_for_checks(target: ResearchAuditTarget) -> None:
    """Convert EvidenceItem dataclass objects to plain dicts in-place.

    Check modules expect evidence items as dicts (``item.get(...)``).
    This mutates the target (idempotent — only converts dataclass instances).
    """
    items = target.evidence_items
    if items and hasattr(items[0], "__dataclass_fields__"):
        target.evidence_items = [
            {f.name: getattr(item, f.name) for f in item.__dataclass_fields__.values()}
            for item in items
        ]


def _collect_failures_and_flags(
    all_checks: list[CheckResult],
) -> tuple[list[str], list[str], list[str]]:
    """Aggregate passed/failed check names, risk flags, and warnings.

    Returns:
        (passed_checks, failed_checks, all_risk_flags, warnings)
    """
    passed: list[str] = []
    failed: list[str] = []
    risk_flags: list[str] = []
    warnings: list[str] = []

    for c in all_checks:
        if c.passed:
            passed.append(c.check_name)
        else:
            failed.append(c.check_name)

        risk_flags.extend(c.risk_flags)

        if not c.passed:
            warnings.append(
                f"{c.check_name}: {c.details}"
            )
        elif c.score < 0.6:
            warnings.append(
                f"{c.check_name}: passed but low quality (score={c.score:.2f}) — {c.details}"
            )

    return passed, failed, risk_flags, warnings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_research_audit(
    target: ResearchAuditTarget,
    persist_dir: str | None = None,
) -> ResearchAuditResult:
    """Run the full research credibility audit on a target.

    The audit evaluates evidence chain integrity, signal quality, narrative
    logic, and cognitive bias exposure, producing a composite score (0-100)
    and a status classification.

    Args:
        target:     The research target to audit.
        persist_dir: Optional directory path to persist the JSON report.
                     If provided, the directory is created (if needed) and
                     the report is written as ``{persist_dir}/{audit_id}.json``.

    Returns:
        A fully populated ResearchAuditResult with scores, status, checks,
        risk flags, warnings, and both JSON and Markdown reports.
    """
    # Generate identifiers
    audit_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    # ---- 0. Normalize evidence items to dicts for check modules ----
    _normalize_evidence_for_checks(target)

    # ---- 1-4. Run all check modules ----
    ev_checks = evidence_check.run_evidence_checks(target)
    sg_checks = signal_check.run_signal_checks(target)
    nr_checks = narrative_check.run_narrative_checks(target)
    bi_checks = bias_check.run_bias_checks(target)

    all_checks = ev_checks + sg_checks + nr_checks + bi_checks

    # ---- 5. Compute scores ----
    ev_score = compute_dimension_score(ev_checks)
    sg_score = compute_dimension_score(sg_checks)
    nr_score = compute_dimension_score(nr_checks)
    bi_score = compute_dimension_score(bi_checks)

    audit_score = compute_audit_score(ev_score, sg_score, nr_score, bi_score)

    # ---- 6. Aggregate failures, flags, warnings ----
    passed_checks, failed_checks, risk_flags, warnings = _collect_failures_and_flags(all_checks)

    # ---- 7. Determine audit status ----
    status = promotion_gate.determine_status(
        evidence_score=ev_score,
        signal_score=sg_score,
        narrative_score=nr_score,
        bias_score=bi_score,
        failed_checks=failed_checks,
        warnings=warnings,
    )

    # ---- 8. Build result object (partial — report to follow) ----
    result = ResearchAuditResult(
        audit_id=audit_id,
        target_type=target.target_type,
        target_id=target.target_id,
        audit_score=audit_score,
        audit_status=status,
        risk_flags=risk_flags,
        passed_checks=passed_checks,
        failed_checks=failed_checks,
        warnings=warnings,
        evidence_score=ev_score,
        signal_score=sg_score,
        narrative_score=nr_score,
        bias_score=bi_score,
        created_at=created_at,
    )

    # ---- 9. Generate reports ----
    report_json, report_md = report_mod.generate_report(
        target, result,
        ev_checks, sg_checks, nr_checks, bi_checks,
    )
    result.report_json = report_json
    result.report_markdown = report_md

    # ---- 10. Persist (optional) ----
    if persist_dir:
        persist_path = Path(persist_dir)
        persist_path.mkdir(parents=True, exist_ok=True)
        out_file = persist_path / f"{audit_id}.json"
        out_file.write_text(
            json.dumps(report_json, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    return result
