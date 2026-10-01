#!/usr/bin/env python3
"""Build BTC trend v0 promotion gate report from robustness evidence."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_btc_trend_v0_robustness_report import (  # noqa: E402
    CANDIDATE_IDS,
    DEFAULT_LEDGER_OUTPUT,
    DEFAULT_OUTPUT as DEFAULT_ROBUSTNESS_REPORT,
    FORMAL_STRATEGY_IDS,
    MIN_LONG_HISTORY_ROWS,
)


SCHEMA_VERSION = "btc_trend_v0_promotion_gate_report_v1"
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_v0_promotion_gate_report.json")
DEFAULT_5M_FREEZE_REPORT = Path("artifacts/btc_paper_readiness/latest/btc_5m_hft_freeze_report.json")
PROMOTION_ORDER = [
    "twelve_month_momentum_intended",
    "ma120_200_trend_intended",
    "ma120_200_trend_vol_target_intended",
]
REQUIRED_LEDGER_FIELDS = [
    "timestamp",
    "strategy_id",
    "close",
    "daily_return",
    "raw_signal",
    "signal_timestamp",
    "effective_timestamp",
    "exposure",
    "turnover",
    "cost_bps",
    "strategy_daily_return",
    "equity",
    "reason",
]


def build_btc_trend_v0_promotion_gate_report(
    *,
    repo_root: Path | None = None,
    robustness_report: Path = DEFAULT_ROBUSTNESS_REPORT,
    position_ledger: Path = DEFAULT_LEDGER_OUTPUT,
    freeze_report: Path = DEFAULT_5M_FREEZE_REPORT,
    output: Path = DEFAULT_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    robustness_path = _resolve(root, robustness_report)
    ledger_path = _resolve(root, position_ledger)
    freeze_path = _resolve(root, freeze_report)
    output_path = _resolve(root, output)
    robustness = _read_json(robustness_path)
    freeze = _read_json(freeze_path)
    hard_blockers: list[str] = []

    if not robustness:
        hard_blockers.append("btc_trend_v0_robustness_report_missing")
    if str(robustness.get("status", "")) == "insufficient_history":
        hard_blockers.append("btc_trend_v0_robustness_insufficient_history")
    data = _mapping(robustness.get("data"))
    daily_rows = _int_or(data.get("daily_rows"), 0)
    if daily_rows < MIN_LONG_HISTORY_ROWS:
        hard_blockers.append("btc_trend_v0_daily_rows_below_1095")
    guardrails = _mapping(robustness.get("guardrails"))
    if bool(guardrails.get("private_endpoint_used", True)):
        hard_blockers.append("btc_trend_v0_private_endpoint_used")
    if bool(guardrails.get("order_endpoint_used", True)):
        hard_blockers.append("btc_trend_v0_order_endpoint_used")
    if bool(guardrails.get("broker_calls_allowed", True)):
        hard_blockers.append("btc_trend_v0_broker_calls_allowed")

    freeze_guardrails = _mapping(freeze.get("guardrails"))
    if freeze and freeze_guardrails.get("parameter_tuning_allowed") is not False:
        hard_blockers.append("btc_5m_hft_freeze_not_locked")
    if freeze and str(freeze.get("status", "")) != "frozen_rejected_as_high_frequency":
        hard_blockers.append("btc_5m_hft_freeze_status_not_frozen")

    ledger_audit = _audit_position_ledger(ledger_path)
    if not ledger_audit["exists"]:
        hard_blockers.append("btc_trend_v0_position_ledger_missing")
    if not ledger_audit["field_contract_pass"]:
        hard_blockers.append("btc_trend_v0_position_ledger_field_contract_failed")
    if not ledger_audit["complete"]:
        hard_blockers.append("btc_trend_v0_position_ledger_incomplete")
    if not ledger_audit["lookahead_pass"]:
        hard_blockers.append("btc_trend_v0_position_ledger_lookahead_failed")

    candidates = _candidate_gate_rows(robustness)
    selected = _select_candidate(candidates) if not hard_blockers else {}
    status = "rejected" if hard_blockers else ("paper_candidate_ready" if selected else "research_only")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "gate_type": "paper_operational_readiness_gate",
        "status": status,
        "decision": _decision_text(status),
        "scope": "allows_simulated_daily_paper_runner_only",
        "asset": "btc",
        "symbol": "BTCUSDT",
        "robustness_report": _relpath(robustness_path, root),
        "position_ledger": _relpath(ledger_path, root),
        "freeze_report": _relpath(freeze_path, root),
        "paper_candidate_ready": bool(selected),
        "paper_candidate_ready_scope": "simulated_paper_runner_operational_readiness",
        "paper_candidate_ready_is_strategy_validation": False,
        "strategy_validation_gate_required_for_backtest_claims": True,
        "strategy_validation_status": "not_evaluated_by_this_gate",
        "selected_candidate": selected,
        "promotion_order": PROMOTION_ORDER,
        "requirements": {
            "minimum_daily_rows": MIN_LONG_HISTORY_ROWS,
            "minimum_acceptable_year_segments": 4,
            "cost_stress_bps_required": 10.0,
            "minimum_drawdown_reduction_vs_buy_hold_pct": 20.0,
            "position_ledger_required": True,
            "no_future_function_required": True,
        },
        "data": {"daily_rows": daily_rows, "start": data.get("start", ""), "end": data.get("end", "")},
        "ledger_audit": ledger_audit,
        "candidate_gates": candidates,
        "guardrails": {
            "paper_candidate_ready_is_not_alpha_validation": True,
            "strategy_validation_gate_required_before_strategy_claims": True,
            "research_only_until_gate_passes": status != "paper_candidate_ready",
            "paper_runner_can_be_built_next": status == "paper_candidate_ready",
            "live_order_allowed": False,
            "broker_calls_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "do_not_reuse_5m_hft_ledger": True,
            "trend_paper_ledger_root": "data/paper_ledger/btc_trend_v0",
        },
        "blockers": _dedupe(hard_blockers),
    }
    _write_json(output_path, payload)
    return payload


def _decision_text(status: str) -> str:
    if status == "paper_candidate_ready":
        return "paper_runner_operationally_allowed_not_strategy_validated"
    if status == "research_only":
        return "paper_runner_not_allowed_research_only"
    return "paper_runner_rejected"


def _candidate_gate_rows(robustness: Mapping[str, Any]) -> list[dict[str, Any]]:
    default_by_id = {str(row.get("strategy_id", "")): _mapping(row) for row in robustness.get("default_performance", []) if isinstance(row, Mapping)}
    yearly_rows = [_mapping(row) for row in robustness.get("yearly_performance", []) if isinstance(row, Mapping)]
    cost_rows = [_mapping(row) for row in robustness.get("cost_stress", []) if isinstance(row, Mapping)]
    buy_hold_metrics = _mapping(_mapping(default_by_id.get("buy_hold_btc")).get("metrics"))
    candidates = []
    for strategy_id in CANDIDATE_IDS:
        metrics = _mapping(_mapping(default_by_id.get(strategy_id)).get("metrics"))
        cost_10 = _mapping(
            next(
                (
                    _mapping(row.get("metrics"))
                    for row in cost_rows
                    if str(row.get("strategy_id", "")) == strategy_id and abs(float(row.get("cost_bps", 0.0)) - 10.0) < 1e-12
                ),
                {},
            )
        )
        acceptable_segments = sum(
            1 for row in yearly_rows if str(row.get("strategy_id", "")) == strategy_id and bool(row.get("acceptable", False))
        )
        drawdown_reduction = float(buy_hold_metrics.get("max_drawdown_abs_pct", 0.0) or 0.0) - float(
            metrics.get("max_drawdown_abs_pct", 0.0) or 0.0
        )
        checks = {
            "acceptable_year_segments": acceptable_segments >= 4,
            "cost_10bps_total_return_positive": float(cost_10.get("total_return_pct", 0.0) or 0.0) > 0.0,
            "cost_10bps_drawdown_below_buy_hold": float(cost_10.get("max_drawdown_abs_pct", 999.0) or 999.0)
            < float(buy_hold_metrics.get("max_drawdown_abs_pct", 0.0) or 0.0),
            "drawdown_reduction_vs_buy_hold_at_least_20pct": drawdown_reduction >= 20.0,
        }
        candidates.append(
            {
                "strategy_id": strategy_id,
                "paper_candidate_ready": all(checks.values()),
                "checks": checks,
                "acceptable_year_segments": acceptable_segments,
                "default_total_return_pct": metrics.get("total_return_pct", 0.0),
                "default_max_drawdown_abs_pct": metrics.get("max_drawdown_abs_pct", 0.0),
                "cost_10bps_total_return_pct": cost_10.get("total_return_pct", 0.0),
                "cost_10bps_max_drawdown_abs_pct": cost_10.get("max_drawdown_abs_pct", 0.0),
                "drawdown_reduction_vs_buy_hold_pct": round(drawdown_reduction, 6),
            }
        )
    return candidates


def _select_candidate(candidates: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_id = {str(row.get("strategy_id", "")): _mapping(row) for row in candidates}
    for strategy_id in PROMOTION_ORDER:
        row = by_id.get(strategy_id, {})
        if bool(row.get("paper_candidate_ready", False)):
            return row
    return {}


def _audit_position_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "row_count": 0,
            "field_contract_pass": False,
            "complete": False,
            "lookahead_pass": False,
            "strategy_ids_present": [],
            "bad_rows": [],
        }
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    fields_ok = fieldnames == REQUIRED_LEDGER_FIELDS
    bad_rows: list[dict[str, Any]] = []
    strategies = sorted({row.get("strategy_id", "") for row in rows if row.get("strategy_id")})
    for index, row in enumerate(rows, start=2):
        reason = str(row.get("reason", "")).strip()
        exposure = _float_or(row.get("exposure"), 0.0)
        signal_timestamp = str(row.get("signal_timestamp", "")).strip()
        effective_timestamp = str(row.get("effective_timestamp", "")).strip()
        if not reason:
            bad_rows.append({"line": index, "reason": "missing_reason"})
            continue
        if exposure > 0.0 and not signal_timestamp:
            bad_rows.append({"line": index, "reason": "positive_exposure_missing_signal_timestamp"})
            continue
        if signal_timestamp:
            signal_ts = pd.Timestamp(signal_timestamp)
            effective_ts = pd.Timestamp(effective_timestamp)
            if signal_ts >= effective_ts:
                bad_rows.append({"line": index, "reason": "signal_timestamp_not_before_effective_timestamp"})
                continue
    complete = bool(rows) and fields_ok and not bad_rows and all(strategy_id in strategies for strategy_id in FORMAL_STRATEGY_IDS)
    return {
        "exists": True,
        "row_count": len(rows),
        "field_contract_pass": fields_ok,
        "complete": complete,
        "lookahead_pass": not any(row.get("reason") == "signal_timestamp_not_before_effective_timestamp" for row in bad_rows),
        "strategy_ids_present": strategies,
        "bad_rows": bad_rows[:20],
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _int_or(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _float_or(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC trend v0 promotion gate report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--robustness-report", default=str(DEFAULT_ROBUSTNESS_REPORT))
    parser.add_argument("--position-ledger", default=str(DEFAULT_LEDGER_OUTPUT))
    parser.add_argument("--freeze-report", default=str(DEFAULT_5M_FREEZE_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_trend_v0_promotion_gate_report(
        repo_root=Path(args.repo_root),
        robustness_report=Path(args.robustness_report),
        position_ledger=Path(args.position_ledger),
        freeze_report=Path(args.freeze_report),
        output=Path(args.output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
