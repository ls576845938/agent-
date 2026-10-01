#!/usr/bin/env python3
"""Run the daily BTC raw trend forward-observation pipeline.

This is the scheduler entrypoint. It refreshes public OKX daily spot data, checks
the raw observation gate, appends at most one simulated observation cycle, and
rebuilds the evaluation report. It never calls broker, private, or order
endpoints.
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

from scripts.build_btc_trend_raw_forward_observation_evaluation import (  # noqa: E402
    DEFAULT_MARKDOWN_OUTPUT as DEFAULT_EVALUATION_MARKDOWN_REPORT,
    DEFAULT_OUTPUT as DEFAULT_EVALUATION_REPORT,
    build_btc_trend_raw_forward_observation_evaluation,
)
from scripts.check_btc_trend_raw_forward_observation_readiness import (  # noqa: E402
    DEFAULT_5M_FREEZE_REPORT,
    DEFAULT_BUNDLE_DIR,
    DEFAULT_LEDGER_ROOT,
    DEFAULT_OUTPUT as DEFAULT_READINESS_REPORT,
    DEFAULT_RAW_PLAN_REPORT,
    DEFAULT_TOP_VALIDATION_REPORT,
    DEFAULT_VOLATILITY_FREEZE_REPORT,
    check_btc_trend_raw_forward_observation_readiness,
)
from scripts.fetch_btc_okx_daily_history import (  # noqa: E402
    DEFAULT_BUNDLE_ID,
    DEFAULT_CAPTURE_REPORT,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_REQUEST_RETRY_BACKOFF_SECONDS,
    DEFAULT_REQUEST_RETRY_COUNT,
    capture_btc_okx_daily_history,
)
from scripts.run_btc_trend_raw_forward_observation_roll import (  # noqa: E402
    DEFAULT_FEE_BPS,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_OUTPUT as DEFAULT_ROLL_REPORT,
    run_btc_trend_raw_forward_observation_roll,
)


SCHEMA_VERSION = "btc_trend_raw_forward_observation_daily_run_v1"
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_daily_run_report.json")
DEFAULT_HISTORY_DAYS = 1825
DEFAULT_REQUEST_SLEEP_SECONDS = 0.12
SCHEDULER_LOCAL_TIME = "08:30 Asia/Shanghai"
SCHEDULER_UTC_TIME = "00:30 UTC"

CaptureFn = Callable[..., Mapping[str, Any]]
ReadinessFn = Callable[..., Mapping[str, Any]]
RollFn = Callable[..., Mapping[str, Any]]
EvaluationFn = Callable[..., Mapping[str, Any]]


def run_btc_trend_raw_forward_observation_daily(
    *,
    repo_root: Path | None = None,
    execute_network: bool = False,
    bundle_id: str = DEFAULT_BUNDLE_ID,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    bundle_dir: Path = DEFAULT_BUNDLE_DIR,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    capture_report: Path = DEFAULT_CAPTURE_REPORT,
    readiness_report: Path = DEFAULT_READINESS_REPORT,
    roll_report: Path = DEFAULT_ROLL_REPORT,
    evaluation_report: Path = DEFAULT_EVALUATION_REPORT,
    evaluation_markdown_report: Path = DEFAULT_EVALUATION_MARKDOWN_REPORT,
    output: Path = DEFAULT_OUTPUT,
    top_validation_report: Path = DEFAULT_TOP_VALIDATION_REPORT,
    raw_plan_report: Path = DEFAULT_RAW_PLAN_REPORT,
    volatility_freeze_report: Path = DEFAULT_VOLATILITY_FREEZE_REPORT,
    five_minute_freeze_report: Path = DEFAULT_5M_FREEZE_REPORT,
    history_days: int = DEFAULT_HISTORY_DAYS,
    request_sleep_seconds: float = DEFAULT_REQUEST_SLEEP_SECONDS,
    request_retry_count: int = DEFAULT_REQUEST_RETRY_COUNT,
    request_retry_backoff_seconds: float = DEFAULT_REQUEST_RETRY_BACKOFF_SECONDS,
    as_of: str = "",
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    fee_bps: float = DEFAULT_FEE_BPS,
    generated_at: str | None = None,
    capture_fn: CaptureFn = capture_btc_okx_daily_history,
    readiness_fn: ReadinessFn = check_btc_trend_raw_forward_observation_readiness,
    roll_fn: RollFn = run_btc_trend_raw_forward_observation_roll,
    evaluation_fn: EvaluationFn = build_btc_trend_raw_forward_observation_evaluation,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    output_path = _resolve(root, output)

    capture = dict(
        capture_fn(
            repo_root=root,
            bundle_id=bundle_id,
            output_root=output_root,
            capture_report=capture_report,
            execute_network=execute_network,
            history_days=history_days,
            request_sleep_seconds=request_sleep_seconds,
            request_retry_count=request_retry_count,
            request_retry_backoff_seconds=request_retry_backoff_seconds,
            captured_at=generated,
        )
    )
    if str(capture.get("status", "")) == "dry_run":
        payload = _payload(
            generated_at=generated,
            status="DRY_RUN",
            capture=capture,
            readiness=None,
            roll=None,
            evaluation=None,
            blockers=[],
            root=root,
            output_path=output_path,
            execute_network=execute_network,
            ledger_root=ledger_root,
        )
        _write_json(output_path, payload)
        return payload

    blockers = _capture_blockers(capture)
    readiness: dict[str, Any] | None = None
    roll: dict[str, Any] | None = None
    evaluation: dict[str, Any] | None = None

    if not blockers:
        readiness = dict(
            readiness_fn(
                repo_root=root,
                top_validation_report=top_validation_report,
                raw_plan_report=raw_plan_report,
                volatility_freeze_report=volatility_freeze_report,
                five_minute_freeze_report=five_minute_freeze_report,
                bundle_dir=bundle_dir,
                ledger_root=ledger_root,
                output=readiness_report,
                generated_at=generated,
            )
        )
        if str(readiness.get("status", "")) != "PASS":
            blockers.extend([str(item) for item in readiness.get("blockers", []) if item])
            blockers.append("btc_trend_raw_forward_daily_readiness_not_pass")

    if not blockers:
        roll = dict(
            roll_fn(
                repo_root=root,
                bundle_dir=bundle_dir,
                ledger_root=ledger_root,
                top_validation_report=top_validation_report,
                raw_plan_report=raw_plan_report,
                volatility_freeze_report=volatility_freeze_report,
                five_minute_freeze_report=five_minute_freeze_report,
                readiness_report=readiness_report,
                output=roll_report,
                as_of=as_of,
                initial_capital=initial_capital,
                fee_bps=fee_bps,
                generated_at=generated,
            )
        )
        if str(roll.get("status", "")) != "PASS":
            blockers.extend([str(item) for item in roll.get("blockers", []) if item])
            blockers.append("btc_trend_raw_forward_daily_roll_not_pass")

    if not blockers:
        evaluation = dict(
            evaluation_fn(
                repo_root=root,
                ledger_root=ledger_root,
                bundle_dir=bundle_dir,
                output=evaluation_report,
                markdown_output=evaluation_markdown_report,
                generated_at=generated,
            )
        )
        if str(evaluation.get("status", "")) not in {
            "raw_forward_observing",
            "raw_forward_complete_for_manual_review",
        }:
            blockers.extend([str(item) for item in evaluation.get("blockers", []) if item])
            blockers.append("btc_trend_raw_forward_daily_evaluation_blocked")

    payload = _payload(
        generated_at=generated,
        status="BLOCKED" if blockers else "PASS",
        capture=capture,
        readiness=readiness,
        roll=roll,
        evaluation=evaluation,
        blockers=_dedupe(blockers),
        root=root,
        output_path=output_path,
        execute_network=execute_network,
        ledger_root=ledger_root,
    )
    _write_json(output_path, payload)
    return payload


def _payload(
    *,
    generated_at: str,
    status: str,
    capture: Mapping[str, Any],
    readiness: Mapping[str, Any] | None,
    roll: Mapping[str, Any] | None,
    evaluation: Mapping[str, Any] | None,
    blockers: list[str],
    root: Path,
    output_path: Path,
    execute_network: bool,
    ledger_root: Path,
) -> dict[str, Any]:
    roll_cycle_status = str(roll.get("cycle_status", "")) if roll else ""
    evaluation_metrics = _mapping(evaluation.get("metrics")) if evaluation else {}
    forecast_target_order_chain = _mapping(roll.get("forecast_target_order_chain")) if roll else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": status,
        "asset": "btc",
        "symbol": "BTCUSDT",
        "pipeline": "btc_trend_raw_forward_observation_daily",
        "scheduler": {
            "intended_frequency": "daily",
            "recommended_local_time": SCHEDULER_LOCAL_TIME,
            "recommended_utc_time": SCHEDULER_UTC_TIME,
            "reason": "OKX 1Dutc candle closes at 00:00 UTC; run after the daily candle is expected to be available.",
        },
        "steps": {
            "data_refresh": _step_summary(capture, DEFAULT_CAPTURE_REPORT),
            "readiness": _step_summary(readiness, DEFAULT_READINESS_REPORT),
            "roll": _step_summary(roll, DEFAULT_ROLL_REPORT),
            "evaluation": _step_summary(evaluation, DEFAULT_EVALUATION_REPORT),
        },
        "data": {
            "network_called": bool(capture.get("network_called", False)),
            "execute_network_requested": bool(execute_network),
            "public_rest_only": capture.get("public_rest_only") is True,
            "bundle_id": str(capture.get("bundle_id", "")),
            "bundle_dir": str(capture.get("bundle_dir", "") or DEFAULT_BUNDLE_DIR).replace("\\", "/"),
            "daily_rows": int(capture.get("daily_rows", 0) or 0),
            "sample_start": str(capture.get("sample_start", "")),
            "sample_end": str(capture.get("sample_end", "")),
        },
        "forward_observation": {
            "ledger_root": _relpath(_resolve(root, ledger_root), root),
            "cycle_status": roll_cycle_status,
            "new_observation_written": roll_cycle_status == "COMPLETED",
            "already_processed": roll_cycle_status == "SKIPPED_ALREADY_COMPLETED",
            "evaluation_status": str(evaluation.get("status", "")) if evaluation else "",
            "observation_days": int(evaluation_metrics.get("observation_days", 0) or 0),
            "milestone_progress": evaluation_metrics.get("milestone_progress", {}),
        },
        "guardrails": {
            "simulated_only": True,
            "forward_observation_is_not_alpha_validation": True,
            "paper_candidate_ready_not_implied": True,
            "broker_calls_used": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "live_order_allowed": False,
            "real_order_submitted": False,
            "parameter_tuning_used": False,
            "volatility_position_branch_used": False,
            "multi_timeframe_confluence_used": False,
        },
        "forecast_target_order_chain": forecast_target_order_chain,
        "blockers": _dedupe(blockers),
        "output": _relpath(output_path, root),
    }


def _capture_blockers(capture: Mapping[str, Any]) -> list[str]:
    blockers = [str(item) for item in capture.get("blockers", []) if item]
    if str(capture.get("status", "")) != "verified":
        blockers.append("btc_trend_raw_forward_daily_data_refresh_not_verified")
    if capture.get("public_rest_only") is not True:
        blockers.append("btc_trend_raw_forward_daily_data_refresh_not_public_rest_only")
    if capture.get("api_key_used") is True:
        blockers.append("btc_trend_raw_forward_daily_data_refresh_api_key_used")
    if capture.get("private_endpoint_used") is True:
        blockers.append("btc_trend_raw_forward_daily_data_refresh_private_endpoint_used")
    if capture.get("order_endpoint_used") is True:
        blockers.append("btc_trend_raw_forward_daily_data_refresh_order_endpoint_used")
    return _dedupe(blockers)


def _step_summary(payload: Mapping[str, Any] | None, default_report: Path) -> dict[str, Any]:
    if not payload:
        return {"status": "NOT_RUN", "report": str(default_report).replace("\\", "/")}
    return {
        "status": str(payload.get("status", "")),
        "decision": str(payload.get("decision", "")),
        "cycle_status": str(payload.get("cycle_status", "")),
        "report": str(default_report).replace("\\", "/"),
        "blockers": [str(item) for item in payload.get("blockers", []) if item],
    }


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


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


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _dedupe(values: list[str]) -> list[str]:
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the BTC raw trend forward-observation daily pipeline.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--capture-report", default=str(DEFAULT_CAPTURE_REPORT))
    parser.add_argument("--readiness-report", default=str(DEFAULT_READINESS_REPORT))
    parser.add_argument("--roll-report", default=str(DEFAULT_ROLL_REPORT))
    parser.add_argument("--evaluation-report", default=str(DEFAULT_EVALUATION_REPORT))
    parser.add_argument("--evaluation-markdown-report", default=str(DEFAULT_EVALUATION_MARKDOWN_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--top-validation-report", default=str(DEFAULT_TOP_VALIDATION_REPORT))
    parser.add_argument("--raw-plan-report", default=str(DEFAULT_RAW_PLAN_REPORT))
    parser.add_argument("--volatility-freeze-report", default=str(DEFAULT_VOLATILITY_FREEZE_REPORT))
    parser.add_argument("--five-minute-freeze-report", default=str(DEFAULT_5M_FREEZE_REPORT))
    parser.add_argument("--history-days", type=int, default=DEFAULT_HISTORY_DAYS)
    parser.add_argument("--request-sleep-seconds", type=float, default=DEFAULT_REQUEST_SLEEP_SECONDS)
    parser.add_argument("--request-retry-count", type=int, default=DEFAULT_REQUEST_RETRY_COUNT)
    parser.add_argument("--request-retry-backoff-seconds", type=float, default=DEFAULT_REQUEST_RETRY_BACKOFF_SECONDS)
    parser.add_argument("--as-of", default="")
    parser.add_argument("--initial-capital", type=float, default=DEFAULT_INITIAL_CAPITAL)
    parser.add_argument("--fee-bps", type=float, default=DEFAULT_FEE_BPS)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = run_btc_trend_raw_forward_observation_daily(
        repo_root=Path(args.repo_root),
        execute_network=bool(args.execute_network),
        bundle_id=args.bundle_id,
        output_root=Path(args.output_root),
        bundle_dir=Path(args.bundle_dir),
        ledger_root=Path(args.ledger_root),
        capture_report=Path(args.capture_report),
        readiness_report=Path(args.readiness_report),
        roll_report=Path(args.roll_report),
        evaluation_report=Path(args.evaluation_report),
        evaluation_markdown_report=Path(args.evaluation_markdown_report),
        output=Path(args.output),
        top_validation_report=Path(args.top_validation_report),
        raw_plan_report=Path(args.raw_plan_report),
        volatility_freeze_report=Path(args.volatility_freeze_report),
        five_minute_freeze_report=Path(args.five_minute_freeze_report),
        history_days=args.history_days,
        request_sleep_seconds=args.request_sleep_seconds,
        request_retry_count=args.request_retry_count,
        request_retry_backoff_seconds=args.request_retry_backoff_seconds,
        as_of=args.as_of,
        initial_capital=args.initial_capital,
        fee_bps=args.fee_bps,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])
    raise SystemExit(0 if payload.get("status") in {"PASS", "DRY_RUN"} else 2)


if __name__ == "__main__":
    main()
