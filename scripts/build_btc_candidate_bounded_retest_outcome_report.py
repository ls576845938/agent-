#!/usr/bin/env python3
"""Build a read-only BTC bounded retest outcome report."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
DEFAULT_RUN_DIR = Path("artifacts/btc_canonical/20260604T132400Z_okx_bounded_retest")
RESULTS_FILE = "btc_perp_dual_trend_v4_eventpf_wf_results.json"
CANONICAL_REPORT = "btc_perp_dual_trend_v4_eventpf_wf/canonical_backtest_report.json"
PROMOTION_DECISION = "promotion_decision.json"
SAFETY_STATUS = "paper_live_safety_status.json"
RUN_MANIFEST = "run_manifest.json"


def build_btc_candidate_bounded_retest_outcome_report(
    *,
    repo_root: Path | None = None,
    run_dir: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    selected_run_dir = _resolve(root, run_dir or DEFAULT_RUN_DIR)
    results_path = selected_run_dir / RESULTS_FILE
    canonical_path = selected_run_dir / CANONICAL_REPORT
    promotion_path = selected_run_dir / PROMOTION_DECISION
    safety_path = selected_run_dir / SAFETY_STATUS
    manifest_path = selected_run_dir / RUN_MANIFEST

    results = _read_json(results_path)
    canonical = _read_json(canonical_path)
    promotion = _read_json(promotion_path)
    safety = _read_json(safety_path)
    manifest = _read_json(manifest_path)

    result_report = _mapping(results.get("v4_report"))
    canonical_metrics = _mapping(canonical.get("metrics"))
    gate_decision = _mapping(result_report.get("gate_decision") or canonical.get("gate_decision"))
    checks = _mapping(gate_decision.get("checks"))
    thresholds = _mapping(gate_decision.get("thresholds"))
    failed_metrics = _failed_metrics(results, canonical, gate_decision)
    candidate_passed = bool(gate_decision.get("passed", False))
    complete = all(path.exists() for path in [results_path, canonical_path, promotion_path, safety_path, manifest_path])
    unsafe = _safety_unsafe(safety=safety, promotion=promotion)
    status = _status(complete=complete, candidate_passed=candidate_passed, unsafe=unsafe)
    blockers = _blockers(status=status, failed_metrics=failed_metrics, complete=complete, unsafe=unsafe)

    return {
        "schema_version": "btc_candidate_bounded_retest_outcome_report_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "run_id": str(manifest.get("run_id") or results.get("run_id") or selected_run_dir.name),
        "run_dir": _relpath(selected_run_dir, root),
        "status": status,
        "candidate_gate_passed": candidate_passed,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "same_retest_repeat_allowed": False,
        "next_required_action": _next_required_action(status=status, failed_metrics=failed_metrics),
        "source_artifacts": {
            "run_manifest": _relpath(manifest_path, root) if manifest_path.exists() else None,
            "results": _relpath(results_path, root) if results_path.exists() else None,
            "canonical_backtest_report": _relpath(canonical_path, root) if canonical_path.exists() else None,
            "promotion_decision": _relpath(promotion_path, root) if promotion_path.exists() else None,
            "paper_live_safety_status": _relpath(safety_path, root) if safety_path.exists() else None,
        },
        "manifest_contract": {
            "run_manifest_exists": manifest_path.exists(),
            "schema_version": manifest.get("schema_version"),
            "code_commit_present": bool(manifest.get("code_commit")),
            "artifact_paths_count": len(manifest.get("artifact_paths", [])) if isinstance(manifest.get("artifact_paths"), list) else 0,
        },
        "metrics": {
            "event_profit_factor": _float_or_none(result_report.get("event_PF", canonical_metrics.get("event_profit_factor"))),
            "walk_forward_pass_rate": _float_or_none(result_report.get("walk_forward_pass_rate", canonical_metrics.get("walk_forward_pass_rate"))),
            "regime_pass_rate": _float_or_none(result_report.get("regime_pass_rate", canonical_metrics.get("regime_pass_rate"))),
            "ordinary_profit_factor": _float_or_none(result_report.get("PF", canonical_metrics.get("profit_factor"))),
            "max_drawdown": _float_or_none(result_report.get("MDD", canonical_metrics.get("max_drawdown"))),
            "trade_count": _int_or_none(result_report.get("trade_count", canonical_metrics.get("trade_count"))),
            "fill_count": _int_or_none(result_report.get("fill_count", canonical_metrics.get("fill_count"))),
            "cost_stress_base_pass": bool(checks.get("cost_stress_base", canonical_metrics.get("cost_stress_base_pass", False))),
            "cost_stress_harsh_pass": bool(checks.get("cost_stress_harsh", canonical_metrics.get("cost_stress_harsh_survives", False))),
        },
        "thresholds": {
            "event_profit_factor": _float_or_none(thresholds.get("event_profit_factor")),
            "walk_forward_pass_rate": _float_or_none(thresholds.get("walk_forward_pass_rate")),
            "regime_pass_rate": _float_or_none(thresholds.get("regime_pass_rate")),
        },
        "failed_metrics": failed_metrics,
        "gate_checks": {
            "event_profit_factor": bool(checks.get("event_profit_factor", False)),
            "walk_forward_pass_rate": bool(checks.get("walk_forward_pass_rate", False)),
            "regime_pass_rate": bool(checks.get("regime_pass_rate", False)),
            "cost_stress_base": bool(checks.get("cost_stress_base", False)),
            "cost_stress_harsh": bool(checks.get("cost_stress_harsh", False)),
            "event_ledger": bool(checks.get("event_ledger", False)),
        },
        "safety": {
            "paper_queue_status": str(safety.get("paper_queue_status", "LOCKED")),
            "paper_review_queue_locked": bool(safety.get("paper_review_queue_locked", True)),
            "paper_auto_start": bool(safety.get("paper_auto_start", False)),
            "live_status": str(safety.get("live_status", "FROZEN")),
            "live_frozen": bool(safety.get("live_frozen", True)),
            "real_broker_api_called": bool(safety.get("real_broker_api_called", False)),
            "real_orders_created": bool(safety.get("real_orders_created", False)),
            "paper_or_live_unlock_allowed": False,
        },
        "blockers": blockers,
    }


def write_btc_candidate_bounded_retest_outcome_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "candidate_bounded_retest_outcome_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_candidate_bounded_retest_outcome_report(
        repo_root=Path(args.repo_root),
        run_dir=Path(args.run_dir),
        generated_at=args.generated_at or None,
    )
    print(write_btc_candidate_bounded_retest_outcome_report(payload, Path(args.output_root)))


def _status(*, complete: bool, candidate_passed: bool, unsafe: bool) -> str:
    if unsafe:
        return "unsafe_retest_output"
    if not complete:
        return "missing_retest_output"
    return "completed_candidate_gate_passed" if candidate_passed else "completed_candidate_gate_failed"


def _blockers(*, status: str, failed_metrics: list[str], complete: bool, unsafe: bool) -> list[str]:
    blockers: list[str] = []
    if not complete:
        blockers.append("btc_candidate_bounded_retest_output_missing")
    if unsafe:
        blockers.append("btc_candidate_bounded_retest_output_unsafe")
    if status == "completed_candidate_gate_failed":
        blockers.extend(f"btc_candidate_bounded_retest_{metric}_failed" for metric in failed_metrics)
    return _dedupe(blockers)


def _next_required_action(*, status: str, failed_metrics: list[str]) -> str:
    if status == "completed_candidate_gate_passed":
        return "rebuild_candidate_gate_and_prepare_human_paper_review_evidence"
    if status == "completed_candidate_gate_failed" and failed_metrics:
        return "design_new_fold_specific_hypothesis_or_select_better_candidate"
    if status == "unsafe_retest_output":
        return "repair_retest_safety_output"
    return "rerun_bounded_retest_to_completion"


def _failed_metrics(*payloads: Mapping[str, Any]) -> list[str]:
    failed: list[str] = []
    for payload in payloads:
        failed.extend(_list_of_strings(payload.get("fail_reasons")))
        failed.extend(_list_of_strings(payload.get("failed_metrics")))
    return [
        item
        for item in _dedupe(failed)
        if item in {"event_profit_factor", "walk_forward_pass_rate", "regime_pass_rate", "cost_stress"}
    ]


def _safety_unsafe(*, safety: Mapping[str, Any], promotion: Mapping[str, Any]) -> bool:
    paper_review = _mapping(promotion.get("paper_review"))
    return any(
        [
            bool(safety.get("real_broker_api_called", False)),
            bool(safety.get("real_orders_created", False)),
            bool(safety.get("paper_auto_start", False)),
            str(safety.get("paper_queue_status", "LOCKED")) != "LOCKED",
            str(safety.get("live_status", "FROZEN")) != "FROZEN",
            bool(paper_review.get("paper_auto_start", False)),
            not bool(paper_review.get("paper_review_queue_locked", True)),
        ]
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
