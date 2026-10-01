#!/usr/bin/env python3
"""Build the US ETF forward-observation daily health report.

This report checks whether the forward-observation operating loop is healthy.
It is not alpha validation and it cannot unlock paper or live trading.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_etf_forward_observation_daily_health_report_v1"
DEFAULT_DAILY_RUN_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_daily_run_report.json")
DEFAULT_ROLL_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json")
DEFAULT_EVALUATION_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json")
DEFAULT_LEDGER_ROOT = Path("data/forward_observation/us_etf_rotation_v1")
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_daily_health_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US ETF 轮动 Forward Observation 日更健康报告.md")
ALLOWED_STATUSES = {"daily_health_pass", "daily_health_observing_stale", "daily_health_blocked"}
STALE_AFTER_DAYS = 2


def build_us_etf_forward_observation_daily_health_report(
    *,
    repo_root: Path | None = None,
    daily_run_report: Path = DEFAULT_DAILY_RUN_REPORT,
    roll_report: Path = DEFAULT_ROLL_REPORT,
    evaluation_report: Path = DEFAULT_EVALUATION_REPORT,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
    stale_after_days: int = STALE_AFTER_DAYS,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    daily_path = _resolve(root, daily_run_report)
    roll_path = _resolve(root, roll_report)
    evaluation_path = _resolve(root, evaluation_report)
    ledger = _resolve(root, ledger_root)
    daily = _read_json(daily_path)
    roll = _read_json(roll_path)
    evaluation = _read_json(evaluation_path)
    state = _read_json(ledger / "validation_state.json")
    targets = _read_jsonl(ledger / "target_positions.jsonl")
    fills = _read_jsonl(ledger / "fills.jsonl")
    snapshots = _read_jsonl(ledger / "portfolio_snapshots.jsonl")

    checks = {
        "source_reports_exist": _check_source_reports(daily_path, roll_path, evaluation_path),
        "daily_run_passed": _check_daily_run(daily),
        "roll_report_passed": _check_roll(roll),
        "evaluation_status_safe": _check_evaluation(evaluation),
        "ledger_files_exist": _check_ledger_files(ledger),
        "ledger_state_consistent": _check_state_consistency(state, targets, fills, snapshots, evaluation),
        "ledger_dates_consistent": _check_ledger_dates(targets, snapshots),
        "guardrails_safe": _check_no_unsafe_flags(
            {"daily_run": daily, "roll": roll, "evaluation": evaluation, "state": state, "targets": targets, "fills": fills, "snapshots": snapshots}
        ),
    }
    blockers: list[str] = []
    for name, check in checks.items():
        if not bool(check.get("passed", False)):
            blockers.append(f"us_etf_forward_daily_health_{name}_failed")

    freshness = _check_daily_freshness(daily, generated, stale_after_days)
    warnings = []
    if not freshness["passed"]:
        warnings.append("us_etf_forward_daily_health_generated_at_stale")

    if blockers:
        status = "daily_health_blocked"
    elif warnings:
        status = "daily_health_observing_stale"
    else:
        status = "daily_health_pass"

    metrics = _mapping(evaluation.get("metrics"))
    forward = _mapping(daily.get("forward_observation"))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "pipeline": "us_etf_forward_observation_daily_health",
        "status": status,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "decision": "repair_forward_observation_daily_loop" if status == "daily_health_blocked" else "continue_forward_observation",
        "daily_run_status": str(daily.get("status", "")),
        "roll_status": str(roll.get("status", "")),
        "roll_cycle_status": str(roll.get("cycle_status", "")),
        "evaluation_status": str(evaluation.get("status", "")),
        "observation_days": int(metrics.get("observation_days", forward.get("observation_days", 0)) or 0),
        "minimum_complete_days": int(evaluation.get("minimum_complete_days", forward.get("minimum_complete_days", 30)) or 30),
        "latest_observation_date": metrics.get("latest_observation_date") or state.get("last_processed_timestamp"),
        "daily_run_generated_at": daily.get("generated_at"),
        "freshness": freshness,
        "observation_continuity": _mapping(evaluation.get("observation_continuity")),
        "ledger": {
            "ledger_root": _relpath(ledger, root),
            "target_position_rows": len(targets),
            "fill_rows": len(fills),
            "portfolio_snapshot_rows": len(snapshots),
            "state_days_completed": state.get("days_completed"),
            "state_last_processed_timestamp": state.get("last_processed_timestamp"),
        },
        "scheduler": _mapping(daily.get("scheduler")),
        "checks": checks,
        "warnings": _dedupe(warnings),
        "blockers": _dedupe(blockers),
        "source_files": {
            "daily_run_report": _relpath(daily_path, root),
            "roll_report": _relpath(roll_path, root),
            "evaluation_report": _relpath(evaluation_path, root),
            "ledger_root": _relpath(ledger, root),
            "target_positions": _relpath(ledger / "target_positions.jsonl", root),
            "fills": _relpath(ledger / "fills.jsonl", root),
            "portfolio_snapshots": _relpath(ledger / "portfolio_snapshots.jsonl", root),
            "validation_state": _relpath(ledger / "validation_state.json", root),
        },
        "guardrails": {
            "daily_health_is_not_alpha_validation": True,
            "long_term_positive_expectancy_proven": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "broker_calls_used": False,
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


def _check_source_reports(*paths: Path) -> dict[str, Any]:
    missing = [_relpath(path, Path.cwd()) for path in paths if not path.exists()]
    return {"passed": not missing, "missing": missing}


def _check_daily_run(daily: Mapping[str, Any]) -> dict[str, Any]:
    guardrails = _mapping(daily.get("guardrails"))
    return {
        "passed": (
            str(daily.get("status", "")) == "PASS"
            and guardrails.get("daily_run_is_not_alpha_validation") is True
            and guardrails.get("paper_or_live_unlock_allowed") is False
            and guardrails.get("paper_simulation_allowed") is False
            and guardrails.get("live_order_allowed") is False
            and guardrails.get("private_endpoint_allowed") is False
            and guardrails.get("order_endpoint_allowed") is False
        ),
        "status": daily.get("status"),
        "blockers": _list_of_str(daily.get("blockers")),
    }


def _check_roll(roll: Mapping[str, Any]) -> dict[str, Any]:
    guardrails = _mapping(roll.get("guardrails"))
    operational = _mapping(roll.get("operational_checks"))
    return {
        "passed": (
            str(roll.get("status", "")) == "PASS"
            and str(operational.get("status", "PASS")) == "PASS"
            and guardrails.get("forward_observation_is_not_alpha_validation") is True
            and guardrails.get("paper_or_live_unlock_allowed") is False
            and guardrails.get("live_order_allowed") is False
        ),
        "status": roll.get("status"),
        "cycle_status": roll.get("cycle_status"),
        "blockers": _list_of_str(roll.get("blockers")),
    }


def _check_evaluation(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    guardrails = _mapping(evaluation.get("guardrails"))
    return {
        "passed": (
            str(evaluation.get("status", "")) in {"forward_observing", "forward_complete_for_manual_review"}
            and guardrails.get("forward_evaluation_is_not_alpha_validation") is True
            and guardrails.get("paper_or_live_unlock_allowed") is False
            and guardrails.get("paper_simulation_allowed") is False
            and guardrails.get("live_order_allowed") is False
        ),
        "status": evaluation.get("status"),
        "blockers": _list_of_str(evaluation.get("blockers")),
    }


def _check_ledger_files(ledger: Path) -> dict[str, Any]:
    files = {
        "target_positions": ledger / "target_positions.jsonl",
        "fills": ledger / "fills.jsonl",
        "portfolio_snapshots": ledger / "portfolio_snapshots.jsonl",
        "validation_state": ledger / "validation_state.json",
    }
    missing = [name for name, path in files.items() if not path.exists()]
    return {"passed": not missing, "missing": missing}


def _check_state_consistency(
    state: Mapping[str, Any],
    targets: list[Mapping[str, Any]],
    fills: list[Mapping[str, Any]],
    snapshots: list[Mapping[str, Any]],
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    metrics = _mapping(evaluation.get("metrics"))
    return {
        "passed": (
            bool(state)
            and int(state.get("days_completed", -1)) == len(snapshots)
            and int(state.get("target_position_count", -1)) == len(targets)
            and int(state.get("fill_count", -1)) == len(fills)
            and int(metrics.get("observation_days", -1)) == len(snapshots)
            and int(metrics.get("target_position_rows", -1)) == len(targets)
            and int(metrics.get("simulated_fill_count", -1)) == len(fills)
        ),
        "state_days_completed": state.get("days_completed"),
        "target_rows": len(targets),
        "snapshot_rows": len(snapshots),
        "fill_rows": len(fills),
        "evaluation_metrics": metrics,
    }


def _check_ledger_dates(targets: list[Mapping[str, Any]], snapshots: list[Mapping[str, Any]]) -> dict[str, Any]:
    target_dates = sorted({str(row.get("timestamp", "")) for row in targets if row.get("timestamp")})
    snapshot_dates = sorted({str(row.get("timestamp", "")) for row in snapshots if row.get("timestamp")})
    return {"passed": bool(target_dates) and target_dates == snapshot_dates, "target_dates": target_dates, "snapshot_dates": snapshot_dates}


def _check_daily_freshness(daily: Mapping[str, Any], generated_at: str, stale_after_days: int) -> dict[str, Any]:
    report_dt = _parse_utc(str(daily.get("generated_at", "")))
    current_dt = _parse_utc(generated_at)
    if report_dt is None or current_dt is None:
        return {"passed": False, "age_days": None, "stale_after_days": stale_after_days, "reason": "timestamp_parse_failed"}
    age_days = max(0, (current_dt.date() - report_dt.date()).days)
    return {"passed": age_days <= stale_after_days, "age_days": age_days, "stale_after_days": stale_after_days}


def _check_no_unsafe_flags(payloads: Mapping[str, Any]) -> dict[str, Any]:
    unsafe = []
    unsafe_keys = {
        "live_order_allowed",
        "private_endpoint_used",
        "private_endpoint_allowed",
        "order_endpoint_used",
        "order_endpoint_allowed",
        "real_order_submitted",
        "paper_or_live_unlock_allowed",
        "paper_simulation_allowed",
        "broker_calls_used",
    }
    for root_name, payload in payloads.items():
        for path, value in _walk(payload):
            if path.split(".")[-1] in unsafe_keys and value is True:
                unsafe.append(f"{root_name}.{path}=true")
    return {"passed": not unsafe, "unsafe_flags": unsafe}


def _markdown(payload: Mapping[str, Any]) -> str:
    ledger = _mapping(payload.get("ledger"))
    freshness = _mapping(payload.get("freshness"))
    lines = [
        "# US ETF 轮动 Forward Observation 日更健康报告",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- status: `{payload.get('status')}`",
        f"- decision: `{payload.get('decision')}`",
        f"- daily_run_status: `{payload.get('daily_run_status')}`",
        f"- roll_status: `{payload.get('roll_status')}`",
        f"- evaluation_status: `{payload.get('evaluation_status')}`",
        f"- observation_days: `{payload.get('observation_days')}` / `{payload.get('minimum_complete_days')}`",
        f"- latest_observation_date: `{payload.get('latest_observation_date')}`",
        f"- daily_run_generated_at: `{payload.get('daily_run_generated_at')}`",
        f"- freshness_age_days: `{freshness.get('age_days')}`",
        "",
        "## Ledger",
        "",
        f"- ledger_root: `{ledger.get('ledger_root')}`",
        f"- target_position_rows: `{ledger.get('target_position_rows')}`",
        f"- portfolio_snapshot_rows: `{ledger.get('portfolio_snapshot_rows')}`",
        f"- fill_rows: `{ledger.get('fill_rows')}`",
        f"- state_days_completed: `{ledger.get('state_days_completed')}`",
        "",
        "## Checks",
        "",
        "| Check | Passed |",
        "|---|---:|",
    ]
    for name, check in _mapping(payload.get("checks")).items():
        lines.append(f"| `{name}` | `{_mapping(check).get('passed')}` |")
    lines.extend(["", "## Warnings", ""])
    warnings = _list_of_str(payload.get("warnings"))
    lines.extend([f"- `{item}`" for item in warnings] if warnings else ["- None"])
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This health report only verifies daily operational continuity.",
            "- It is not Alpha validation and cannot prove long-term positive expectancy.",
            "- It does not allow paper simulation, live orders, private endpoints, or order endpoints.",
            "",
        ]
    )
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_jsonl(path: Path) -> list[Mapping[str, Any]]:
    if not path.exists():
        return []
    rows: list[Mapping[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, Mapping):
            rows.append(item)
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(_jsonable(payload), indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)
    except OSError:
        return None
    value = result.stdout.strip()
    return value or None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--daily-run-report", type=Path, default=DEFAULT_DAILY_RUN_REPORT)
    parser.add_argument("--roll-report", type=Path, default=DEFAULT_ROLL_REPORT)
    parser.add_argument("--evaluation-report", type=Path, default=DEFAULT_EVALUATION_REPORT)
    parser.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--stale-after-days", type=int, default=STALE_AFTER_DAYS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_us_etf_forward_observation_daily_health_report(
        repo_root=args.repo_root,
        daily_run_report=args.daily_run_report,
        roll_report=args.roll_report,
        evaluation_report=args.evaluation_report,
        ledger_root=args.ledger_root,
        output=args.output,
        markdown_output=args.markdown_output,
        stale_after_days=args.stale_after_days,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] != "daily_health_blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
