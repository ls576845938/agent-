#!/usr/bin/env python3
"""Check BTC raw trend forward-observation readiness.

This gate is operational only: PASS means the raw observation ledger may append
one simulated daily cycle. It does not mean the strategy has passed alpha
validation, paper promotion, or live readiness.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_btc_only_trend_v0_report import _load_daily_bars  # noqa: E402


SCHEMA_VERSION = "btc_trend_raw_forward_observation_readiness_v1"
DEFAULT_TOP_VALIDATION_REPORT = Path("artifacts/btc_trend_v0/latest/btc_trend_top_strategy_validation_report.json")
DEFAULT_RAW_PLAN_REPORT = Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_plan_report.json")
DEFAULT_VOLATILITY_FREEZE_REPORT = Path("artifacts/btc_trend_v0/latest/btc_trend_volatility_position_freeze_report.json")
DEFAULT_5M_FREEZE_REPORT = Path("artifacts/btc_paper_readiness/latest/btc_5m_hft_freeze_report.json")
DEFAULT_BUNDLE_DIR = Path("data/external/btc_spot/okx/bundles/btc_okx_spot_btcusdt_daily_5y_v1")
DEFAULT_LEDGER_ROOT = Path("data/forward_observation/btc_trend_raw_v1")
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_readiness_report.json")
FORBIDDEN_LEDGER_ROOTS = (
    Path("data/paper_ledger/btc_5m"),
    Path("data/paper_ledger/btc_trend_v0"),
)
EXPECTED_PRIMARY_FAMILY = "t01_twelve_month_momentum"
EXPECTED_PRIMARY_CANDIDATE = "t01_momentum_binary_8e09e94c36"
EXPECTED_STRATEGY_ID = "btc_trend_raw_t01_twelve_month_momentum"
MIN_DAILY_ROWS = 367


def check_btc_trend_raw_forward_observation_readiness(
    *,
    repo_root: Path | None = None,
    top_validation_report: Path = DEFAULT_TOP_VALIDATION_REPORT,
    raw_plan_report: Path = DEFAULT_RAW_PLAN_REPORT,
    volatility_freeze_report: Path = DEFAULT_VOLATILITY_FREEZE_REPORT,
    five_minute_freeze_report: Path = DEFAULT_5M_FREEZE_REPORT,
    bundle_dir: Path = DEFAULT_BUNDLE_DIR,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    output: Path = DEFAULT_OUTPUT,
    expected_primary_family: str = EXPECTED_PRIMARY_FAMILY,
    expected_primary_candidate: str = EXPECTED_PRIMARY_CANDIDATE,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    top_path = _resolve(root, top_validation_report)
    plan_path = _resolve(root, raw_plan_report)
    vol_path = _resolve(root, volatility_freeze_report)
    freeze_path = _resolve(root, five_minute_freeze_report)
    bundle_path = _resolve(root, bundle_dir)
    ledger = _resolve(root, ledger_root)
    output_path = _resolve(root, output)

    top = _read_json(top_path)
    plan = _read_json(plan_path)
    vol_freeze = _read_json(vol_path)
    five_minute_freeze = _read_json(freeze_path)
    blockers: list[str] = []

    primary = _mapping(plan.get("primary_candidate"))
    primary_family = str(primary.get("family_id", "") or "")
    primary_candidate = str(primary.get("candidate_id", "") or "")
    if not plan:
        blockers.append("btc_trend_raw_forward_plan_missing")
    if str(plan.get("status", "")) != "raw_trend_forward_observation_plan_ready":
        blockers.append("btc_trend_raw_forward_plan_not_ready")
    if primary_family != expected_primary_family:
        blockers.append("btc_trend_raw_forward_primary_family_mismatch")
    if primary_candidate != expected_primary_candidate:
        blockers.append("btc_trend_raw_forward_primary_candidate_mismatch")
    forward = _mapping(plan.get("forward_observation"))
    if forward.get("volatility_position_branch_allowed") is not False:
        blockers.append("btc_trend_raw_forward_volatility_branch_not_excluded")
    if forward.get("paper_runner_start_allowed_by_this_report") is not False:
        blockers.append("btc_trend_raw_forward_plan_misstates_paper_start")
    if _mapping(plan.get("guardrails")).get("volatility_position_branch_frozen") is not True:
        blockers.append("btc_trend_raw_forward_plan_volatility_branch_not_frozen")

    if not top:
        blockers.append("btc_trend_top_strategy_validation_report_missing")
    if str(top.get("status", "")) != "top_strategy_validation_research_only":
        blockers.append("btc_trend_top_strategy_validation_report_unexpected_status")
    top_candidate = _find_candidate(top, expected_primary_family)
    if not top_candidate:
        blockers.append("btc_trend_top_strategy_primary_candidate_missing")
    else:
        if str(top_candidate.get("validation_status", "")) != "research_validation_passed":
            blockers.append("btc_trend_top_strategy_primary_candidate_not_passed")
        if str(top_candidate.get("candidate_id", "")) != expected_primary_candidate:
            blockers.append("btc_trend_top_strategy_primary_candidate_id_mismatch")

    if not vol_freeze:
        blockers.append("btc_trend_volatility_position_freeze_report_missing")
    if str(vol_freeze.get("status", "")) != "frozen_deferred_not_primary":
        blockers.append("btc_trend_volatility_position_not_frozen_deferred")
    vol_guardrails = _mapping(vol_freeze.get("guardrails"))
    if vol_guardrails.get("parameter_tuning_allowed") is not False:
        blockers.append("btc_trend_volatility_position_parameter_tuning_not_frozen")
    if vol_guardrails.get("paper_observation_allowed") is not False:
        blockers.append("btc_trend_volatility_position_paper_observation_not_frozen")

    if not five_minute_freeze:
        blockers.append("btc_5m_hft_freeze_report_missing")
    if str(five_minute_freeze.get("status", "")) != "frozen_rejected_as_high_frequency":
        blockers.append("btc_5m_hft_not_frozen_rejected_as_high_frequency")
    five_minute_guardrails = _mapping(five_minute_freeze.get("guardrails"))
    if five_minute_guardrails.get("parameter_tuning_allowed") is not False:
        blockers.append("btc_5m_hft_freeze_allows_parameter_tuning")

    true_flags = _true_control_flags(
        {
            "raw_plan": plan,
            "top_strategy_validation": top,
            "volatility_freeze": vol_freeze,
            "five_minute_freeze": five_minute_freeze,
        }
    )
    for item in true_flags:
        blockers.append(f"btc_trend_raw_forward_forbidden_flag_true:{item}")

    data_summary = _daily_data_summary(bundle_path)
    if not data_summary["loaded"]:
        blockers.append("btc_trend_raw_forward_daily_bundle_unreadable")
    elif int(data_summary["row_count"]) < MIN_DAILY_ROWS:
        blockers.append("btc_trend_raw_forward_daily_history_insufficient")

    ledger_forbidden = any(_same_path(ledger, _resolve(root, forbidden)) for forbidden in FORBIDDEN_LEDGER_ROOTS)
    if ledger_forbidden:
        blockers.append("btc_trend_raw_forward_ledger_root_forbidden")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "BLOCKED" if blockers else "PASS",
        "readiness_type": "raw_forward_observation_operational_readiness_only",
        "asset": "btc",
        "symbol": "BTCUSDT",
        "strategy_id": EXPECTED_STRATEGY_ID,
        "primary_candidate": {
            "family_id": primary_family,
            "candidate_id": primary_candidate,
            "expected_family_id": expected_primary_family,
            "expected_candidate_id": expected_primary_candidate,
        },
        "reports": {
            "top_validation_report": _relpath(top_path, root),
            "raw_plan_report": _relpath(plan_path, root),
            "volatility_freeze_report": _relpath(vol_path, root),
            "five_minute_freeze_report": _relpath(freeze_path, root),
        },
        "bundle": {
            "path": _relpath(bundle_path, root),
            **data_summary,
        },
        "ledger_root": _relpath(ledger, root),
        "checks": {
            "raw_plan_ready": str(plan.get("status", "")) == "raw_trend_forward_observation_plan_ready",
            "primary_family_matches": primary_family == expected_primary_family,
            "primary_candidate_matches": primary_candidate == expected_primary_candidate,
            "top_validation_research_only": str(top.get("status", "")) == "top_strategy_validation_research_only",
            "top_primary_candidate_passed": str(top_candidate.get("validation_status", "")) == "research_validation_passed" if top_candidate else False,
            "volatility_position_frozen": str(vol_freeze.get("status", "")) == "frozen_deferred_not_primary",
            "five_minute_hft_frozen": str(five_minute_freeze.get("status", "")) == "frozen_rejected_as_high_frequency",
            "forbidden_control_flags_false": not true_flags,
            "daily_history_sufficient": data_summary["loaded"] and int(data_summary["row_count"]) >= MIN_DAILY_ROWS,
            "ledger_root_isolated": not ledger_forbidden,
        },
        "guardrails": {
            "raw_forward_observation_is_not_strategy_validation": True,
            "paper_candidate_ready_not_required": True,
            "paper_runner_start_allowed_by_this_gate": False,
            "volatility_position_branch_frozen": True,
            "t02_long_ma_trend_excluded": True,
            "multi_timeframe_confluence_allowed": False,
            "parameter_tuning_allowed": False,
            "broker_calls_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "live_order_allowed": False,
            "real_order_submitted": False,
            "do_not_reuse_5m_hft_ledger": True,
            "do_not_reuse_old_trend_paper_ledger": True,
        },
        "blockers": _dedupe(blockers),
    }
    _write_json(output_path, payload)
    return payload


def _find_candidate(report: Mapping[str, Any], family_id: str) -> dict[str, Any]:
    for item in report.get("candidate_summaries", []):
        if isinstance(item, Mapping) and str(item.get("family_id", "")) == family_id:
            return dict(item)
    return {}


def _daily_data_summary(bundle_dir: Path) -> dict[str, Any]:
    try:
        daily = _load_daily_bars(bundle_dir)
    except Exception as exc:  # noqa: BLE001 - readiness must report the exact blocker.
        return {"loaded": False, "row_count": 0, "start": "", "end": "", "error": str(exc)}
    if daily.empty:
        return {"loaded": True, "row_count": 0, "start": "", "end": "", "error": ""}
    return {
        "loaded": True,
        "row_count": int(len(daily)),
        "start": _timestamp_text(daily.index.min()),
        "end": _timestamp_text(daily.index.max()),
        "error": "",
    }


def _true_control_flags(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    forbidden_keys = {
        "broker_calls_allowed",
        "broker_calls_used",
        "private_endpoint_used",
        "order_endpoint_used",
        "live_order_allowed",
        "live_order_submitted",
        "real_order_submitted",
    }
    found: list[str] = []
    for name, report in reports.items():
        for scope, payload in (("top_level", report), ("guardrails", _mapping(report.get("guardrails")))):
            for key in forbidden_keys:
                if payload.get(key) is True:
                    found.append(f"{name}.{scope}.{key}")
    return _dedupe(found)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


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


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _timestamp_text(value: object) -> str:
    import pandas as pd

    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check BTC raw trend forward-observation readiness.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--top-validation-report", default=str(DEFAULT_TOP_VALIDATION_REPORT))
    parser.add_argument("--raw-plan-report", default=str(DEFAULT_RAW_PLAN_REPORT))
    parser.add_argument("--volatility-freeze-report", default=str(DEFAULT_VOLATILITY_FREEZE_REPORT))
    parser.add_argument("--five-minute-freeze-report", default=str(DEFAULT_5M_FREEZE_REPORT))
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--expected-primary-family", default=EXPECTED_PRIMARY_FAMILY)
    parser.add_argument("--expected-primary-candidate", default=EXPECTED_PRIMARY_CANDIDATE)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = check_btc_trend_raw_forward_observation_readiness(
        repo_root=Path(args.repo_root),
        top_validation_report=Path(args.top_validation_report),
        raw_plan_report=Path(args.raw_plan_report),
        volatility_freeze_report=Path(args.volatility_freeze_report),
        five_minute_freeze_report=Path(args.five_minute_freeze_report),
        bundle_dir=Path(args.bundle_dir),
        ledger_root=Path(args.ledger_root),
        output=Path(args.output),
        expected_primary_family=args.expected_primary_family,
        expected_primary_candidate=args.expected_primary_candidate,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])
    raise SystemExit(0 if payload.get("status") == "PASS" else 2)


if __name__ == "__main__":
    main()
