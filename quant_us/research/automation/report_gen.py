"""Research report generation for strategy candidates.

Provides:
- generate(): Standard report with basic summary.
- generate_v2(): Enhanced report with walk-forward summary, anti-overfit
  findings, structured reject reasons, and next research actions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def generate(
    experiment_id: str, data_root: str = "data", v2: bool = False
) -> str:
    """Generate a research report for an experiment.

    Args:
        experiment_id: The experiment to report on.
        data_root: Data root path.
        v2: If True, generate enhanced v2 report with walk-forward,
            anti-overfit findings, and next actions.

    Returns:
        Markdown report string.

    Raises:
        ValueError: If the experiment is not found.
    """
    if v2:
        return generate_v2(experiment_id, data_root=data_root)
    return _generate_standard(experiment_id, data_root=data_root)


class ExperimentReportGenerator:
    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def generate(self, experiment_id: str) -> dict[str, Any]:
        exp_dir = self.data_root / "research" / "experiments" / experiment_id
        manifest_path = exp_dir / "manifest.json"
        if not manifest_path.exists():
            raise ValueError(f"Experiment {experiment_id} not found")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        candidates_path = exp_dir / "candidates.json"
        candidates = []
        if candidates_path.exists():
            candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
        return {
            "experiment_id": experiment_id,
            "strategy_id": manifest.get("strategy_id", ""),
            "candidate_count": len(candidates),
            "candidates": candidates,
        }


def _generate_standard(experiment_id: str, data_root: str = "data") -> str:
    """Standard report — basic experiment summary."""
    data_path = Path(data_root)
    manifest_path = (
        data_path / "research" / "experiments" / experiment_id / "manifest.json"
    )
    if not manifest_path.exists():
        raise ValueError(f"Experiment {experiment_id} not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    lines = [
        f"# Research Report: {experiment_id}",
        "",
        f"**Strategy:** {manifest.get('strategy_id', 'unknown')}  ",
        f"**Status:** {manifest.get('status', 'UNKNOWN')}  ",
        f"**Created:** {manifest.get('created_at', 'unknown')}  ",
        "",
    ]

    metrics = manifest.get("metrics", {})
    if metrics:
        lines.append("## Metrics\n")
        lines.append("| Metric | Value |\n|--------|-------|\n")
        for key, value in sorted(metrics.items()):
            if isinstance(value, float):
                lines.append(f"| {key} | {value:.4f} |\n")
            else:
                lines.append(f"| {key} | {value} |\n")

    return "".join(lines)


def generate_v2(experiment_id: str, data_root: str = "data") -> str:
    """Enhanced v2 report with full analysis sections.

    Sections:
    1. Experiment summary
    2. Candidate scorecards
    3. Walk-forward summary
    4. Anti-overfit findings
    5. Promotion gate evaluation
    6. "Ready for Paper Review" summary table
    7. Next research actions
    """
    data_path = Path(data_root)
    manifest_path = (
        data_path / "research" / "experiments" / experiment_id / "manifest.json"
    )
    if not manifest_path.exists():
        raise ValueError(f"Experiment {experiment_id} not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Find candidates linked to this experiment
    candidate_ids = _find_candidates_for_experiment(experiment_id, data_root)

    sections: list[str] = [
        f"# Research Report v2: {experiment_id}",
        "",
        _v2_header(manifest),
        "",
        _v2_experiment_summary(manifest),
        "",
    ]

    # Section 2: Candidate scorecards
    scorecards = _load_scorecards(candidate_ids, data_root)
    sections.append(_v2_candidate_section(scorecards))
    sections.append("")

    # Section 3: Walk-forward summary
    sections.append(_v2_walk_forward_section(scorecards))
    sections.append("")

    # Section 4: Anti-overfit findings
    sections.append(_v2_anti_overfit_section(candidate_ids, data_root))
    sections.append("")

    # Section 5: Validation statistics
    gate_results = _evaluate_promotion_gate(candidate_ids, data_root)
    sections.append(_v2_validation_section(gate_results))
    sections.append("")

    # Section 6: Promotion gate results
    sections.append(_v2_gate_section(gate_results))
    sections.append("")

    # Section 7: Unified backtest evidence summary
    sections.append(_v2_backtest_evidence_section(gate_results))
    sections.append("")

    # Section 8: Ready for paper review summary
    sections.append(_v2_ready_summary(gate_results))
    sections.append("")

    # Section 9: Next research actions
    sections.append(_v2_next_actions(gate_results))
    sections.append("")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _v2_header(manifest: dict) -> str:
    return (
        f"**Strategy:** {manifest.get('strategy_id', 'unknown')}  \n"
        f"**Status:** {manifest.get('status', 'UNKNOWN')}  \n"
        f"**Created:** {manifest.get('created_at', 'unknown')}  \n"
        f"**Symbols:** {', '.join(manifest.get('symbols', [])) or 'N/A'}  \n"
    )


def _v2_experiment_summary(manifest: dict) -> str:
    lines = [
        "## Experiment Summary\n",
        "| Field | Value |\n|-------|-------|\n",
        f"| Experiment ID | {manifest.get('experiment_id', '?')} |\n",
        f"| Strategy Family | {manifest.get('strategy_family', 'N/A')} |\n",
        f"| Data Version | {manifest.get('data_version', 'N/A')} |\n",
        f"| Date Range | {manifest.get('start_date', '?')} -> {manifest.get('end_date', '?')} |\n",
        f"| Cost Model | {manifest.get('cost_model', 'default')} |\n",
        f"| Walk Forward Config | {json.dumps(manifest.get('walk_forward_config', {}))} |\n",
    ]

    metrics = manifest.get("metrics", {})
    if metrics:
        lines.append("\n### Metrics\n\n| Metric | Value |\n|--------|-------|\n")
        for key, value in sorted(metrics.items()):
            if isinstance(value, float):
                lines.append(f"| {key} | {value:.4f} |\n")
            else:
                lines.append(f"| {key} | {value} |\n")

    return "".join(lines)


def _v2_candidate_section(scorecards: list[dict]) -> str:
    if not scorecards:
        return "## Candidate Scorecards\n\nNo candidates found.\n"

    lines = [
        "## Candidate Scorecards\n",
        "| Candidate | Sharpe | CAGR | MaxDD | OOS Deg | WFR | Overfit | Robust |\n",
        "|-----------|--------|------|-------|---------|-----|---------|--------|\n",
    ]
    for sc in scorecards:
        lines.append(
            f"| {sc.get('candidate_id', '?')[:16]} "
            f"| {sc.get('sharpe', 0.0):.2f} "
            f"| {sc.get('cagr', 0.0):.2%} "
            f"| {sc.get('max_drawdown', 0.0):.2%} "
            f"| {sc.get('oos_degradation', 0.0):.2%} "
            f"| {sc.get('walk_forward_pass_rate', 0.0):.2%} "
            f"| {sc.get('overfit_risk', '?'):8s} "
            f"| {sc.get('robustness_score', 0.0):.2f} |\n"
        )
    return "".join(lines)


def _v2_walk_forward_section(scorecards: list[dict]) -> str:
    if not scorecards:
        return "## Walk-Forward Summary\n\nNo candidates to evaluate.\n"

    lines = [
        "## Walk-Forward Summary\n",
        "| Candidate | WFR Pass Rate | OOS Degradation | Stability Score |\n",
        "|-----------|---------------|-----------------|-----------------|\n",
    ]
    for sc in scorecards:
        lines.append(
            f"| {sc.get('candidate_id', '?')[:16]} "
            f"| {sc.get('walk_forward_pass_rate', 0.0):.2%} "
            f"| {sc.get('oos_degradation', 0.0):.2%} "
            f"| {sc.get('stability_score', 0.0):.2f} |\n"
        )
    return "".join(lines)


def _v2_anti_overfit_section(
    candidate_ids: list[str], data_root: str
) -> str:
    if not candidate_ids:
        return "## Anti-Overfit Findings\n\nNo candidates to evaluate.\n"

    from quant_us.research.automation.overfit import OverfitDetector

    detector = OverfitDetector(data_root=data_root)

    lines = [
        "## Anti-Overfit Findings\n",
        "| Candidate | Overfit | Degradation | Param Sens | Year Conc | Sym Conc | Reasons |\n",
        "|-----------|---------|-------------|------------|-----------|----------|--------|\n",
    ]

    for cid in candidate_ids:
        try:
            report = detector.check(cid)
            reasons_summary = "; ".join(report.reasons[:2])
            if len(report.reasons) > 2:
                reasons_summary += f" ... (+{len(report.reasons) - 2} more)"
            lines.append(
                f"| {cid[:16]} "
                f"| {'YES' if report.is_overfit else 'no':7s} "
                f"| {report.degradation_pct:.1%} "
                f"| {report.param_sensitivity:.3f} "
                f"| {report.single_year_concentration:.1%} "
                f"| {report.single_symbol_concentration:.1%} "
                f"| {reasons_summary or 'none'} |\n"
            )
        except ValueError:
            lines.append(f"| {cid[:16]} | ERROR | - | - | - | - | not found |\n")

    return "".join(lines)


def _v2_gate_section(
    gate_results: list[dict],
) -> str:
    if not gate_results:
        return "## Promotion Gate\n\nNo candidates evaluated.\n"

    lines = [
        "## Promotion Gate Evaluation\n",
        "| Candidate | Decision | Reasons | Warnings |\n",
        "|-----------|----------|---------|----------|\n",
    ]
    for gr in gate_results:
        reasons = "; ".join(gr.get("reasons", [])[:2]) or "none"
        warnings = "; ".join(gr.get("warnings", [])[:2]) or "none"
        lines.append(
            f"| {gr.get('candidate_id', '?')[:16]} "
            f"| {gr.get('decision', '?'):25s} "
            f"| {reasons} "
            f"| {warnings} |\n"
        )
    return "".join(lines)


def _v2_validation_section(gate_results: list[dict]) -> str:
    if not gate_results:
        return "## Validation Statistics\n\nNo candidates evaluated.\n"

    lines = [
        "## Validation Statistics\n",
        "| Candidate | CV Method | Trials | DSR | PBO | Cost Drag | Validation Status |\n",
        "|-----------|-----------|--------|-----|-----|-----------|-------------------|\n",
    ]
    for gr in gate_results:
        evidence = gr.get("evidence", {}) if isinstance(gr, dict) else {}
        if not isinstance(evidence, dict):
            evidence = {}
        validation = evidence.get("validation_stats", {})
        if not isinstance(validation, dict):
            validation = {}
        cv_summary = validation.get("cv_summary", {})
        trial_counting = validation.get("trial_counting", {})
        dsr = validation.get("deflated_sharpe_ratio", {})
        pbo = validation.get("pbo", {})
        cost_before_after = validation.get("cost_before_after", {})
        cost_drag = cost_before_after.get("cost_drag_return")
        lines.append(
            f"| {gr.get('candidate_id', '?')[:16]} "
            f"| {cv_summary.get('method', 'unknown')} "
            f"| {trial_counting.get('effective_trial_count', 0)} "
            f"| {_format_optional_number(dsr.get('dsr'), digits=3)} "
            f"| {_format_optional_number(pbo.get('pbo'), digits=3)} "
            f"| {_format_optional_number(cost_drag, digits=4)} "
            f"| {validation.get('status', 'partial')} |\n"
        )
    return "".join(lines)


def _v2_backtest_evidence_section(gate_results: list[dict]) -> str:
    if not gate_results:
        return "## Unified Backtest Evidence\n\nNo candidates evaluated.\n"

    lines = [
        "## Unified Backtest Evidence\n",
    ]
    for gr in gate_results:
        evidence = gr.get("evidence", {}) if isinstance(gr, dict) else {}
        if not isinstance(evidence, dict):
            evidence = {}

        reconciliation = _extract_reconciliation_evidence(evidence)
        corporate_actions = _extract_corporate_actions_evidence(evidence)

        lines.extend(
            [
                f"### {gr.get('candidate_id', '?')}\n",
                f"- Reconciliation Passed: {_format_bool(reconciliation.get('passed'))}\n",
                f"- Max Abs Diff: {_format_number(reconciliation.get('max_abs_diff'))}\n",
                f"- Max Pct Diff: {_format_number(reconciliation.get('max_pct_diff'))}\n",
                f"- Failed Snapshot Summary: {reconciliation.get('failed_snapshot_summary', 'none')}\n",
                f"- Corporate Actions Digest: {corporate_actions}\n",
                "\n",
            ]
        )
    return "".join(lines)


def _v2_ready_summary(gate_results: list[dict]) -> str:
    """Summary table showing which candidates are Ready for Paper Review."""
    ready = [
        g for g in gate_results if g.get("decision") == "READY_FOR_PAPER_REVIEW"
    ]
    blocked = [g for g in gate_results if g.get("decision") == "BLOCKED"]
    watchlist = [g for g in gate_results if g.get("decision") == "WATCHLIST"]

    lines = [
        "## \"Ready for Paper Review\" Summary\n",
        f"**Total evaluated:** {len(gate_results)}  \n",
        f"**READY_FOR_PAPER_REVIEW:** {len(ready)}  \n",
        f"**WATCHLIST:** {len(watchlist)}  \n",
        f"**BLOCKED:** {len(blocked)}  \n",
        "",
    ]

    if ready:
        lines.append("### Ready for Human Review\n")
        lines.append("| Candidate |\n|-----------|\n")
        for g in ready:
            lines.append(f"| {g.get('candidate_id', '?')} |\n")
        lines.append(
            "\n*These candidates are ready for HUMAN paper-review evaluation. "
            "No automatic promotion to paper trading occurs.*\n"
        )

    return "".join(lines)


def _v2_next_actions(gate_results: list[dict]) -> str:
    """Generate next research actions based on gate evaluation."""
    blocked = [g for g in gate_results if g.get("decision") == "BLOCKED"]
    watchlist = [g for g in gate_results if g.get("decision") == "WATCHLIST"]
    ready = [
        g for g in gate_results if g.get("decision") == "READY_FOR_PAPER_REVIEW"
    ]

    lines = [
        "## Next Research Actions\n",
    ]

    if blocked:
        b_ids = ", ".join(g.get("candidate_id", "?")[:16] for g in blocked)
        lines.append(
            f"1. **Review blocked candidates** ({b_ids}): "
            f"Address blocking issues before re-evaluation.\n"
        )

    if watchlist:
        w_ids = ", ".join(g.get("candidate_id", "?")[:16] for g in watchlist)
        lines.append(
            f"2. **Investigate watchlist candidates** ({w_ids}): "
            f"Run walk-forward analysis or gather more trade data.\n"
        )

    if ready:
        r_ids = ", ".join(g.get("candidate_id", "?")[:16] for g in ready)
        lines.append(
            f"3. **Submit for human review** ({r_ids}): "
            f"Generate dossier and escalate to paper review pool.\n"
        )

    lines.append(
        "4. **NOTE**: READY_FOR_PAPER_REVIEW does NOT enter paper trading. "
        "It only enters the human review pool.\n"
    )

    if not any([blocked, watchlist, ready]):
        lines.append("No candidates evaluated. No actions needed.\n")

    return "".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_candidates_for_experiment(
    experiment_id: str, data_root: str
) -> list[str]:
    """Find all candidate IDs linked to an experiment."""
    data_path = Path(data_root)
    candidates_dir = data_path / "research" / "candidates"
    if not candidates_dir.exists():
        return []

    ids: list[str] = []
    for d in sorted(candidates_dir.iterdir()):
        if not d.is_dir():
            continue
        cand_path = d / "candidate.json"
        if not cand_path.exists():
            continue
        try:
            data = json.loads(cand_path.read_text(encoding="utf-8"))
            if data.get("experiment_id") == experiment_id:
                ids.append(data.get("candidate_id", d.name))
        except (json.JSONDecodeError, OSError):
            continue
    return ids


def _load_scorecards(
    candidate_ids: list[str], data_root: str
) -> list[dict]:
    """Load persisted scorecards for the given candidate IDs."""
    data_path = Path(data_root)
    scorecards_dir = data_path / "research" / "scorecards"
    scorecards: list[dict] = []

    for cid in candidate_ids:
        path = scorecards_dir / f"{cid}.json"
        if path.exists():
            try:
                scorecards.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
    return scorecards


def _evaluate_promotion_gate(
    candidate_ids: list[str], data_root: str
) -> list[dict]:
    """Run promotion gate evaluation for all candidates."""
    from quant_us.research.automation.promotion_gate import (
        ResearchPromotionGate,
    )

    gate = ResearchPromotionGate(data_root=data_root)
    results: list[dict] = []
    for cid in candidate_ids:
        try:
            result = gate.evaluate(cid)
            results.append(
                {
                    "candidate_id": result.candidate_id,
                    "decision": result.decision,
                    "reasons": result.reasons,
                    "warnings": result.warnings,
                    "evidence": result.evidence,
                }
            )
        except (ValueError, FileNotFoundError, json.JSONDecodeError):
            continue
    return results


def _extract_reconciliation_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    reconciliation = evidence.get("reconciliation")
    if isinstance(reconciliation, dict):
        summary = reconciliation.get("summary", {})
        snapshots = reconciliation.get("snapshots", [])
    else:
        summary = evidence.get("reconciliation_summary", {})
        snapshots = evidence.get("reconciliation_snapshots", [])

    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(snapshots, list):
        snapshots = []

    failed_summary = evidence.get("reconciliation_failed_snapshot_summary", "none")
    if failed_summary == "none":
        failed_snapshots = [
            snap for snap in snapshots if _coerce_bool(snap.get("passed", False)) is not True
        ]
        failed_summary = _summarize_failed_snapshot_list(failed_snapshots)

    return {
        "passed": summary.get("passed"),
        "max_abs_diff": summary.get("max_abs_diff"),
        "max_pct_diff": summary.get("max_pct_diff"),
        "failed_snapshot_summary": failed_summary,
    }


def _extract_corporate_actions_evidence(evidence: dict[str, Any]) -> str:
    corporate_actions = evidence.get("corporate_actions")
    if isinstance(corporate_actions, dict):
        digest = corporate_actions.get("digest", {})
        if isinstance(digest, dict):
            return _format_digest(digest)

    digest = evidence.get("corporate_actions_digest", {})
    if isinstance(digest, dict):
        return _format_digest(digest)
    return "none"


def _format_bool(value: Any) -> str:
    coerced = _coerce_bool(value)
    if coerced is None:
        return "N/A"
    return "True" if coerced else "False"


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "passed", "pass"}:
            return True
        if normalized in {"0", "false", "no", "n", "failed", "fail"}:
            return False
        return None
    return bool(value)


def _format_number(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def _format_optional_number(value: Any, *, digits: int) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _format_digest(digest: dict[str, Any]) -> str:
    if not digest:
        return "none"

    preferred_keys = [
        "adjustment_count",
        "split_event_count",
        "total_dividends",
        "total_borrow_fees",
        "total_corporate_adjustments",
    ]
    parts: list[str] = []
    seen: set[str] = set()

    for key in preferred_keys:
        if key in digest:
            parts.append(f"{key}={_format_digest_value(digest.get(key))}")
            seen.add(key)

    for key in sorted(digest):
        if key in seen:
            continue
        parts.append(f"{key}={_format_digest_value(digest.get(key))}")

    return ", ".join(parts) if parts else "none"


def _format_digest_value(value: Any) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return str(value)
    return _format_number(value)


def _summarize_failed_snapshot_list(snapshots: list[dict[str, Any]]) -> str:
    if not snapshots:
        return "none"

    first = snapshots[0]
    timestamp = first.get("timestamp_utc", "unknown")
    cash_diff = first.get("cash_diff")
    equity_diff = first.get("equity_diff")
    max_abs_diff = first.get("max_abs_diff")
    max_pct_diff = first.get("max_pct_diff")
    return (
        f"count={len(snapshots)}; first={timestamp}; "
        f"cash_diff={_format_number(cash_diff)}; "
        f"equity_diff={_format_number(equity_diff)}; "
        f"max_abs_diff={_format_number(max_abs_diff)}; "
        f"max_pct_diff={_format_number(max_pct_diff)}"
    )
