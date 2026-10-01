#!/usr/bin/env python3
"""Run the daily US ETF forward-observation pipeline.

This scheduler entrypoint runs one target-position observation roll and rebuilds
the forward evaluation. It never calls broker, private, or order endpoints.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_us_etf_forward_observation_evaluation_report import (  # noqa: E402
    DEFAULT_LEDGER_ROOT,
    DEFAULT_MARKDOWN_OUTPUT as DEFAULT_EVALUATION_MARKDOWN,
    DEFAULT_OUTPUT as DEFAULT_EVALUATION_OUTPUT,
    build_us_etf_forward_observation_evaluation_report,
)
from scripts.run_us_etf_rotation_forward_observation import (  # noqa: E402
    DEFAULT_OUTPUT as DEFAULT_ROLL_OUTPUT,
    DEFAULT_VALIDATION_REPORT,
    run_us_etf_rotation_forward_observation,
)


SCHEMA_VERSION = "us_etf_forward_observation_daily_run_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_daily_run_report.json")
DEFAULT_DATA_FRESHNESS_REPORT = Path("artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json")
DEFAULT_KLINE_QUALITY_REPORT = Path("artifacts/us_equity_data_status/latest/us_equity_etf_kline_quality_daily_report.json")
DEFAULT_FRED_PREFLIGHT_REPORT = Path("artifacts/us_equity_data_status/latest/us_equity_fred_macro_preflight_report.json")
SCHEDULER_LOCAL_TIME = "09:20 Asia/Shanghai"
SCHEDULER_US_MARKET_NOTE = "Run after the prior US trading session data and validation reports have refreshed."

RollFn = Callable[..., Mapping[str, Any]]
EvaluationFn = Callable[..., Mapping[str, Any]]


def run_us_etf_forward_observation_daily(
    *,
    repo_root: Path | None = None,
    validation_report: Path = DEFAULT_VALIDATION_REPORT,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    roll_output: Path = DEFAULT_ROLL_OUTPUT,
    evaluation_output: Path = DEFAULT_EVALUATION_OUTPUT,
    evaluation_markdown: Path = DEFAULT_EVALUATION_MARKDOWN,
    data_freshness_report: Path = DEFAULT_DATA_FRESHNESS_REPORT,
    kline_quality_report: Path = DEFAULT_KLINE_QUALITY_REPORT,
    fred_preflight_report: Path = DEFAULT_FRED_PREFLIGHT_REPORT,
    output: Path = DEFAULT_OUTPUT,
    generated_at: str | None = None,
    roll_fn: RollFn = run_us_etf_rotation_forward_observation,
    evaluation_fn: EvaluationFn = build_us_etf_forward_observation_evaluation_report,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    output_path = _resolve(root, output)
    blockers: list[str] = []
    data_gate = _data_gate_status(
        root=root,
        data_freshness_report=data_freshness_report,
        kline_quality_report=kline_quality_report,
        fred_preflight_report=fred_preflight_report,
    )
    blockers.extend(_list_of_str(data_gate.get("blockers")))

    roll: dict[str, Any] | None = None
    if not blockers:
        roll = dict(
            roll_fn(
                repo_root=root,
                validation_report=validation_report,
                ledger_root=ledger_root,
                output=roll_output,
                generated_at=generated,
            )
        )
    if roll and str(roll.get("status", "")) != "PASS":
        blockers.extend(_list_of_str(roll.get("blockers")))
        blockers.append("us_etf_forward_daily_roll_not_pass")

    evaluation: dict[str, Any] | None = None
    if roll and not blockers:
        provisional_payload = _payload(
            generated_at=generated,
            status="PASS",
            roll=roll,
            evaluation=None,
            blockers=[],
            root=root,
            output_path=output_path,
            data_gate=data_gate,
            ledger_root=ledger_root,
            validation_report=validation_report,
            roll_output=roll_output,
            evaluation_output=evaluation_output,
        )
        # The evaluation scans daily-run reports for data-gate history. Persist
        # the current clean gate before evaluation to avoid reading yesterday's
        # blocked gate as today's state.
        _write_json(output_path, provisional_payload)
        evaluation = dict(
            evaluation_fn(
                repo_root=root,
                ledger_root=ledger_root,
                roll_report=roll_output,
                output=evaluation_output,
                markdown_output=evaluation_markdown,
                generated_at=generated,
            )
        )
        if str(evaluation.get("status", "")) not in {"forward_observing", "forward_complete_for_manual_review"}:
            blockers.extend(_list_of_str(evaluation.get("blockers")))
            blockers.append("us_etf_forward_daily_evaluation_blocked")

    payload = _payload(
        generated_at=generated,
        status="BLOCKED" if blockers else "PASS",
        roll=roll,
        evaluation=evaluation,
        blockers=_dedupe(blockers),
        root=root,
        output_path=output_path,
        data_gate=data_gate,
        ledger_root=ledger_root,
        validation_report=validation_report,
        roll_output=roll_output,
        evaluation_output=evaluation_output,
    )
    _write_json(output_path, payload)
    return payload


def _payload(
    *,
    generated_at: str,
    status: str,
    roll: Mapping[str, Any] | None,
    evaluation: Mapping[str, Any] | None,
    blockers: list[str],
    root: Path,
    output_path: Path,
    data_gate: Mapping[str, Any],
    ledger_root: Path,
    validation_report: Path,
    roll_output: Path,
    evaluation_output: Path,
    ) -> dict[str, Any]:
    evaluation_metrics = _mapping(evaluation.get("metrics")) if evaluation else {}
    roll_cycle = str(roll.get("cycle_status", "")) if roll else ""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": status,
        "asset": "us_equity",
        "pipeline": "us_etf_forward_observation_daily",
        "scheduler": {
            "intended_frequency": "daily_or_after_rebalance_signal_refresh",
            "recommended_local_time": SCHEDULER_LOCAL_TIME,
            "market_note": SCHEDULER_US_MARKET_NOTE,
        },
        "steps": {
            "data_gate": dict(data_gate),
            "roll": _step_summary(roll, roll_output),
            "evaluation": _step_summary(evaluation, evaluation_output),
        },
        "forward_observation": {
            "ledger_root": _relpath(_resolve(root, ledger_root), root),
            "validation_report": _relpath(_resolve(root, validation_report), root),
            "cycle_status": roll_cycle,
            "new_observation_written": roll_cycle == "COMPLETED",
            "already_processed": roll_cycle == "SKIPPED_ALREADY_COMPLETED",
            "evaluation_status": str(evaluation.get("status", "")) if evaluation else "",
            "observation_days": int(evaluation_metrics.get("observation_days", 0) or 0),
            "minimum_complete_days": int(evaluation.get("minimum_complete_days", 30) if evaluation else 30),
        },
        "blockers": blockers,
        "guardrails": {
            "simulated_only": True,
            "daily_run_is_not_alpha_validation": True,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "broker_calls_used": False,
        },
        "outputs": {
            "json": _relpath(output_path, root),
            "roll_report": _relpath(_resolve(root, roll_output), root),
            "evaluation_report": _relpath(_resolve(root, evaluation_output), root),
        },
    }


def _data_gate_status(
    *,
    root: Path,
    data_freshness_report: Path,
    kline_quality_report: Path,
    fred_preflight_report: Path,
) -> dict[str, Any]:
    reports = {
        "data_freshness": (_resolve(root, data_freshness_report), {"pass"}),
        "kline_quality": (_resolve(root, kline_quality_report), {"pass", "warn"}),
        "fred_preflight": (_resolve(root, fred_preflight_report), {"fred_macro_preflight_pass", "fred_macro_preflight_warn"}),
    }
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    for check_id, (path, allowed_statuses) in reports.items():
        payload = _read_json(path)
        status = str(payload.get("status") or "missing")
        report_blockers = _list_of_str(payload.get("blockers"))
        passed = bool(payload) and status in allowed_statuses and not report_blockers
        if not payload:
            blockers.append(f"us_etf_forward_daily_{check_id}_report_missing")
        elif status not in allowed_statuses:
            blockers.append(f"us_etf_forward_daily_{check_id}_status_not_safe:{status}")
        blockers.extend(f"us_etf_forward_daily_{check_id}:{item}" for item in report_blockers)
        checks.append(
            {
                "check_id": check_id,
                "status": status,
                "passed": passed,
                "blockers": report_blockers,
                "source_report": _relpath(path, root),
            }
        )
    return {
        "status": "pass" if not blockers else "blocked",
        "checks": checks,
        "blockers": _dedupe(blockers),
        "guardrails": {
            "data_gate_only": True,
            "stale_or_blocked_data_stops_forward_roll": True,
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
        },
    }


def _step_summary(payload: Mapping[str, Any] | None, path: Path) -> dict[str, Any]:
    if not payload:
        return {"status": "not_run", "path": str(path).replace("\\", "/"), "blockers": []}
    return {
        "status": str(payload.get("status", "")),
        "cycle_status": str(payload.get("cycle_status", "")),
        "path": str(path).replace("\\", "/"),
        "blockers": _list_of_str(payload.get("blockers")),
    }


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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run US ETF forward-observation daily pipeline.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--validation-report", default=str(DEFAULT_VALIDATION_REPORT))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--roll-output", default=str(DEFAULT_ROLL_OUTPUT))
    parser.add_argument("--evaluation-output", default=str(DEFAULT_EVALUATION_OUTPUT))
    parser.add_argument("--evaluation-markdown", default=str(DEFAULT_EVALUATION_MARKDOWN))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = run_us_etf_forward_observation_daily(
        repo_root=Path(args.repo_root),
        validation_report=Path(args.validation_report),
        ledger_root=Path(args.ledger_root),
        roll_output=Path(args.roll_output),
        evaluation_output=Path(args.evaluation_output),
        evaluation_markdown=Path(args.evaluation_markdown),
        output=Path(args.output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
