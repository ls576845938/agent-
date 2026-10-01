#!/usr/bin/env python3
"""Run the BTC scalping research backtest sandbox.

This is a research-only convenience runner. It rebuilds the existing 1m proxy
scalping event-ledger prototype and the 5m drift-guarded intraday event-ledger
backtest, then writes one small report that tells the operator what is usable
for research right now. It does not create candidate, paper, live, broker, or
order-submission state.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from quant_us.research.btc_intraday_short_cycle_event_ledger import (
        BTC_INTRADAY_DRIFT_GUARDED_EVENT_LEDGER_RUN_ID,
        BTC_INTRADAY_EVENT_LEDGER_LATEST,
        BTC_INTRADAY_EVENT_LEDGER_ROOT,
        run_btc_intraday_short_cycle_drift_guarded_event_ledger,
    )
    from scripts.build_btc_true_scalping_event_ledger_prototype_report import (
        DEFAULT_OUTPUT_ROOT as TRUE_SCALPING_OUTPUT_ROOT,
        build_btc_true_scalping_event_ledger_prototype_report,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_us.research.btc_intraday_short_cycle_event_ledger import (
        BTC_INTRADAY_DRIFT_GUARDED_EVENT_LEDGER_RUN_ID,
        BTC_INTRADAY_EVENT_LEDGER_LATEST,
        BTC_INTRADAY_EVENT_LEDGER_ROOT,
        run_btc_intraday_short_cycle_drift_guarded_event_ledger,
    )
    from scripts.build_btc_true_scalping_event_ledger_prototype_report import (
        DEFAULT_OUTPUT_ROOT as TRUE_SCALPING_OUTPUT_ROOT,
        build_btc_true_scalping_event_ledger_prototype_report,
    )


DEFAULT_OUTPUT = Path("artifacts/btc_research_backtests/latest/btc_scalping_research_backtest_report.json")
DRIFT_GUARDED_REPORT_NAME = "btc_intraday_short_cycle_drift_guarded_event_ledger_report.json"
REQUIRED_MANIFEST_FIELDS = [
    "data_version",
    "strategy_version",
    "params",
    "cost_model",
    "slippage_model",
    "commit_hash",
]


def run_btc_scalping_research_backtest(
    *,
    repo_root: Path | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
    one_minute_history_days: int = 180,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    one_minute_report = build_btc_true_scalping_event_ledger_prototype_report(
        repo_root=root,
        output_root=TRUE_SCALPING_OUTPUT_ROOT,
        generated_at=generated,
        history_days=one_minute_history_days,
    )
    drift_run_dir = run_btc_intraday_short_cycle_drift_guarded_event_ledger(
        run_id=BTC_INTRADAY_DRIFT_GUARDED_EVENT_LEDGER_RUN_ID,
        output_root=BTC_INTRADAY_EVENT_LEDGER_ROOT,
        latest_root=BTC_INTRADAY_EVENT_LEDGER_LATEST,
        repo_root=root,
    )
    drift_report_path = drift_run_dir / DRIFT_GUARDED_REPORT_NAME
    drift_report = _read_json(drift_report_path)

    one_minute_manifest = _manifest_summary(
        root=root,
        path=_optional_path(_mapping(one_minute_report.get("artifacts")).get("run_manifest")),
    )
    drift_manifest = _manifest_summary(
        root=root,
        path=_optional_path(_mapping(drift_report.get("artifacts")).get("run_manifest")),
    )
    one_minute_gate_passed = bool(_mapping(one_minute_report.get("gate")).get("passed", False))
    drift_gate_passed = bool(_mapping(drift_report.get("gate")).get("passed", False))
    status = "research_backtest_completed" if drift_manifest["complete"] else "research_backtest_incomplete"
    if str(one_minute_report.get("status", "")) == "event_ledger_research_gate_blocked":
        status = "research_backtest_completed_with_1m_proxy_blocked" if drift_manifest["complete"] else status

    recommended_track = "five_minute_drift_guarded_intraday" if drift_gate_passed else "none"
    if one_minute_gate_passed:
        recommended_track = "one_minute_proxy_scalping"

    report = {
        "schema_version": "btc_scalping_research_backtest_report_v1",
        "generated_at": generated,
        "asset": "btc",
        "symbol": "BTCUSDT",
        "scope": "research_only_btc_scalping_backtest_no_candidate_no_paper_no_live",
        "status": status,
        "decision": _decision(one_minute_gate_passed=one_minute_gate_passed, drift_gate_passed=drift_gate_passed),
        "next_required_action": "inspect_research_backtest_outputs_or_adjust_params_then_rerun",
        "recommended_research_track": recommended_track,
        "operator_summary": {
            "current_research_answer": _operator_answer(
                one_minute_gate_passed=one_minute_gate_passed,
                drift_gate_passed=drift_gate_passed,
            ),
            "run_command": "make run-btc-scalping-research-backtest",
            "direct_command": "python3 scripts/run_btc_scalping_research_backtest.py",
        },
        "backtests": {
            "one_minute_proxy_scalping": _backtest_summary(
                report=one_minute_report,
                label="1m public microstructure proxy scalping",
                timeframe="1m",
                manifest=one_minute_manifest,
            ),
            "five_minute_drift_guarded_intraday": _backtest_summary(
                report=drift_report,
                label="5m drift-guarded intraday scalping research",
                timeframe="5m",
                manifest=drift_manifest,
                report_path=drift_report_path,
            ),
        },
        "manifest_contract": {
            "required_fields": REQUIRED_MANIFEST_FIELDS,
            "one_minute_proxy_scalping_complete": one_minute_manifest["complete"],
            "five_minute_drift_guarded_intraday_complete": drift_manifest["complete"],
        },
        "guardrails": {
            "research_only": True,
            "strategy_outputs_only": ["Signal", "OrderIntent", "TargetPosition"],
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "candidate_generation_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "pnl_from_fill_or_trade_ledger": True,
        },
    }
    output_file = _resolve(root, output_path or DEFAULT_OUTPUT)
    _write_json(output_file, report)
    return report


def _decision(*, one_minute_gate_passed: bool, drift_gate_passed: bool) -> str:
    if one_minute_gate_passed:
        return "continue_research_on_1m_proxy_scalping_keep_paper_live_locked"
    if drift_gate_passed:
        return "use_5m_drift_guarded_for_research_iteration_redesign_1m_proxy_scalping"
    return "redesign_scalping_research_hypothesis"


def _operator_answer(*, one_minute_gate_passed: bool, drift_gate_passed: bool) -> str:
    if one_minute_gate_passed:
        return "1m proxy scalping research backtest passed its internal research gate; paper/live remain locked."
    if drift_gate_passed:
        return "5m drift-guarded BTC intraday research backtest is the usable research track now; 1m proxy scalping runs but fails after costs."
    return "Both current BTC scalping research tracks need redesign before candidate or paper work."


def _backtest_summary(
    *,
    report: Mapping[str, Any],
    label: str,
    timeframe: str,
    manifest: Mapping[str, Any],
    report_path: Path | None = None,
) -> dict[str, Any]:
    gate = _mapping(report.get("gate"))
    metrics = _mapping(report.get("metrics"))
    artifacts = _mapping(report.get("artifacts"))
    return {
        "label": label,
        "timeframe": timeframe,
        "status": str(report.get("status", "missing")),
        "strategy_id": str(report.get("strategy_id", "")),
        "variant_id": str(report.get("variant_id", "")),
        "scope": str(report.get("scope", "")),
        "report_path": str(report_path) if report_path is not None else None,
        "run_dir": report.get("run_dir"),
        "artifacts": dict(artifacts),
        "metrics": {
            key: metrics.get(key)
            for key in [
                "event_count",
                "trade_count",
                "fill_count",
                "profit_factor",
                "hit_rate",
                "mean_trade_return_bps",
                "total_return_pct",
                "max_drawdown",
                "walk_forward_pass_rate",
                "regime_pass_rate",
            ]
            if key in metrics
        },
        "gate_passed": bool(gate.get("passed", False)),
        "gate_status": str(gate.get("status", "missing")),
        "blockers": [str(item) for item in report.get("blockers", []) if isinstance(item, str)],
        "manifest": dict(manifest),
        "research_only_lock": {
            "candidate_generation_allowed": bool(report.get("candidate_generation_allowed", False)),
            "strategy_skeleton_generation_allowed": bool(report.get("strategy_skeleton_generation_allowed", False)),
            "paper_or_live_unlock_allowed": bool(report.get("paper_or_live_unlock_allowed", False)),
            "true_scalping_allowed": bool(report.get("true_scalping_allowed", False)),
        },
    }


def _manifest_summary(*, root: Path, path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "path": None,
            "present": False,
            "required_fields_present": {field: False for field in REQUIRED_MANIFEST_FIELDS},
            "complete": False,
            "paper_queue": None,
            "live": None,
        }
    manifest_path = _resolve(root, path)
    payload = _read_json(manifest_path)
    present = manifest_path.exists() and bool(payload)
    fields = {field: bool(payload.get(field)) for field in REQUIRED_MANIFEST_FIELDS}
    return {
        "path": _relpath(manifest_path, root),
        "present": present,
        "required_fields_present": fields,
        "complete": present and all(fields.values()),
        "paper_queue": payload.get("paper_queue"),
        "live": payload.get("live"),
    }


def _optional_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    return Path(value)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--one-minute-history-days", type=int, default=180)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    output = Path(args.output_path)
    run_btc_scalping_research_backtest(
        repo_root=Path(args.repo_root),
        output_path=output,
        generated_at=args.generated_at or None,
        one_minute_history_days=args.one_minute_history_days,
    )
    print(output)


if __name__ == "__main__":
    main()
