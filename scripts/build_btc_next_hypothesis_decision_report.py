#!/usr/bin/env python3
"""Build a fail-closed BTC next-hypothesis decision report."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
DEFAULT_BOUNDED_RETEST_OUTCOME = Path("artifacts/btc_candidate_gate/latest/candidate_bounded_retest_outcome_report.json")
DEFAULT_PROBE_RUN_DIRS = [
    Path("artifacts/btc_canonical/20260605T000000Z_lifecycle_probe"),
    Path("artifacts/btc_canonical/20260605T001000Z_lifecycle_entry_quality_probe"),
]
EVENT_PF_THRESHOLD = 1.15
WALK_FORWARD_PASS_RATE_THRESHOLD = 0.80


def build_btc_next_hypothesis_decision_report(
    *,
    repo_root: Path | None = None,
    probe_run_dirs: list[Path] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    selected_probe_dirs = [_resolve(root, path) for path in (probe_run_dirs or DEFAULT_PROBE_RUN_DIRS)]
    outcome = _read_json(root / DEFAULT_BOUNDED_RETEST_OUTCOME)
    rows = _probe_rows(root=root, run_dirs=selected_probe_dirs)
    best_by_event_pf = max(rows, key=lambda row: (row["event_profit_factor"], row["walk_forward_pass_rate"]), default={})
    best_by_walk_forward = max(rows, key=lambda row: (row["walk_forward_pass_rate"], row["event_profit_factor"]), default={})
    event_pf_pass_count = sum(1 for row in rows if bool(row["event_profit_factor_pass"]))
    walk_forward_pass_count = sum(1 for row in rows if bool(row["walk_forward_pass_rate_pass"]))
    any_candidate_gate_candidate = any(
        bool(row["event_profit_factor_pass"]) and bool(row["walk_forward_pass_rate_pass"]) for row in rows
    )
    status = "candidate_probe_promising_requires_full_gate" if any_candidate_gate_candidate else "dual_trend_micro_surgery_rejected"
    blockers = _blockers(rows=rows, event_pf_pass_count=event_pf_pass_count, status=status)
    return {
        "schema_version": "btc_next_hypothesis_decision_report_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "status": status,
        "decision": "reject_same_family_micro_surgery" if status == "dual_trend_micro_surgery_rejected" else "candidate_probe_requires_full_gate",
        "next_required_action": (
            "design_new_strategy_family_with_lifecycle_edge"
            if status == "dual_trend_micro_surgery_rejected"
            else "run_full_candidate_gate_for_promising_probe"
        ),
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "same_family_micro_search_allowed": False,
        "source_bounded_retest_outcome": _relpath(root / DEFAULT_BOUNDED_RETEST_OUTCOME, root)
        if (root / DEFAULT_BOUNDED_RETEST_OUTCOME).exists()
        else None,
        "source_bounded_retest_status": str(outcome.get("status", "missing") or "missing"),
        "baseline_candidate": {
            "run_id": str(outcome.get("run_id", "")),
            "event_profit_factor": _float_or_none(_mapping(outcome.get("metrics")).get("event_profit_factor")),
            "walk_forward_pass_rate": _float_or_none(_mapping(outcome.get("metrics")).get("walk_forward_pass_rate")),
            "max_drawdown": _float_or_none(_mapping(outcome.get("metrics")).get("max_drawdown")),
            "failed_metrics": _list_of_strings(outcome.get("failed_metrics")),
        },
        "thresholds": {
            "event_profit_factor": EVENT_PF_THRESHOLD,
            "walk_forward_pass_rate": WALK_FORWARD_PASS_RATE_THRESHOLD,
        },
        "probe_run_dirs": [_relpath(path, root) for path in selected_probe_dirs],
        "probe_count": len(selected_probe_dirs),
        "mode_count": len(rows),
        "event_profit_factor_pass_count": event_pf_pass_count,
        "walk_forward_pass_rate_pass_count": walk_forward_pass_count,
        "best_by_event_profit_factor": best_by_event_pf,
        "best_by_walk_forward_pass_rate": best_by_walk_forward,
        "rows": rows,
        "interpretation": _interpretation(rows=rows, best_by_event_pf=best_by_event_pf, best_by_walk_forward=best_by_walk_forward),
        "guardrails": {
            "research_only": True,
            "broker_calls_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "ordinary_profit_factor_diagnostic_only": True,
            "do_not_optimize_sharpe_before_event_pf": True,
        },
        "blockers": blockers,
    }


def write_btc_next_hypothesis_decision_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_next_hypothesis_decision_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--probe-run-dir", action="append", default=[])
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_next_hypothesis_decision_report(
        repo_root=Path(args.repo_root),
        probe_run_dirs=[Path(path) for path in args.probe_run_dir] if args.probe_run_dir else None,
        generated_at=args.generated_at or None,
    )
    print(write_btc_next_hypothesis_decision_report(payload, Path(args.output_root)))


def _probe_rows(*, root: Path, run_dirs: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        manifests = sorted((run_dir / "manifests").glob("run_btc_perp_dual_trend_v5_*_ablation_base.json"))
        for manifest_path in manifests:
            strategy_id = manifest_path.name.removeprefix("run_").removesuffix("_ablation_base.json")
            mode = strategy_id.removeprefix("btc_perp_dual_trend_v5_")
            base = _manifest_metrics(manifest_path)
            fold_rows = []
            for fold_path in sorted((run_dir / "manifests").glob(f"run_{strategy_id}_wf*.json")):
                fold_id = int(fold_path.stem.rsplit("_wf", 1)[-1])
                fold_metrics = _manifest_metrics(fold_path)
                fold_rows.append(
                    {
                        "fold_id": fold_id,
                        "passed": _fold_passed(fold_metrics),
                        "event_profit_factor": fold_metrics["event_profit_factor"],
                        "total_return_pct": fold_metrics["total_return_pct"],
                        "max_drawdown": fold_metrics["max_drawdown"],
                        "fill_count": fold_metrics["fill_count"],
                        "manifest_path": _relpath(fold_path, root),
                    }
                )
            pass_rate = round(sum(1 for fold in fold_rows if fold["passed"]) / max(1, len(fold_rows)), 6)
            row = {
                "run_id": run_dir.name,
                "mode": mode,
                "strategy_id": strategy_id,
                "base_manifest_path": _relpath(manifest_path, root),
                "event_profit_factor": base["event_profit_factor"],
                "event_profit_factor_pass": base["event_profit_factor"] >= EVENT_PF_THRESHOLD,
                "walk_forward_pass_rate": pass_rate,
                "walk_forward_pass_rate_pass": pass_rate >= WALK_FORWARD_PASS_RATE_THRESHOLD,
                "total_return_pct": base["total_return_pct"],
                "max_drawdown": base["max_drawdown"],
                "fill_count": base["fill_count"],
                "ledger_equity_consistent": base["ledger_equity_consistent"],
                "folds": fold_rows,
            }
            row["failed_metrics"] = _failed_metrics(row)
            rows.append(row)
    return rows


def _manifest_metrics(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    ledger = _mapping(payload.get("ledger_artifact"))
    reconciliation = _mapping(ledger.get("reconciliation"))
    snapshots = reconciliation.get("snapshots")
    equities = [
        _float_or_none(_mapping(snapshot).get("ledger_equity", _mapping(snapshot).get("snapshot_equity")))
        for snapshot in snapshots
    ] if isinstance(snapshots, list) else []
    equity_values = [value for value in equities if value is not None]
    returns = [
        0.0 if previous in {None, 0.0} else (current / previous) - 1.0
        for previous, current in zip([None, *equity_values[:-1]], equity_values)
    ]
    peak = None
    drawdowns: list[float] = []
    for value in equity_values:
        peak = value if peak is None else max(peak, value)
        drawdowns.append((value / peak - 1.0) * 100.0 if peak else 0.0)
    fills = _mapping(ledger.get("fills"))
    evidence = _mapping(payload.get("evidence"))
    equity = _mapping(evidence.get("equity"))
    return {
        "event_profit_factor": _profit_factor(returns),
        "total_return_pct": round(((equity_values[-1] / equity_values[0]) - 1.0) * 100.0, 6)
        if len(equity_values) >= 2 and equity_values[0]
        else 0.0,
        "max_drawdown": round(min(drawdowns), 6) if drawdowns else 0.0,
        "fill_count": int(fills.get("effective_fill_count", fills.get("raw_fill_count", 0)) or 0),
        "ledger_equity_consistent": bool(equity.get("consistent", False)),
    }


def _fold_passed(metrics: Mapping[str, Any]) -> bool:
    return (
        float(metrics.get("total_return_pct", 0.0)) >= 0.0
        and float(metrics.get("event_profit_factor", 0.0)) >= 1.0
        and bool(metrics.get("ledger_equity_consistent", False))
    )


def _failed_metrics(row: Mapping[str, Any]) -> list[str]:
    failed = []
    if not bool(row.get("event_profit_factor_pass", False)):
        failed.append("event_profit_factor")
    if not bool(row.get("walk_forward_pass_rate_pass", False)):
        failed.append("walk_forward_pass_rate")
    if not bool(row.get("ledger_equity_consistent", False)):
        failed.append("event_ledger")
    return failed


def _blockers(*, rows: list[Mapping[str, Any]], event_pf_pass_count: int, status: str) -> list[str]:
    blockers: list[str] = []
    if not rows:
        blockers.append("btc_next_hypothesis_probe_rows_missing")
    if event_pf_pass_count <= 0:
        blockers.append("btc_next_hypothesis_all_probe_event_profit_factor_failed")
    if status == "dual_trend_micro_surgery_rejected":
        blockers.append("btc_next_hypothesis_dual_trend_micro_surgery_rejected")
    return _dedupe(blockers)


def _interpretation(
    *,
    rows: list[Mapping[str, Any]],
    best_by_event_pf: Mapping[str, Any],
    best_by_walk_forward: Mapping[str, Any],
) -> list[str]:
    if not rows:
        return ["no lifecycle probe rows were available; remain fail-closed"]
    return [
        "lifecycle risk cuts improved drawdown and some fold stability, but no probe reached the event_PF gate",
        (
            f"best event_PF mode {best_by_event_pf.get('mode', '')} reached "
            f"{best_by_event_pf.get('event_profit_factor', 0.0)} versus required {EVENT_PF_THRESHOLD}"
        ),
        (
            f"best WF mode {best_by_walk_forward.get('mode', '')} reached "
            f"{best_by_walk_forward.get('walk_forward_pass_rate', 0.0)} pass rate, but still failed event_PF"
        ),
        "same-family dual-trend micro-surgery should stop; the next research unit needs a new strategy family or a materially different lifecycle edge",
    ]


def _profit_factor(values: list[float]) -> float:
    gains = sum(value for value in values if value > 0.0)
    losses = abs(sum(value for value in values if value < 0.0))
    if losses <= 0.0:
        return 999.0 if gains > 0.0 else 0.0
    return round(gains / losses, 6)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
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
