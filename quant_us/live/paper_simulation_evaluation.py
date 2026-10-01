"""Evaluate US equity ETF paper-simulation ledger quality.

This module holds the service rules for paper-simulation ledger evaluation. It
does not start paper simulation, unlock live trading, or call broker/private or
order endpoints.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_us.live.paper_ledger_pnl import build_paper_ledger_pnl_replay


SCHEMA_VERSION = "us_equity_paper_simulation_evaluation_v1"
DEFAULT_LEDGER_ROOT = Path("data/paper_ledger/us_equity_etf_rotation_v1")
DEFAULT_ROLL_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_roll_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_evaluation_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 纸面模拟评估.md")


def build_us_equity_paper_simulation_evaluation_report(
    *,
    repo_root: Path | None = None,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    roll_report: Path = DEFAULT_ROLL_REPORT,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    ledger = _resolve(root, ledger_root)
    roll_path = _resolve(root, roll_report)
    roll = _read_json(roll_path)
    targets = _read_jsonl(ledger / "target_positions.jsonl")
    fills = _read_jsonl(ledger / "fills.jsonl")
    positions = _read_jsonl(ledger / "positions.jsonl")
    cash_ledger = _read_jsonl(ledger / "cash_ledger.jsonl")
    snapshots = _read_jsonl(ledger / "portfolio_snapshots.jsonl")
    state = _read_json(ledger / "validation_state.json")
    daily_reports = _read_daily_reports(ledger / "daily_reports")
    ledger_rows = {
        "target_positions": targets,
        "fills": fills,
        "positions": positions,
        "cash_ledger": cash_ledger,
        "portfolio_snapshots": snapshots,
        "validation_state": [state] if state else [],
        "daily_reports": daily_reports,
    }
    prestart_evidence = _prestart_evidence(ledger=ledger, root=root, roll=roll, ledger_rows=ledger_rows)
    blockers: list[str] = []
    ledger_completeness = _ledger_completeness(prestart_evidence=prestart_evidence, ledger_rows=ledger_rows)

    if not prestart_evidence["ledger_started"]:
        blockers.extend(_list_of_str(prestart_evidence.get("blockers")))
    if _relpath(ledger, root) != "data/paper_ledger/us_equity_etf_rotation_v1":
        blockers.append("us_equity_paper_simulation_evaluation_ledger_root_not_canonical")
    if str(roll.get("status", "")) not in {"PASS", "BLOCKED"}:
        blockers.append("us_equity_paper_simulation_roll_report_missing_or_invalid")

    reconciliation = _reconcile_snapshots(snapshots)
    blockers.extend(reconciliation["blockers"])
    target_fill = _target_fill_consistency(targets, fills, snapshots)
    blockers.extend(target_fill["blockers"])
    trade_reconciliation = _trade_reconciliation(targets, fills)
    blockers.extend(trade_reconciliation["blockers"])
    position_cash = _position_cash_consistency(targets, positions, cash_ledger, snapshots)
    blockers.extend(position_cash["blockers"])
    ledger_pnl_replay = build_paper_ledger_pnl_replay(
        fill_rows=fills,
        position_rows=positions,
        cash_rows=cash_ledger,
        snapshot_rows=snapshots,
    )
    if prestart_evidence["ledger_started"] and ledger_pnl_replay["status"] != "passed":
        blockers.extend(
            f"us_equity_paper_simulation_{item}"
            for item in _list_of_str(ledger_pnl_replay.get("blockers"))
        )
    blockers.extend(ledger_completeness["blockers"])
    unsafe = _unsafe_flags({"roll": roll, "state": state})
    blockers.extend([f"us_equity_paper_simulation_evaluation_unsafe_flag:{item}" for item in unsafe])

    if not prestart_evidence["ledger_started"]:
        status = "paper_simulation_not_started"
    elif blockers:
        status = "paper_simulation_blocked"
    elif len(snapshots) < 30:
        status = "paper_simulation_observing"
    else:
        status = "paper_simulation_complete_for_manual_review"

    replay_equity = [
        _float_or(row.get("equity"), 0.0)
        for row in ledger_pnl_replay.get("equity_curve", [])
        if isinstance(row, Mapping)
    ]
    metrics = {
        "paper_days": len({str(row.get("timestamp", "")) for row in snapshots if row.get("timestamp")}),
        "target_position_count": len(targets),
        "fill_count": len(fills),
        "position_ledger_count": len(positions),
        "cash_ledger_count": len(cash_ledger),
        "snapshot_count": len(snapshots),
        "target_change_count": _target_change_count(targets),
        "total_estimated_slippage": round(sum(_float_or(row.get("estimated_slippage"), 0.0) for row in snapshots), 6),
        "total_estimated_financing": round(sum(_float_or(row.get("estimated_financing_daily"), 0.0) for row in snapshots), 6),
        "latest_equity": _float_or(ledger_pnl_replay.get("latest_equity"), 0.0),
        "max_drawdown": _max_drawdown(replay_equity),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
        "status": status,
        "allowed_statuses": [
            "paper_simulation_not_started",
            "paper_simulation_observing",
            "paper_simulation_complete_for_manual_review",
            "paper_simulation_blocked",
        ],
        "decision": "do_not_start_live_or_claim_paper_success",
        "ledger_root": _relpath(ledger, root),
        "metrics": metrics,
        "ledger_checks": {
            "ledger_completeness": ledger_completeness,
            "snapshot_reconciliation": reconciliation,
            "target_fill_consistency": target_fill,
            "trade_reconciliation": trade_reconciliation,
            "position_cash_consistency": position_cash,
            "ledger_pnl_replay": ledger_pnl_replay,
            "unsafe_flags_absent": {"passed": not unsafe, "unsafe_flags": unsafe},
        },
        "prestart_evidence": prestart_evidence,
        "latest_state": {
            "state_present": bool(state),
            "last_processed_timestamp": str(state.get("last_processed_timestamp", "")),
            "current_equity": _float_or(state.get("current_equity"), 0.0),
            "target_position_count": int(state.get("target_position_count", 0) or 0),
            "fill_count": int(state.get("fill_count", 0) or 0),
        },
        "blockers": _dedupe(blockers),
        "guardrails": {
            "evaluation_only": True,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "broker_calls_used": False,
            "live_ready_claim_allowed": False,
        },
        "source_reports": {
            "paper_roll": _relpath(roll_path, root),
        },
        "source_ledgers": {
            "target_positions": _relpath(ledger / "target_positions.jsonl", root),
            "fills": _relpath(ledger / "fills.jsonl", root),
            "positions": _relpath(ledger / "positions.jsonl", root),
            "cash_ledger": _relpath(ledger / "cash_ledger.jsonl", root),
            "portfolio_snapshots": _relpath(ledger / "portfolio_snapshots.jsonl", root),
            "validation_state": _relpath(ledger / "validation_state.json", root),
            "daily_reports": _relpath(ledger / "daily_reports", root),
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _prestart_evidence(
    *,
    ledger: Path,
    root: Path,
    roll: Mapping[str, Any],
    ledger_rows: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    ledger_file_names = [
        "target_positions",
        "fills",
        "positions",
        "cash_ledger",
        "portfolio_snapshots",
        "validation_state",
        "daily_reports",
    ]
    file_paths = {
        "target_positions": ledger / "target_positions.jsonl",
        "fills": ledger / "fills.jsonl",
        "positions": ledger / "positions.jsonl",
        "cash_ledger": ledger / "cash_ledger.jsonl",
        "portfolio_snapshots": ledger / "portfolio_snapshots.jsonl",
        "validation_state": ledger / "validation_state.json",
        "daily_reports": ledger / "daily_reports",
    }
    file_statuses = {
        name: {
            "path": _relpath(path, root),
            "exists": path.exists(),
            "row_count": len(ledger_rows.get(name, [])),
        }
        for name, path in file_paths.items()
    }
    missing_files = [name for name in ledger_file_names if not file_statuses[name]["exists"]]
    roll_blockers = _list_of_str(roll.get("blockers"))
    roll_materialization = _mapping(roll.get("ledger_materialization"))
    blocked_by_roll_report = str(roll.get("status", "")) == "BLOCKED" and bool(roll_blockers)
    ledger_write_expected = not blocked_by_roll_report
    blockers: list[str] = []
    if not ledger.exists() and ledger_write_expected:
        blockers.append("us_equity_paper_simulation_ledger_root_missing")
    if ledger_write_expected:
        blockers.extend(f"us_equity_paper_simulation_missing_ledger_file:{name}" for name in missing_files)
    if not ledger_rows.get("target_positions") and ledger_write_expected:
        blockers.append("us_equity_paper_simulation_no_target_positions")
    if not ledger_rows.get("portfolio_snapshots") and ledger_write_expected:
        blockers.append("us_equity_paper_simulation_no_portfolio_snapshots")
    if str(roll.get("status", "")) == "BLOCKED":
        blockers.append("us_equity_paper_simulation_roll_blocked")
    blockers.extend(roll_blockers)
    ledger_started = bool(ledger_rows.get("target_positions")) and bool(ledger_rows.get("portfolio_snapshots"))
    return {
        "ledger_started": ledger_started,
        "ledger_root_exists": ledger.exists(),
        "ledger_root": _relpath(ledger, root),
        "expected_ledger_files": ledger_file_names,
        "missing_ledger_files": missing_files,
        "ledger_file_statuses": file_statuses,
        "roll_report_status": str(roll.get("status", "")),
        "roll_cycle_status": str(roll.get("cycle_status", "")),
        "roll_blockers": roll_blockers,
        "roll_ledger_materialization_status": str(roll_materialization.get("status", "")),
        "roll_ledger_writes_performed": roll_materialization.get("writes_performed") is True,
        "roll_ledger_rows_written_this_cycle": _ledger_row_counts(_mapping(roll_materialization.get("rows_written_this_cycle"))),
        "roll_ledger_materialization_next_action": str(roll_materialization.get("operator_next_action", "")),
        "blocked_by_roll_report": blocked_by_roll_report,
        "ledger_write_expected": ledger_write_expected,
        "readiness_status": str(roll.get("readiness_status", "")),
        "readiness_decision": str(roll.get("readiness_decision", "")),
        "manual_start_approved": roll.get("manual_start_approved") is True,
        "independent_ledger_root_verified": _relpath(ledger, root) == "data/paper_ledger/us_equity_etf_rotation_v1",
        "next_action": _paper_prestart_next_action(roll_blockers=roll_blockers, missing_files=missing_files),
        "blockers": _dedupe(blockers),
    }


def _ledger_row_counts(value: Mapping[str, Any]) -> dict[str, int]:
    return {
        "target_positions": int(value.get("target_positions", 0) or 0),
        "fills": int(value.get("fills", 0) or 0),
        "positions": int(value.get("positions", 0) or 0),
        "cash_ledger": int(value.get("cash_ledger", 0) or 0),
        "portfolio_snapshots": int(value.get("portfolio_snapshots", 0) or 0),
        "validation_state": int(value.get("validation_state", 0) or 0),
        "daily_reports": int(value.get("daily_reports", 0) or 0),
    }


def _ledger_completeness(
    *,
    prestart_evidence: Mapping[str, Any],
    ledger_rows: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    expected_files = _list_of_str(prestart_evidence.get("expected_ledger_files"))
    file_statuses = _mapping(prestart_evidence.get("ledger_file_statuses"))
    row_counts = {name: len(ledger_rows.get(name, [])) for name in expected_files}
    missing_files = [
        name
        for name in expected_files
        if _mapping(file_statuses.get(name)).get("exists") is not True
    ]
    target_count = row_counts.get("target_positions", 0)
    snapshot_count = row_counts.get("portfolio_snapshots", 0)
    blockers: list[str] = []

    ledger_started = prestart_evidence.get("ledger_started") is True
    ledger_write_expected = prestart_evidence.get("ledger_write_expected") is True
    blocked_before_write = prestart_evidence.get("blocked_by_roll_report") is True

    if missing_files and ledger_write_expected:
        blockers.extend(f"us_equity_paper_simulation_completeness_missing_ledger_file:{name}" for name in missing_files)

    if ledger_started:
        if target_count <= 0:
            blockers.append("us_equity_paper_simulation_completeness_no_target_positions")
        if snapshot_count <= 0:
            blockers.append("us_equity_paper_simulation_completeness_no_portfolio_snapshots")
        for name in ("positions", "cash_ledger", "portfolio_snapshots", "daily_reports"):
            if row_counts.get(name, 0) != target_count:
                blockers.append(f"us_equity_paper_simulation_completeness_row_count_mismatch:{name}")
        if row_counts.get("validation_state", 0) != 1:
            blockers.append("us_equity_paper_simulation_completeness_validation_state_missing")

    if ledger_started and not blockers:
        status = "complete"
        next_action = "continue paper simulation observation until the manual review window is reached"
    elif blocked_before_write and not ledger_started:
        status = "blocked_before_write"
        next_action = "resolve upstream paper roll blockers before expecting ledger files"
    elif not ledger_started:
        status = "not_started"
        next_action = "run the paper simulation roll only after readiness and manual start approval"
    else:
        status = "incomplete"
        next_action = "repair the independent paper ledger before evaluating paper performance"

    return {
        "passed": status == "complete",
        "status": status,
        "ledger_started": ledger_started,
        "ledger_write_expected": ledger_write_expected,
        "expected_files": expected_files,
        "missing_files": missing_files,
        "row_counts": row_counts,
        "target_position_count": target_count,
        "snapshot_count": snapshot_count,
        "blockers": _dedupe(blockers),
        "next_action": next_action,
    }


def _paper_prestart_next_action(*, roll_blockers: list[str], missing_files: list[str]) -> str:
    if "us_equity_paper_simulation_manual_start_not_approved" in roll_blockers:
        return "Record manual paper-start approval only after readiness is ready; do not start simulation automatically."
    if any("readiness" in item for item in roll_blockers):
        return "Resolve paper simulation readiness blockers before writing the independent paper ledger."
    if missing_files:
        return "Run the paper simulation roll after readiness and manual approval; expected independent ledger files are missing."
    return "Inspect paper simulation roll report and ledger consistency before continuing."


def _reconcile_snapshots(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    blockers: list[str] = []
    rows = []
    for row in snapshots:
        expected = _float_or(row.get("prior_equity"), 0.0) - _float_or(row.get("estimated_slippage"), 0.0) - _float_or(
            row.get("estimated_financing_daily"),
            0.0,
        )
        actual = _float_or(row.get("equity"), 0.0)
        diff = round(actual - expected, 8)
        passed = abs(diff) <= 0.01 and str(row.get("reconciliation_status", "")) == "clean"
        if not passed:
            blockers.append(f"us_equity_paper_simulation_snapshot_reconciliation_failed:{row.get('timestamp', '')}")
        rows.append(
            {
                "timestamp": str(row.get("timestamp", "")),
                "expected_equity": round(expected, 6),
                "actual_equity": round(actual, 6),
                "diff": diff,
                "passed": passed,
            }
        )
    return {
        "passed": not blockers,
        "checked_count": len(rows),
        "failed_count": len(blockers),
        "rows": rows[-5:],
        "blockers": blockers,
    }


def _target_fill_consistency(
    targets: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    target_dates = {str(row.get("timestamp") or _nested(row, "target_position.date", "")) for row in targets}
    snapshot_dates = {str(row.get("timestamp", "")) for row in snapshots}
    fill_dates = {str(row.get("timestamp", "")) for row in fills}
    missing_snapshot = sorted(date for date in target_dates if date and date not in snapshot_dates)
    missing_target = sorted(date for date in snapshot_dates if date and date not in target_dates)
    fill_without_target = sorted(date for date in fill_dates if date and date not in target_dates)
    blockers: list[str] = []
    if missing_snapshot:
        blockers.append("us_equity_paper_simulation_missing_snapshot_for_target")
    if missing_target:
        blockers.append("us_equity_paper_simulation_missing_target_for_snapshot")
    if fill_without_target:
        blockers.append("us_equity_paper_simulation_fill_without_target")
    return {
        "passed": not blockers,
        "target_dates": sorted(date for date in target_dates if date),
        "snapshot_dates": sorted(date for date in snapshot_dates if date),
        "fill_dates": sorted(date for date in fill_dates if date),
        "missing_snapshot_for_target": missing_snapshot,
        "missing_target_for_snapshot": missing_target,
        "fill_without_target": fill_without_target,
        "blockers": blockers,
    }


def _position_cash_consistency(
    targets: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    cash_ledger: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    target_dates = {str(row.get("timestamp") or _nested(row, "target_position.date", "")) for row in targets}
    position_dates = {str(row.get("timestamp", "")) for row in positions}
    cash_dates = {str(row.get("timestamp", "")) for row in cash_ledger}
    snapshot_by_date = {str(row.get("timestamp", "")): row for row in snapshots if row.get("timestamp")}
    blockers: list[str] = []
    missing_position = sorted(date for date in target_dates if date and date not in position_dates)
    missing_cash = sorted(date for date in target_dates if date and date not in cash_dates)
    position_without_target = sorted(date for date in position_dates if date and date not in target_dates)
    cash_without_target = sorted(date for date in cash_dates if date and date not in target_dates)
    if missing_position:
        blockers.append("us_equity_paper_simulation_missing_position_ledger_for_target")
    if missing_cash:
        blockers.append("us_equity_paper_simulation_missing_cash_ledger_for_target")
    if position_without_target:
        blockers.append("us_equity_paper_simulation_position_without_target")
    if cash_without_target:
        blockers.append("us_equity_paper_simulation_cash_without_target")
    cash_rows = []
    for row in cash_ledger:
        timestamp = str(row.get("timestamp", ""))
        snapshot = snapshot_by_date.get(timestamp, {})
        expected = _float_or(snapshot.get("equity"), 0.0)
        actual = _float_or(row.get("final_equity"), 0.0)
        diff = round(actual - expected, 8)
        passed = bool(snapshot) and abs(diff) <= 0.01 and row.get("cash_reconciliation_status") == "clean"
        if not passed:
            blockers.append(f"us_equity_paper_simulation_cash_reconciliation_failed:{timestamp}")
        cash_rows.append(
            {
                "timestamp": timestamp,
                "expected_equity": round(expected, 6),
                "actual_final_equity": round(actual, 6),
                "diff": diff,
                "passed": passed,
            }
        )
    return {
        "passed": not blockers,
        "position_ledger_count": len(positions),
        "cash_ledger_count": len(cash_ledger),
        "missing_position_for_target": missing_position,
        "missing_cash_for_target": missing_cash,
        "position_without_target": position_without_target,
        "cash_without_target": cash_without_target,
        "cash_reconciliation_rows": cash_rows[-5:],
        "blockers": blockers,
    }


def _trade_reconciliation(targets: list[dict[str, Any]], fills: list[dict[str, Any]]) -> dict[str, Any]:
    fills_by_date: dict[str, list[dict[str, Any]]] = {}
    blockers: list[str] = []
    for fill in fills:
        timestamp = str(fill.get("timestamp", ""))
        fills_by_date.setdefault(timestamp, []).append(fill)
        if fill.get("simulated_only") is not True:
            blockers.append(f"us_equity_paper_simulation_fill_not_simulated_only:{timestamp}")
        if str(fill.get("broker_order_id", "")):
            blockers.append(f"us_equity_paper_simulation_fill_contains_broker_order_id:{timestamp}")
        if str(fill.get("exchange_order_id", "")):
            blockers.append(f"us_equity_paper_simulation_fill_contains_exchange_order_id:{timestamp}")

    rows = []
    for target in targets:
        timestamp = str(target.get("timestamp") or _nested(target, "target_position.date", ""))
        rebalance = _mapping(target.get("rebalance"))
        if not rebalance:
            blockers.append(f"us_equity_paper_simulation_target_rebalance_missing:{timestamp}")
        expected = _float_or(rebalance.get("estimated_trade_notional"), 0.0)
        date_fills = fills_by_date.get(timestamp, [])
        actual = sum(abs(_float_or(fill.get("notional"), 0.0)) for fill in date_fills)
        diff = round(actual - expected, 8)
        passed = bool(rebalance) and abs(diff) <= 0.01
        if expected > 0.01 and not date_fills:
            blockers.append(f"us_equity_paper_simulation_expected_fills_missing:{timestamp}")
            passed = False
        if expected <= 0.01 and actual > 0.01:
            blockers.append(f"us_equity_paper_simulation_unexpected_fills_for_zero_turnover:{timestamp}")
            passed = False
        if bool(rebalance) and abs(diff) > 0.01:
            blockers.append(f"us_equity_paper_simulation_trade_notional_mismatch:{timestamp}")
        rows.append(
            {
                "timestamp": timestamp,
                "expected_trade_notional": round(expected, 6),
                "actual_fill_notional": round(actual, 6),
                "fill_count": len(date_fills),
                "diff": diff,
                "passed": passed,
            }
        )
    return {
        "passed": not blockers,
        "checked_count": len(rows),
        "failed_count": sum(1 for row in rows if row["passed"] is not True),
        "rows": rows[-5:],
        "blockers": _dedupe(blockers),
    }


def _target_change_count(targets: list[dict[str, Any]]) -> int:
    last = None
    changes = 0
    for row in targets:
        weights = json.dumps(_nested(row, "target_position.weights", {}), sort_keys=True)
        if last is not None and weights != last:
            changes += 1
        last = weights
    return changes


def _max_drawdown(equity: list[float]) -> float:
    peak = 0.0
    mdd = 0.0
    for value in equity:
        if value <= 0:
            continue
        peak = max(peak, value)
        if peak > 0:
            mdd = min(mdd, value / peak - 1.0)
    return round(mdd, 6)


def _markdown(payload: Mapping[str, Any]) -> str:
    metrics = _mapping(payload.get("metrics"))
    replay = _mapping(_mapping(payload.get("ledger_checks")).get("ledger_pnl_replay"))
    lines = [
        "# US Equity 纸面模拟评估",
        "",
        f"- generated_at: `{payload.get('generated_at', '')}`",
        f"- status: `{payload.get('status', '')}`",
        f"- decision: `{payload.get('decision', '')}`",
        f"- paper_days: `{metrics.get('paper_days', 0)}`",
        f"- target_position_count: `{metrics.get('target_position_count', 0)}`",
        f"- fill_count: `{metrics.get('fill_count', 0)}`",
        f"- ledger_pnl_replay: `{replay.get('status', '')}`",
        f"- ledger_pnl_source: `{replay.get('source', '')}`",
        "",
        "本报告只评估纸面模拟账本质量，不解锁 paper/live。",
        "",
        "## Blockers",
        "",
    ]
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, Mapping):
            rows.append(dict(payload))
    return rows


def _read_daily_reports(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_dir():
        return []
    rows = []
    for item in sorted(path.glob("*.json")):
        payload = _read_json(item)
        if payload:
            rows.append(payload)
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _unsafe_flags(payloads: Mapping[str, Mapping[str, Any]]) -> list[str]:
    keys = {
        "paper_or_live_unlock_allowed",
        "paper_simulation_allowed",
        "live_order_allowed",
        "private_endpoint_allowed",
        "private_endpoint_used",
        "order_endpoint_allowed",
        "order_endpoint_used",
        "real_order_submitted",
        "broker_calls_used",
    }
    out = []
    for root_name, payload in payloads.items():
        for path, value in _walk(payload):
            if path.split(".")[-1] in keys and value is True:
                out.append(f"{root_name}.{path}=true")
    return out


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_walk(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out.extend(_walk(child, f"{prefix}.{index}"))
    else:
        out.append((prefix, value))
    return out


def _nested(value: Any, dotted: str, default: Any = None) -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _float_or(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _dedupe(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
