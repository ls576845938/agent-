#!/usr/bin/env python3
"""Run one US ETF rotation forward-observation cycle.

The runner is target-position only. It writes simulated observation ledger files
and never calls a broker, private endpoint, or order endpoint.
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

from quant_us.execution.us_etf_rotation_execution import (  # noqa: E402
    build_simulated_fills,
    calculate_rebalance_delta,
    reconcile_simulated_snapshot,
    target_from_validation_report,
)


SCHEMA_VERSION = "us_etf_rotation_forward_observation_roll_v1"
STATE_SCHEMA_VERSION = "us_etf_rotation_forward_observation_state_v1"
DEFAULT_VALIDATION_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_top1_higher_vol_20pct_15x_validation_report.json")
DEFAULT_DATA_FRESHNESS_REPORT = Path("artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json")
DEFAULT_KLINE_QUALITY_REPORT = Path("artifacts/us_equity_data_status/latest/us_equity_etf_kline_quality_daily_report.json")
DEFAULT_FRED_PREFLIGHT_REPORT = Path("artifacts/us_equity_data_status/latest/us_equity_fred_macro_preflight_report.json")
DEFAULT_LEDGER_ROOT = Path("data/forward_observation/us_etf_rotation_v1")
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json")
STRATEGY_ID = "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x"
BASE_STRATEGY_ID = "top1_higher_vol__vol_target_20pct_cap1.5x"
EXPECTED_VARIANT = "min_adv_10m_to_shv"
ACCOUNT_EQUITY = 10_000.0
DEFAULT_SLIPPAGE_BPS = 10.0
MIN_OBSERVATION_DAYS = 30


def run_us_etf_rotation_forward_observation(
    *,
    repo_root: Path | None = None,
    validation_report: Path = DEFAULT_VALIDATION_REPORT,
    data_freshness_report: Path = DEFAULT_DATA_FRESHNESS_REPORT,
    kline_quality_report: Path = DEFAULT_KLINE_QUALITY_REPORT,
    fred_preflight_report: Path = DEFAULT_FRED_PREFLIGHT_REPORT,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    output: Path = DEFAULT_OUTPUT,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    report_path = _resolve(root, validation_report)
    data_freshness_path = _resolve(root, data_freshness_report)
    kline_quality_path = _resolve(root, kline_quality_report)
    fred_preflight_path = _resolve(root, fred_preflight_report)
    ledger = _resolve(root, ledger_root)
    output_path = _resolve(root, output)
    validation = _read_json(report_path)
    data_freshness = _read_json(data_freshness_path)
    kline_quality = _read_json(kline_quality_path)
    fred_preflight = _read_json(fred_preflight_path)
    readiness = _readiness(
        validation,
        data_freshness=data_freshness,
        kline_quality=kline_quality,
        fred_preflight=fred_preflight,
        report_path=report_path,
        data_freshness_path=data_freshness_path,
        kline_quality_path=kline_quality_path,
        fred_preflight_path=fred_preflight_path,
        ledger_root=ledger_root,
    )
    if readiness["status"] != "PASS":
        payload = _blocked_payload(generated, ledger, output_path, readiness)
        _write_json(output_path, payload)
        return payload

    target = target_from_validation_report(validation)
    state_path = ledger / "validation_state.json"
    state = _read_json(state_path)
    timestamp = str(target["date"])
    if state.get("last_processed_timestamp") == timestamp:
        latest_snapshot = _latest_jsonl(ledger / "portfolio_snapshots.jsonl")
        rebalance = {
            "deltas": {},
            "turnover": 0.0,
            "estimated_trade_notional": 0.0,
            "slippage_bps": float(slippage_bps),
            "estimated_slippage": 0.0,
            "estimated_financing_daily": 0.0,
            "simulated_only": True,
        }
        reconciliation = {
            "status": "clean" if latest_snapshot.get("reconciliation_status") == "clean" else "unknown",
            "passed": latest_snapshot.get("reconciliation_status") == "clean",
        }
        operational_checks = _operational_checks(
            generated_at=generated,
            target=target,
            rebalance=rebalance,
            reconciliation=reconciliation,
            prior_equity=_float_or(latest_snapshot.get("prior_equity"), ACCOUNT_EQUITY),
            validation=validation,
            fills=[],
            reason="already_processed_same_timestamp",
        )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated,
            "status": "PASS" if operational_checks["status"] == "PASS" else "BLOCKED",
            "cycle_status": "SKIPPED_ALREADY_COMPLETED"
            if operational_checks["status"] == "PASS"
            else "OPERATIONAL_CHECK_FAILED",
            "strategy_id": STRATEGY_ID,
            "base_strategy_id": BASE_STRATEGY_ID,
            "candidate_variant": EXPECTED_VARIANT,
            "ledger_root": _relpath(ledger, root),
            "account_equity": _float_or(state.get("current_equity"), ACCOUNT_EQUITY),
            "target_position": target,
            "current_position": state.get("current_position", {}),
            "rebalance": rebalance,
            "portfolio_snapshot": latest_snapshot,
            "readiness": readiness,
            "observation_scope": _observation_scope(),
            "alpha_validation": _alpha_validation_status(),
            "operational_checks": operational_checks,
            "guardrails": _guardrails(),
            "blockers": list(operational_checks.get("blockers", [])),
        }
        _write_json(output_path, payload)
        return payload

    ledger.mkdir(parents=True, exist_ok=True)
    current = _mapping(state.get("current_position"))
    prior_equity = _float_or(state.get("current_equity"), ACCOUNT_EQUITY)
    rebalance = calculate_rebalance_delta(current, target, prior_equity, slippage_bps, validation)
    fills = build_simulated_fills(
        timestamp,
        target,
        prior_equity,
        rebalance,
        generated,
        strategy_id=STRATEGY_ID,
        candidate_variant=EXPECTED_VARIANT,
    )
    final_equity = prior_equity - rebalance["estimated_slippage"] - rebalance["estimated_financing_daily"]
    snapshot = {
        "timestamp": timestamp,
        "strategy_id": STRATEGY_ID,
        "candidate_variant": EXPECTED_VARIANT,
        "prior_equity": round(prior_equity, 6),
        "equity": round(final_equity, 6),
        "gross_exposure": round(float(target["gross_exposure"]), 10),
        "net_exposure": round(float(target["net_exposure"]), 10),
        "target_count": int(target["target_count"]),
        "turnover": round(rebalance["turnover"], 10),
        "estimated_trade_notional": round(rebalance["estimated_trade_notional"], 6),
        "estimated_slippage": round(rebalance["estimated_slippage"], 6),
        "estimated_financing_daily": round(rebalance["estimated_financing_daily"], 6),
        "reconciliation_status": "clean",
        "generated_at": generated,
    }
    reason = "monthly_rotation_target_from_research_validation_report"
    target_row = {
        "timestamp": timestamp,
        "strategy_id": STRATEGY_ID,
        "base_strategy_id": BASE_STRATEGY_ID,
        "candidate_variant": EXPECTED_VARIANT,
        "account_equity": ACCOUNT_EQUITY,
        "target_position": target,
        "current_position": current,
        "rebalance": rebalance,
        "reason": reason,
        "simulated_only": True,
        "generated_at": generated,
    }
    reconciliation = reconcile_simulated_snapshot(snapshot=snapshot, prior_equity=prior_equity, rebalance=rebalance)
    operational_checks = _operational_checks(
        generated_at=generated,
        target=target,
        rebalance=rebalance,
        reconciliation=reconciliation,
        prior_equity=prior_equity,
        validation=validation,
        fills=fills,
        reason=reason,
    )
    if operational_checks["status"] != "PASS":
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated,
            "status": "BLOCKED",
            "cycle_status": "OPERATIONAL_CHECK_FAILED",
            "strategy_id": STRATEGY_ID,
            "base_strategy_id": BASE_STRATEGY_ID,
            "candidate_variant": EXPECTED_VARIANT,
            "ledger_root": _relpath(ledger, root),
            "account_equity": ACCOUNT_EQUITY,
            "target_position": target,
            "current_position": current,
            "rebalance": rebalance,
            "fills": fills,
            "portfolio_snapshot": snapshot,
            "readiness": readiness,
            "reconciliation": reconciliation,
            "observation_scope": _observation_scope(),
            "alpha_validation": _alpha_validation_status(),
            "operational_checks": operational_checks,
            "guardrails": _guardrails(),
            "blockers": list(operational_checks.get("blockers", [])),
        }
        _write_json(output_path, payload)
        return payload

    _append_jsonl(ledger / "target_positions.jsonl", target_row)
    for fill in fills:
        _append_jsonl(ledger / "fills.jsonl", fill)
    if not fills:
        (ledger / "fills.jsonl").touch(exist_ok=True)
    _append_jsonl(ledger / "portfolio_snapshots.jsonl", snapshot)
    new_state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "updated_at": generated,
        "strategy_id": STRATEGY_ID,
        "candidate_variant": EXPECTED_VARIANT,
        "account_equity": ACCOUNT_EQUITY,
        "current_equity": round(final_equity, 6),
        "current_position": target,
        "days_completed": int(state.get("days_completed", 0) or 0) + 1,
        "target_position_count": int(state.get("target_position_count", 0) or 0) + 1,
        "fill_count": int(state.get("fill_count", 0) or 0) + len(fills),
        "last_processed_timestamp": timestamp,
        "ledger_root": _relpath(ledger, root),
        "forward_observation_min_days": MIN_OBSERVATION_DAYS,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "live_order_allowed": False,
    }
    _write_json(state_path, new_state)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "PASS",
        "cycle_status": "COMPLETED",
        "strategy_id": STRATEGY_ID,
        "base_strategy_id": BASE_STRATEGY_ID,
        "candidate_variant": EXPECTED_VARIANT,
        "ledger_root": _relpath(ledger, root),
        "account_equity": ACCOUNT_EQUITY,
        "target_position": target,
        "current_position": current,
        "rebalance": rebalance,
        "fills": fills,
        "portfolio_snapshot": snapshot,
        "validation_state_path": _relpath(state_path, root),
        "readiness": readiness,
        "reconciliation": reconciliation,
        "observation_scope": _observation_scope(),
        "alpha_validation": _alpha_validation_status(),
        "operational_checks": operational_checks,
        "guardrails": _guardrails(),
        "blockers": [],
    }
    _write_json(output_path, payload)
    return payload


def _readiness(
    validation: Mapping[str, Any],
    *,
    data_freshness: Mapping[str, Any],
    kline_quality: Mapping[str, Any],
    fred_preflight: Mapping[str, Any],
    report_path: Path,
    data_freshness_path: Path,
    kline_quality_path: Path,
    fred_preflight_path: Path,
    ledger_root: Path,
) -> dict[str, Any]:
    blockers: list[str] = []
    if not validation:
        blockers.append("us_etf_validation_report_missing")
    if str(validation.get("schema_version", "")) != "us_etf_top1_higher_vol_20pct_15x_validation_report_v1":
        blockers.append("us_etf_validation_report_schema_mismatch")
    if validation.get("live_ready") is not False or validation.get("paper_ready") is not False:
        blockers.append("us_etf_validation_report_unexpected_promotion_flag")
    if _mapping(validation.get("decision")).get("live_ready") is not False:
        blockers.append("us_etf_decision_live_ready_not_false")
    if _mapping(validation.get("small_account_10k_profile")).get("account_equity") != ACCOUNT_EQUITY:
        blockers.append("us_etf_10k_profile_missing")
    if _mapping(validation.get("small_account_10k_profile")).get("constrained_strategy_capacity_pass") is not True:
        blockers.append("us_etf_10k_constrained_capacity_not_passed")
    if _mapping(validation.get("tradability_constraints")).get("selected_constrained_variant") != EXPECTED_VARIANT:
        blockers.append("us_etf_selected_variant_mismatch")
    target_date = str(_mapping(_mapping(validation.get("small_account_10k_profile")).get("constrained_latest_target")).get("date", ""))
    data_gate = _data_gate_readiness(
        data_freshness=data_freshness,
        kline_quality=kline_quality,
        fred_preflight=fred_preflight,
        target_date=target_date,
    )
    blockers.extend(_list_of_str(data_gate.get("blockers")))
    if "paper_ledger" in ledger_root.as_posix() or "live" in ledger_root.as_posix():
        blockers.append("us_etf_forward_ledger_root_forbidden")
    if not report_path.exists():
        blockers.append("us_etf_validation_report_path_missing")
    if not data_freshness_path.exists():
        blockers.append("us_etf_data_freshness_report_path_missing")
    if not kline_quality_path.exists():
        blockers.append("us_etf_kline_quality_report_path_missing")
    if not fred_preflight_path.exists():
        blockers.append("us_etf_fred_preflight_report_path_missing")
    return {
        "status": "BLOCKED" if blockers else "PASS",
        "readiness_type": "us_etf_forward_observation_operational_only",
        "readiness_is_not_alpha_validation": True,
        "paper_or_live_unlock_allowed": False,
        "validation_report": report_path.as_posix(),
        "data_freshness_report": data_freshness_path.as_posix(),
        "kline_quality_report": kline_quality_path.as_posix(),
        "fred_preflight_report": fred_preflight_path.as_posix(),
        "ledger_root": ledger_root.as_posix(),
        "data_gate": data_gate,
        "blockers": _dedupe(blockers),
    }


def _data_gate_readiness(
    *,
    data_freshness: Mapping[str, Any],
    kline_quality: Mapping[str, Any],
    fred_preflight: Mapping[str, Any],
    target_date: str,
) -> dict[str, Any]:
    blockers: list[str] = []
    if not data_freshness:
        blockers.append("us_etf_forward_data_freshness_report_missing")
    elif str(data_freshness.get("status", "")) != "pass":
        blockers.extend(_list_of_str(data_freshness.get("blockers")) or ["us_etf_forward_data_freshness_not_pass"])
    if not kline_quality:
        blockers.append("us_etf_forward_kline_quality_report_missing")
    elif str(kline_quality.get("status", "")) == "blocked":
        blockers.extend(_list_of_str(kline_quality.get("blockers")) or ["us_etf_forward_kline_quality_blocked"])
    elif str(kline_quality.get("status", "")) not in {"pass", "warn"}:
        blockers.append("us_etf_forward_kline_quality_status_invalid")
    if not fred_preflight:
        blockers.append("us_etf_forward_fred_preflight_report_missing")
    elif str(fred_preflight.get("status", "")) == "fred_macro_preflight_blocked":
        blockers.extend(_list_of_str(fred_preflight.get("blockers")) or ["us_etf_forward_fred_preflight_blocked"])
    elif str(fred_preflight.get("status", "")) not in {"fred_macro_preflight_pass", "fred_macro_preflight_warn"}:
        blockers.append("us_etf_forward_fred_preflight_status_invalid")
    latest_common = str(_nested(kline_quality, "summary.latest_common_date", ""))
    if target_date and latest_common and latest_common < target_date:
        blockers.append("us_etf_forward_kline_quality_older_than_target")
    if _unsafe_true({"data_freshness": data_freshness, "kline_quality": kline_quality, "fred_preflight": fred_preflight}):
        blockers.append("us_etf_forward_data_gate_unsafe_flag_detected")
    return {
        "status": "BLOCKED" if blockers else "PASS",
        "target_date": target_date,
        "data_freshness_status": data_freshness.get("status"),
        "kline_quality_status": kline_quality.get("status"),
        "kline_quality_latest_common_date": latest_common,
        "kline_quality_warnings": _list_of_str(kline_quality.get("warnings")),
        "fred_preflight_status": fred_preflight.get("status"),
        "fred_preflight_warnings": _list_of_str(fred_preflight.get("warnings")),
        "blockers": _dedupe(blockers),
    }


def _observation_scope() -> dict[str, Any]:
    return {
        "scope": "operational_quality_only",
        "not_alpha_validation": True,
        "cannot_prove_long_term_positive_expectancy": True,
        "cannot_auto_unlock_paper_or_live": True,
        "allowed_claims": [
            "target_position_generation_stability",
            "data_freshness",
            "ledger_recalculation",
            "rebalance_rule_no_future_timestamp",
            "cost_and_financing_estimate_consistency",
            "target_change_explainability",
        ],
        "forbidden_claims": [
            "alpha_is_validated",
            "long_term_positive_expectancy_is_proven",
            "strategy_is_live_ready",
            "paper_or_live_is_auto_unlocked",
        ],
    }


def _alpha_validation_status() -> dict[str, Any]:
    return {
        "status": "not_evaluated",
        "alpha_validated": False,
        "long_term_positive_expectancy_proven": False,
        "strategy_validation_gate_required": True,
        "unlock_effect": "none",
    }


def _operational_checks(
    *,
    generated_at: str,
    target: Mapping[str, Any],
    rebalance: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    prior_equity: float,
    validation: Mapping[str, Any],
    fills: list[Mapping[str, Any]],
    reason: str,
) -> dict[str, Any]:
    target_date = _date_from_iso(str(target.get("date", "")))
    generated_date = _date_from_iso(generated_at)
    staleness_days = None
    if target_date is not None and generated_date is not None:
        staleness_days = (generated_date - target_date).days
    target_count = int(target.get("target_count", 0) or 0)
    weights = _mapping(target.get("weights"))
    deltas = _mapping(rebalance.get("deltas"))
    turnover = _float_or(rebalance.get("turnover"), 0.0)
    expected_slippage = _float_or(rebalance.get("estimated_trade_notional"), 0.0) * _float_or(
        rebalance.get("slippage_bps"),
        DEFAULT_SLIPPAGE_BPS,
    ) / 10_000.0
    slippage_ok = abs(expected_slippage - _float_or(rebalance.get("estimated_slippage"), 0.0)) <= 0.01
    financing_model = _mapping(validation.get("financing_model"))
    avg_rate = _float_or(financing_model.get("average_annual_rate"), 0.0)
    expected_financing = prior_equity * max(0.0, _float_or(target.get("gross_exposure"), 0.0) - 1.0) * avg_rate / 252.0
    financing_ok = abs(expected_financing - _float_or(rebalance.get("estimated_financing_daily"), 0.0)) <= 0.01
    checks = {
        "target_position_generation": {
            "passed": target_count > 0 and bool(weights),
            "target_count": target_count,
            "target_date": str(target.get("date", "")),
        },
        "data_freshness": {
            "passed": staleness_days is not None and 0 <= staleness_days <= 5,
            "target_date": str(target.get("date", "")),
            "generated_at": generated_at,
            "staleness_days": staleness_days,
            "max_allowed_staleness_days": 5,
        },
        "ledger_recalculation": {
            "passed": bool(reconciliation.get("passed", False)),
            "reconciliation_status": reconciliation.get("status"),
        },
        "rebalance_rule_no_future_timestamp": {
            "passed": staleness_days is not None and staleness_days >= 0,
            "rule": "runner consumes a precomputed target dated on or before the run timestamp; it does not recalculate alpha using future data",
        },
        "cost_and_financing_estimate_consistency": {
            "passed": slippage_ok and financing_ok,
            "expected_slippage": round(expected_slippage, 6),
            "reported_slippage": round(_float_or(rebalance.get("estimated_slippage"), 0.0), 6),
            "expected_financing_daily": round(expected_financing, 6),
            "reported_financing_daily": round(_float_or(rebalance.get("estimated_financing_daily"), 0.0), 6),
        },
        "target_change_explainability": {
            "passed": bool(reason) and _deltas_are_numeric(deltas) and (turnover <= 1e-12 or bool(fills)),
            "reason": reason,
            "turnover": turnover,
            "fill_count": len(fills),
        },
    }
    blockers = []
    for check_name, check in checks.items():
        if not bool(check.get("passed", False)):
            blockers.append(f"us_etf_forward_observation_{check_name}_failed")
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "scope": "operational_quality_only",
        "checks": checks,
        "blockers": blockers,
        "not_alpha_validation": True,
        "long_term_positive_expectancy_proven": False,
        "paper_or_live_unlock_allowed": False,
    }


def _guardrails() -> dict[str, Any]:
    return {
        "simulated_only": True,
        "forward_observation_is_not_strategy_validation": True,
        "forward_observation_is_not_alpha_validation": True,
        "long_term_positive_expectancy_proven": False,
        "paper_candidate_ready_not_implied": True,
        "paper_or_live_unlock_allowed": False,
        "paper_runner_started": False,
        "broker_calls_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "live_order_allowed": False,
        "real_order_submitted": False,
        "initial_live_leverage_recommended": False,
        "one_x_or_low_leverage_first_if_live": True,
        "forward_observation_min_days": MIN_OBSERVATION_DAYS,
    }


def _blocked_payload(generated_at: str, ledger: Path, output_path: Path, readiness: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "BLOCKED",
        "cycle_status": "NOT_RUN",
        "strategy_id": STRATEGY_ID,
        "candidate_variant": EXPECTED_VARIANT,
        "ledger_root": ledger.as_posix(),
        "readiness": dict(readiness),
        "observation_scope": _observation_scope(),
        "alpha_validation": _alpha_validation_status(),
        "operational_checks": {
            "status": "NOT_RUN",
            "scope": "operational_quality_only",
            "blockers": ["us_etf_forward_observation_readiness_blocked"],
            "not_alpha_validation": True,
            "long_term_positive_expectancy_proven": False,
            "paper_or_live_unlock_allowed": False,
        },
        "guardrails": _guardrails(),
        "blockers": list(readiness.get("blockers", [])),
        "output": output_path.as_posix(),
    }


def _append_jsonl(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(row), sort_keys=True, ensure_ascii=False, default=str))
        handle.write("\n")


def _latest_jsonl(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    latest = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            latest = line
    if not latest:
        return {}
    payload = json.loads(latest)
    return dict(payload) if isinstance(payload, Mapping) else {}


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


def _list_of_str(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _nested(payload: Mapping[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = payload
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _unsafe_true(payloads: Mapping[str, Mapping[str, Any]]) -> list[str]:
    unsafe = []
    unsafe_keys = {
        "live_order_allowed",
        "paper_simulation_allowed",
        "paper_or_live_unlock_allowed",
        "private_endpoint_used",
        "private_endpoint_allowed",
        "order_endpoint_used",
        "order_endpoint_allowed",
        "real_order_submitted",
        "token_written_to_artifacts",
    }
    for root_name, payload in payloads.items():
        for path, value in _walk(payload):
            if path.split(".")[-1] in unsafe_keys and value is True:
                unsafe.append(f"{root_name}.{path}=true")
    return unsafe


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


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _float_or(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _date_from_iso(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.fromisoformat(value.split("T", maxsplit=1)[0]).date()
        except ValueError:
            return None


def _deltas_are_numeric(deltas: Mapping[str, Any]) -> bool:
    try:
        for value in deltas.values():
            float(value)
    except (TypeError, ValueError):
        return False
    return True


def _dedupe(values: list[str]) -> list[str]:
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one US ETF forward-observation cycle.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--validation-report", default=str(DEFAULT_VALIDATION_REPORT))
    parser.add_argument("--data-freshness-report", default=str(DEFAULT_DATA_FRESHNESS_REPORT))
    parser.add_argument("--kline-quality-report", default=str(DEFAULT_KLINE_QUALITY_REPORT))
    parser.add_argument("--fred-preflight-report", default=str(DEFAULT_FRED_PREFLIGHT_REPORT))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--slippage-bps", type=float, default=DEFAULT_SLIPPAGE_BPS)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = run_us_etf_rotation_forward_observation(
        repo_root=Path(args.repo_root),
        validation_report=Path(args.validation_report),
        data_freshness_report=Path(args.data_freshness_report),
        kline_quality_report=Path(args.kline_quality_report),
        fred_preflight_report=Path(args.fred_preflight_report),
        ledger_root=Path(args.ledger_root),
        output=Path(args.output),
        slippage_bps=float(args.slippage_bps),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])
    raise SystemExit(0 if payload.get("status") == "PASS" else 2)


if __name__ == "__main__":
    main()
