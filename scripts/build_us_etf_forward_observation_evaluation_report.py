#!/usr/bin/env python3
"""Evaluate US ETF forward-observation operational quality.

The evaluation only reviews forward-record quality. It does not validate alpha
or unlock paper/live trading.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_etf_forward_observation_evaluation_v1"
DEFAULT_LEDGER_ROOT = Path("data/forward_observation/us_etf_rotation_v1")
DEFAULT_ROLL_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json")
DEFAULT_DAILY_RUN_REPORT_ROOT = Path("artifacts/us_equity_etf_macro_rotation/latest")
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US ETF 轮动 Forward Observation 评估.md")
MIN_COMPLETE_DAYS = 30
REVIEW_MILESTONES = [30, 60, 90]
ALLOWED_STATUSES = {"forward_observing", "forward_complete_for_manual_review", "forward_blocked"}


def build_us_etf_forward_observation_evaluation_report(
    *,
    repo_root: Path | None = None,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    roll_report: Path = DEFAULT_ROLL_REPORT,
    daily_run_report_root: Path = DEFAULT_DAILY_RUN_REPORT_ROOT,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    ledger = _resolve(root, ledger_root)
    roll_path = _resolve(root, roll_report)
    daily_root = _resolve(root, daily_run_report_root)
    roll = _read_json(roll_path)
    daily_runs = _read_daily_run_reports(daily_root)
    data_gate_summary = _data_gate_summary(daily_runs)
    targets = _read_jsonl(ledger / "target_positions.jsonl")
    fills = _read_jsonl(ledger / "fills.jsonl")
    snapshots = _read_jsonl(ledger / "portfolio_snapshots.jsonl")
    state = _read_json(ledger / "validation_state.json")

    target_dates = [str(row.get("timestamp", "")) for row in targets if row.get("timestamp")]
    snapshot_dates = [str(row.get("timestamp", "")) for row in snapshots if row.get("timestamp")]
    fill_dates = [str(row.get("timestamp", "")) for row in fills if row.get("timestamp")]
    observation_days = len(set(snapshot_dates))
    observation_continuity = _observation_continuity(target_dates, snapshot_dates, fill_dates, state)
    target_change_count = sum(1 for row in targets if _float_or(_nested(row, "rebalance.turnover", 0.0), 0.0) > 1e-12)
    simulated_fill_count = len(fills)
    checks = {
        "ledger_files_exist": _check_ledger_files(ledger),
        "target_snapshot_continuity": _check_target_snapshot_continuity(target_dates, snapshot_dates),
        "observation_continuity": observation_continuity,
        "ledger_recalculation": _check_ledger_recalculation(snapshots),
        "target_fill_consistency": _check_target_fill_consistency(targets, fills),
        "rule_consistency": _check_rule_consistency(targets, snapshots),
        "roll_report_scope": _check_roll_scope(roll),
        "daily_data_gate": _check_daily_data_gate(data_gate_summary),
        "state_consistency": _check_state_consistency(state, observation_days, targets, fills),
        "no_live_or_order_flags": _check_no_unsafe_flags({"roll_report": roll, "state": state, "targets": targets, "fills": fills, "snapshots": snapshots}),
    }
    blockers = []
    for name, check in checks.items():
        if not bool(check.get("passed", False)):
            blockers.append(f"us_etf_forward_evaluation_{name}_failed")
    if not snapshots:
        blockers.append("us_etf_forward_evaluation_no_snapshots")
    if blockers:
        status = "forward_blocked"
    elif observation_days >= MIN_COMPLETE_DAYS:
        status = "forward_complete_for_manual_review"
    else:
        status = "forward_observing"
    review_progress = _review_progress(observation_days, status)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "strategy_id": str(state.get("strategy_id") or roll.get("strategy_id") or "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x"),
        "candidate_variant": str(state.get("candidate_variant") or roll.get("candidate_variant") or ""),
        "status": status,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "decision": "continue_observing" if status == "forward_observing" else ("manual_review_required" if status == "forward_complete_for_manual_review" else "repair_forward_observation"),
        "minimum_complete_days": MIN_COMPLETE_DAYS,
        "review_milestones": REVIEW_MILESTONES,
        "review_progress": review_progress,
        "metrics": {
            "observation_days": observation_days,
            "target_position_rows": len(targets),
            "portfolio_snapshot_rows": len(snapshots),
            "target_change_count": target_change_count,
            "simulated_fill_count": simulated_fill_count,
            "latest_observation_date": max(snapshot_dates) if snapshot_dates else None,
            "total_estimated_slippage": round(sum(_float_or(row.get("estimated_slippage"), 0.0) for row in snapshots), 6),
            "total_estimated_financing": round(sum(_float_or(row.get("estimated_financing_daily"), 0.0) for row in snapshots), 6),
            "max_drawdown": _max_drawdown([_float_or(row.get("equity"), 0.0) for row in snapshots]),
            "daily_run_count": data_gate_summary["daily_run_count"],
            "data_gate_pass_count": data_gate_summary["pass_count"],
            "data_gate_blocked_count": data_gate_summary["blocked_count"],
        },
        "observation_continuity": observation_continuity,
        "daily_data_gate": data_gate_summary,
        "checks": checks,
        "blockers": _dedupe(blockers),
        "source_files": {
            "ledger_root": _relpath(ledger, root),
            "roll_report": _relpath(roll_path, root),
            "daily_run_report_root": _relpath(daily_root, root),
            "target_positions": _relpath(ledger / "target_positions.jsonl", root),
            "fills": _relpath(ledger / "fills.jsonl", root),
            "portfolio_snapshots": _relpath(ledger / "portfolio_snapshots.jsonl", root),
            "validation_state": _relpath(ledger / "validation_state.json", root),
        },
        "guardrails": {
            "evaluation_scope": "operational_quality_only",
            "forward_evaluation_is_not_alpha_validation": True,
            "long_term_positive_expectancy_proven": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    if payload["status"] not in ALLOWED_STATUSES:
        raise AssertionError(f"invalid status: {payload['status']}")
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _check_ledger_files(ledger: Path) -> dict[str, Any]:
    files = {
        "target_positions": ledger / "target_positions.jsonl",
        "fills": ledger / "fills.jsonl",
        "portfolio_snapshots": ledger / "portfolio_snapshots.jsonl",
        "validation_state": ledger / "validation_state.json",
    }
    missing = [name for name, path in files.items() if not path.exists()]
    return {"passed": not missing, "missing": missing}


def _review_progress(observation_days: int, status: str) -> dict[str, Any]:
    completed = [day for day in REVIEW_MILESTONES if observation_days >= day]
    next_candidates = [day for day in REVIEW_MILESTONES if observation_days < day]
    next_milestone = next_candidates[0] if next_candidates else None
    days_until_minimum = max(MIN_COMPLETE_DAYS - observation_days, 0)
    return {
        "observation_days": observation_days,
        "minimum_complete_days": MIN_COMPLETE_DAYS,
        "review_milestones": REVIEW_MILESTONES,
        "completed_milestones": completed,
        "next_milestone": next_milestone,
        "days_until_minimum": days_until_minimum,
        "manual_review_required": status == "forward_complete_for_manual_review",
        "manual_review_only_no_paper_or_live_unlock": status == "forward_complete_for_manual_review",
        "alpha_validation_claim_allowed": False,
        "paper_or_live_unlock_allowed": False,
    }


def _check_target_snapshot_continuity(target_dates: list[str], snapshot_dates: list[str]) -> dict[str, Any]:
    return {
        "passed": bool(target_dates) and bool(snapshot_dates) and set(target_dates) == set(snapshot_dates),
        "target_dates": sorted(set(target_dates)),
        "snapshot_dates": sorted(set(snapshot_dates)),
    }


def _check_ledger_recalculation(snapshots: list[Mapping[str, Any]]) -> dict[str, Any]:
    failures = []
    for row in snapshots:
        expected = _float_or(row.get("prior_equity"), 0.0) - _float_or(row.get("estimated_slippage"), 0.0) - _float_or(
            row.get("estimated_financing_daily"),
            0.0,
        )
        actual = _float_or(row.get("equity"), 0.0)
        if abs(expected - actual) > 0.01 or row.get("reconciliation_status") != "clean":
            failures.append({"timestamp": row.get("timestamp"), "expected": round(expected, 6), "actual": actual})
    return {"passed": not failures and bool(snapshots), "failures": failures}


def _check_target_fill_consistency(targets: list[Mapping[str, Any]], fills: list[Mapping[str, Any]]) -> dict[str, Any]:
    fill_count_by_date: dict[str, int] = {}
    for fill in fills:
        ts = str(fill.get("timestamp", ""))
        fill_count_by_date[ts] = fill_count_by_date.get(ts, 0) + 1
    failures = []
    for row in targets:
        ts = str(row.get("timestamp", ""))
        turnover = _float_or(_nested(row, "rebalance.turnover", 0.0), 0.0)
        if turnover > 1e-12 and fill_count_by_date.get(ts, 0) == 0:
            failures.append({"timestamp": ts, "turnover": turnover, "reason": "turnover_without_fill"})
        if not row.get("reason"):
            failures.append({"timestamp": ts, "reason": "missing_reason"})
    return {"passed": not failures and bool(targets), "failures": failures, "fill_count_by_date": fill_count_by_date}


def _check_rule_consistency(targets: list[Mapping[str, Any]], snapshots: list[Mapping[str, Any]]) -> dict[str, Any]:
    failures = []
    snapshot_by_ts = {str(row.get("timestamp", "")): row for row in snapshots}
    for row in targets:
        ts = str(row.get("timestamp", ""))
        target_date = str(_nested(row, "target_position.date", ""))
        if ts != target_date:
            failures.append({"timestamp": ts, "target_date": target_date, "reason": "timestamp_target_date_mismatch"})
        snap = snapshot_by_ts.get(ts, {})
        if snap and int(_nested(row, "target_position.target_count", -1)) != int(snap.get("target_count", -2)):
            failures.append({"timestamp": ts, "reason": "target_count_mismatch"})
    return {"passed": not failures and bool(targets), "failures": failures}


def _check_roll_scope(roll: Mapping[str, Any]) -> dict[str, Any]:
    guardrails = _mapping(roll.get("guardrails"))
    alpha = _mapping(roll.get("alpha_validation"))
    operational = _mapping(roll.get("operational_checks"))
    return {
        "passed": (
            str(roll.get("status", "")) == "PASS"
            and guardrails.get("forward_observation_is_not_alpha_validation") is True
            and guardrails.get("paper_or_live_unlock_allowed") is False
            and alpha.get("alpha_validated") is False
            and str(operational.get("status", "")) == "PASS"
        ),
        "roll_status": roll.get("status"),
        "operational_checks_status": operational.get("status"),
    }


def _check_daily_data_gate(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "passed": int(summary.get("blocked_count", 0) or 0) == 0,
        "daily_run_count": summary.get("daily_run_count"),
        "pass_count": summary.get("pass_count"),
        "blocked_count": summary.get("blocked_count"),
        "blocked_reports": summary.get("blocked_reports", []),
    }


def _check_state_consistency(state: Mapping[str, Any], observation_days: int, targets: list[Mapping[str, Any]], fills: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "passed": (
            bool(state)
            and int(state.get("days_completed", -1)) == observation_days
            and int(state.get("target_position_count", -1)) == len(targets)
            and int(state.get("fill_count", -1)) == len(fills)
        ),
        "state_days_completed": state.get("days_completed"),
        "state_target_position_count": state.get("target_position_count"),
        "state_fill_count": state.get("fill_count"),
        "observed_days": observation_days,
        "target_rows": len(targets),
        "fill_rows": len(fills),
    }


def _observation_continuity(
    target_dates: list[str],
    snapshot_dates: list[str],
    fill_dates: list[str],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    target_unique = sorted(set(target_dates))
    snapshot_unique = sorted(set(snapshot_dates))
    duplicate_target_dates = sorted({date for date in target_dates if target_dates.count(date) > 1})
    duplicate_snapshot_dates = sorted({date for date in snapshot_dates if snapshot_dates.count(date) > 1})
    missing_snapshot_for_target = sorted(set(target_unique) - set(snapshot_unique))
    missing_target_for_snapshot = sorted(set(snapshot_unique) - set(target_unique))
    latest_observation_date = snapshot_unique[-1] if snapshot_unique else None
    state_last = state.get("last_processed_timestamp")
    gaps = _calendar_gaps(snapshot_unique)
    passed = (
        bool(snapshot_unique)
        and not duplicate_target_dates
        and not duplicate_snapshot_dates
        and not missing_snapshot_for_target
        and not missing_target_for_snapshot
        and state_last == latest_observation_date
    )
    return {
        "passed": passed,
        "first_observation_date": snapshot_unique[0] if snapshot_unique else None,
        "latest_observation_date": latest_observation_date,
        "unique_observation_days": len(snapshot_unique),
        "duplicate_target_dates": duplicate_target_dates,
        "duplicate_snapshot_dates": duplicate_snapshot_dates,
        "missing_snapshot_for_target": missing_snapshot_for_target,
        "missing_target_for_snapshot": missing_target_for_snapshot,
        "state_last_processed_timestamp": state_last,
        "fill_dates_without_snapshot": sorted(set(fill_dates) - set(snapshot_unique)),
        "calendar_gaps": gaps,
        "max_calendar_gap_days": max([gap["gap_days"] for gap in gaps], default=0),
        "note": "Calendar gaps are informational; weekends and market holidays are not treated as failures by this check.",
    }


def _calendar_gaps(sorted_dates: list[str]) -> list[dict[str, Any]]:
    parsed = [(date, _parse_date(date)) for date in sorted_dates]
    rows = []
    for (prev_text, prev_date), (next_text, next_date) in zip(parsed, parsed[1:]):
        if prev_date is None or next_date is None:
            continue
        gap_days = (next_date - prev_date).days
        if gap_days > 1:
            rows.append({"previous": prev_text, "next": next_text, "gap_days": gap_days})
    return rows


def _check_no_unsafe_flags(payloads: Mapping[str, Any]) -> dict[str, Any]:
    unsafe = []
    for root_name, payload in payloads.items():
        for path, value in _walk(payload):
            key = path.split(".")[-1]
            if key in {"live_order_allowed", "private_endpoint_used", "order_endpoint_used", "real_order_submitted", "paper_or_live_unlock_allowed"} and value is True:
                unsafe.append(f"{root_name}.{path}=true")
    return {"passed": not unsafe, "unsafe_flags": unsafe}


def _max_drawdown(equity_values: list[float]) -> float:
    if not equity_values:
        return 0.0
    peak = equity_values[0]
    max_dd = 0.0
    for value in equity_values:
        if value > peak:
            peak = value
        if peak > 0:
            max_dd = min(max_dd, value / peak - 1.0)
    return round(max_dd, 8)


def _read_daily_run_reports(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    reports: list[dict[str, Any]] = []
    for path in sorted(root.glob("us_etf_forward_observation_daily_run_report*.json")):
        payload = _read_json(path)
        if payload:
            payload = dict(payload)
            payload["_source_report"] = path
            reports.append(payload)
    return reports


def _parse_date(value: str):
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def _data_gate_summary(reports: list[Mapping[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    blocked_reports: list[str] = []
    for report in reports:
        source = report.get("_source_report")
        source_text = str(source) if source else ""
        data_gate = _nested(report, "steps.data_gate", default={})
        if not isinstance(data_gate, Mapping):
            data_gate = {}
        status = str(data_gate.get("status") or "missing")
        blockers = _list_of_str(data_gate.get("blockers"))
        checks = data_gate.get("checks", [])
        check_rows = []
        if isinstance(checks, list):
            for check in checks:
                if isinstance(check, Mapping):
                    check_rows.append(
                        {
                            "check_id": str(check.get("check_id") or ""),
                            "status": str(check.get("status") or ""),
                            "passed": bool(check.get("passed", False)),
                            "first_blocker": _list_of_str(check.get("blockers"))[0] if _list_of_str(check.get("blockers")) else "",
                        }
                    )
        if status != "pass" or blockers:
            blocked_reports.append(source_text)
        rows.append(
            {
                "source_report": source_text,
                "status": status,
                "blockers": blockers,
                "checks": check_rows,
            }
        )
    return {
        "daily_run_count": len(rows),
        "pass_count": sum(1 for row in rows if row["status"] == "pass" and not row["blockers"]),
        "blocked_count": sum(1 for row in rows if row["status"] != "pass" or row["blockers"]),
        "blocked_reports": blocked_reports,
        "reports": rows[:30],
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    metrics = _mapping(payload.get("metrics"))
    data_gate = _mapping(payload.get("daily_data_gate"))
    progress = _mapping(payload.get("review_progress"))
    lines = [
        "# US ETF 轮动 Forward Observation 评估",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- status: `{payload.get('status')}`",
        f"- decision: `{payload.get('decision')}`",
        f"- observation_days: `{metrics.get('observation_days')}`",
        f"- next_milestone: `{progress.get('next_milestone')}`",
        f"- days_until_minimum: `{progress.get('days_until_minimum')}`",
        f"- manual_review_required: `{progress.get('manual_review_required')}`",
        f"- target_change_count: `{metrics.get('target_change_count')}`",
        f"- simulated_fill_count: `{metrics.get('simulated_fill_count')}`",
        f"- data_gate_blocked_count: `{data_gate.get('blocked_count')}`",
        f"- live_order_allowed: `{_nested(payload, 'guardrails.live_order_allowed', False)}`",
        "",
        "## 边界",
        "",
        "- 本评估只判断 forward observation 运行质量。",
        "- 本评估不验证 Alpha，不证明长期正期望，不自动解锁 paper/live。",
        "",
        "## Checks",
        "",
        "| Check | Passed |",
        "|---|---:|",
    ]
    for name, check in _mapping(payload.get("checks")).items():
        lines.append(f"| `{name}` | `{bool(_mapping(check).get('passed', False))}` |")
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers)
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (root / path).resolve()


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _nested(payload: Mapping[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = payload
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _float_or(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_walk(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.extend(_walk(item, f"{prefix}.{index}"))
    else:
        out.append((prefix, value))
    return out


def _dedupe(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _git(args: list[str], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)
    except OSError:
        return None
    return result.stdout.strip() or None


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER_ROOT)
    parser.add_argument("--roll-report", type=Path, default=DEFAULT_ROLL_REPORT)
    parser.add_argument("--daily-run-report-root", type=Path, default=DEFAULT_DAILY_RUN_REPORT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_us_etf_forward_observation_evaluation_report(
        repo_root=args.repo_root,
        ledger_root=args.ledger_root,
        roll_report=args.roll_report,
        daily_run_report_root=args.daily_run_report_root,
        output=args.output,
        markdown_output=args.markdown_output,
    )
    print(json.dumps({"status": payload["status"], "output": payload["outputs"]["json"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
