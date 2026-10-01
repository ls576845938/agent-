#!/usr/bin/env python3
"""Build BTC live-readiness and risk-constitution report.

This is a fail-closed governance artifact. It records the rules required before
any live pilot can be discussed and explains why the current BTC system remains
blocked for live trading.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "btc_live_readiness_risk_constitution_v1"
DEFAULT_OUTPUT = Path("artifacts/btc_live_readiness/latest/btc_live_readiness_risk_constitution_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC 实盘前风控宪法.md")
DEFAULT_FORWARD_EVALUATION = Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_evaluation_report.json")
DEFAULT_DAILY_RUN = Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_daily_run_report.json")
DEFAULT_STRATEGY_GATE = Path("artifacts/btc_trend_v0/latest/btc_trend_v0_strategy_validation_gate_report.json")
DEFAULT_FOUR_HOUR_GATE = Path("artifacts/btc_intraday_trend_v1/latest/btc_4h_atr_channel_validation_gate_report.json")
DEFAULT_INTRADAY_REPORT = Path("artifacts/btc_intraday_trend_v1/latest/btc_intraday_trend_v1_report.json")
DEFAULT_5M_FREEZE = Path("artifacts/btc_paper_readiness/latest/btc_5m_hft_freeze_report.json")
DEFAULT_FORWARD_STATE = Path("data/forward_observation/btc_trend_raw_v1/validation_state.json")
DEFAULT_PAPER_OMS_SESSION_CONTRACT = Path("artifacts/btc_completion_evidence/latest/paper_oms_session_contract.json")
DEFAULT_INCIDENT_REPLAY_DRILL_CONTRACT = Path(
    "artifacts/btc_completion_evidence/latest/incident_replay_drill_contract.json"
)
DEFAULT_PAPER_VALIDATION_REPLAY = Path("artifacts/btc_paper_validation/latest/btc_paper_validation_replay_report.json")


def build_btc_live_readiness_risk_constitution(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    forward_evaluation: Path = DEFAULT_FORWARD_EVALUATION,
    daily_run: Path = DEFAULT_DAILY_RUN,
    strategy_gate: Path = DEFAULT_STRATEGY_GATE,
    four_hour_gate: Path = DEFAULT_FOUR_HOUR_GATE,
    intraday_report: Path = DEFAULT_INTRADAY_REPORT,
    five_minute_freeze: Path = DEFAULT_5M_FREEZE,
    forward_state: Path = DEFAULT_FORWARD_STATE,
    paper_oms_session_contract: Path = DEFAULT_PAPER_OMS_SESSION_CONTRACT,
    incident_replay_drill_contract: Path = DEFAULT_INCIDENT_REPLAY_DRILL_CONTRACT,
    paper_validation_replay: Path = DEFAULT_PAPER_VALIDATION_REPLAY,
    max_principal_usd: float = 0.0,
    manual_reviewer: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = {
        "forward_evaluation": _resolve(root, forward_evaluation),
        "daily_run": _resolve(root, daily_run),
        "strategy_gate": _resolve(root, strategy_gate),
        "four_hour_gate": _resolve(root, four_hour_gate),
        "intraday_report": _resolve(root, intraday_report),
        "five_minute_freeze": _resolve(root, five_minute_freeze),
        "forward_state": _resolve(root, forward_state),
        "paper_oms_session_contract": _resolve(root, paper_oms_session_contract),
        "incident_replay_drill_contract": _resolve(root, incident_replay_drill_contract),
        "paper_validation_replay": _resolve(root, paper_validation_replay),
    }
    reports = {name: _read_json(path) for name, path in paths.items()}
    blockers: list[str] = []

    missing = [name for name, payload in reports.items() if not payload]
    blockers.extend([f"btc_live_readiness_missing_{name}" for name in missing])

    forward_eval = reports["forward_evaluation"]
    observation_days = int(
        _nested(forward_eval, "metrics.observation_days", default=0)
        or _nested(forward_eval, "state.days_completed", default=0)
        or _nested(reports["forward_state"], "days_completed", default=0)
        or _nested(forward_eval, "forward_observation.observation_days", default=0)
        or 0
    )
    minimum_days = int(_nested(forward_eval, "minimum_complete_days", default=30) or 30)
    if observation_days < minimum_days:
        blockers.append("btc_live_readiness_forward_observation_less_than_30_days")
    if str(forward_eval.get("status", "")) != "raw_forward_complete_for_manual_review":
        blockers.append("btc_live_readiness_forward_observation_not_complete_for_manual_review")

    daily = reports["daily_run"]
    if daily and str(daily.get("status", "")) != "PASS":
        blockers.append("btc_live_readiness_daily_forward_pipeline_not_pass")
    if daily and str(_nested(daily, "steps.data_refresh.status", default="")) != "verified":
        blockers.append("btc_live_readiness_daily_data_refresh_not_verified")

    strategy = reports["strategy_gate"]
    if strategy and str(strategy.get("status", "")) != "strategy_backtest_validated":
        blockers.append("btc_live_readiness_strategy_gate_not_validated")

    four_hour = reports["four_hour_gate"]
    if four_hour and str(four_hour.get("status", "")) != "research_validation_passed_manual_review_required":
        blockers.append("btc_live_readiness_4h_gate_not_research_validated")

    five = reports["five_minute_freeze"]
    if five and str(five.get("status", "")) != "frozen_rejected_as_high_frequency":
        blockers.append("btc_live_readiness_5m_hft_not_frozen")
    if five and _nested(five, "guardrails.parameter_tuning_allowed", default=True) is not False:
        blockers.append("btc_live_readiness_5m_hft_parameter_tuning_not_locked")

    unsafe_flags = _unsafe_flags(reports)
    blockers.extend([f"btc_live_readiness_unsafe_flag:{item}" for item in unsafe_flags])

    if max_principal_usd <= 0.0:
        blockers.append("btc_live_readiness_max_principal_usd_not_set")
    if not manual_reviewer:
        blockers.append("btc_live_readiness_manual_reviewer_not_recorded")

    kill_switch_drill_complete = _kill_switch_drill_complete(reports["incident_replay_drill_contract"])
    reconciliation_proven = _reconciliation_proven(reports["paper_oms_session_contract"])
    replay_proven = _replay_proven(reports["paper_validation_replay"])
    blockers.extend(
        [
            "btc_live_readiness_exchange_credentials_not_configured",
            "btc_live_readiness_shadow_live_not_completed",
        ]
    )
    if not kill_switch_drill_complete:
        blockers.append("btc_live_readiness_kill_switch_not_proven")
    if not reconciliation_proven:
        blockers.append("btc_live_readiness_order_reconciliation_not_proven")
    if not replay_proven:
        blockers.append("btc_live_readiness_replay_not_proven")

    constitution = {
        "constitution_version": "btc_live_risk_constitution_v1",
        "scope": "BTC spot or externally capped ultra-low-risk pilot only; no perpetual leverage by default.",
        "capital": {
            "max_principal_usd": _round(max_principal_usd),
            "default_until_manual_set": 0.0,
            "capital_must_be_segregated": True,
            "do_not_add_capital_after_win_streak": True,
        },
        "instrument_limits": {
            "btc_spot_allowed_for_future_pilot": True,
            "perpetual_allowed": False,
            "leverage_cap": 1.0,
            "shorting_allowed": False,
        },
        "strategy_limits": {
            "primary_strategy": "btc_trend_raw_t01_twelve_month_momentum",
            "secondary_research_line": "btc_4h_atr_channel_breakout",
            "five_minute_hft_allowed": False,
            "parameter_tuning_during_forward_observation_allowed": False,
        },
        "loss_limits": {
            "pilot_daily_loss_stop_pct_of_principal": 2.0,
            "pilot_total_drawdown_stop_pct_of_principal": 5.0,
            "consecutive_bad_reconciliation_stop_count": 1,
            "manual_reset_required_after_stop": True,
        },
        "data_and_execution_stops": {
            "daily_data_refresh_must_pass": True,
            "latest_closed_bar_required": True,
            "stale_data_stop_hours": 36,
            "private_endpoint_allowed_before_live_gate": False,
            "order_endpoint_allowed_before_live_gate": False,
            "manual_order_confirmation_required_for_first_live_pilot": True,
        },
        "review_required": {
            "forward_observation_days": minimum_days,
            "manual_strategy_review": True,
            "manual_risk_review": True,
            "manual_credentials_review": True,
            "manual_kill_switch_drill": True,
        },
    }
    gate_checks = {
        "forward_observation_complete": observation_days >= minimum_days and str(forward_eval.get("status", "")) == "raw_forward_complete_for_manual_review",
        "daily_pipeline_pass": bool(daily) and str(daily.get("status", "")) == "PASS",
        "strategy_gate_validated": bool(strategy) and str(strategy.get("status", "")) == "strategy_backtest_validated",
        "four_hour_research_gate_validated": bool(four_hour) and str(four_hour.get("status", "")) == "research_validation_passed_manual_review_required",
        "five_minute_hft_frozen": bool(five) and str(five.get("status", "")) == "frozen_rejected_as_high_frequency",
        "no_unsafe_live_flags": not unsafe_flags,
        "max_principal_set": max_principal_usd > 0.0,
        "manual_reviewer_recorded": bool(manual_reviewer),
        "credentials_review_complete": False,
        "shadow_live_complete": False,
        "kill_switch_drill_complete": kill_switch_drill_complete,
        "reconciliation_proven": reconciliation_proven,
        "replay_proven": replay_proven,
    }
    status = "live_readiness_blocked"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": status,
        "decision": "do_not_start_live_trading",
        "asset": "btc",
        "live_order_allowed": False,
        "real_order_submitted": False,
        "paper_runner_unlocked_by_this_report": False,
        "selected_primary_line": "btc_trend_raw_t01_twelve_month_momentum",
        "secondary_research_line": "btc_4h_atr_channel_breakout",
        "forward_observation": {
            "status": str(forward_eval.get("status", "")),
            "observation_days": observation_days,
            "minimum_complete_days": minimum_days,
        },
        "daily_run": {
            "status": str(daily.get("status", "")),
            "data_refresh_status": str(_nested(daily, "steps.data_refresh.status", default="")),
            "blockers": _list(daily.get("blockers")),
        },
        "operational_evidence": {
            "kill_switch_drill": _evidence_summary(
                reports["incident_replay_drill_contract"],
                complete=kill_switch_drill_complete,
            ),
            "reconciliation": _evidence_summary(
                reports["paper_oms_session_contract"],
                complete=reconciliation_proven,
            ),
            "replay": _evidence_summary(
                reports["paper_validation_replay"],
                complete=replay_proven,
            ),
        },
        "gate_checks": gate_checks,
        "risk_constitution": constitution,
        "unsafe_flags": unsafe_flags,
        "blockers": _dedupe(blockers),
        "source_reports": {name: _relpath(path, root) for name, path in paths.items()},
        "source_report_details": {
            name: _source_report_detail(payload=reports.get(name, {}), path=path, root=root)
            for name, path in paths.items()
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
        "guardrails": {
            "research_only_until_live_gate_passes": True,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "manual_review_required": True,
        },
    }
    output_abs = _resolve(root, output)
    markdown_abs = _resolve(root, markdown_output)
    _write_json(output_abs, payload)
    _write_text(markdown_abs, _markdown(payload))
    return payload


def _unsafe_flags(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    keys = {
        "live_order_allowed",
        "live_ready",
        "private_endpoint_used",
        "order_endpoint_used",
        "real_order_submitted",
        "real_orders_created",
        "paper_runner_allowed",
    }
    out = []
    for report_name, payload in reports.items():
        for path, value in _walk(payload):
            key = path.split(".")[-1]
            if key in keys and value is True:
                out.append(f"{report_name}.{path}=true")
    return out


def _kill_switch_drill_complete(payload: Mapping[str, Any]) -> bool:
    required_scenarios = {"data_outage", "funding_gap", "ledger_mismatch", "order_reject"}
    observed_scenarios = set(_list(payload.get("required_scenarios")))
    return (
        bool(payload)
        and str(payload.get("status", "")) == "complete"
        and str(payload.get("decision", "")) == "incident_replay_drill_complete"
        and not _list(payload.get("blockers"))
        and required_scenarios.issubset(observed_scenarios)
        and _evidence_has_safe_execution_flags(payload)
    )


def _reconciliation_proven(payload: Mapping[str, Any]) -> bool:
    return (
        bool(payload)
        and str(payload.get("status", "")) == "complete"
        and str(payload.get("decision", "")) == "paper_oms_session_reconciled"
        and not _list(payload.get("blockers"))
        and not _list(payload.get("missing_fill_client_order_ids"))
        and not _list(payload.get("unknown_fill_client_order_ids"))
        and str(payload.get("ledger_hash", ""))
        and int(payload.get("order_count", 0) or 0) >= 1
        and int(payload.get("fill_count", 0) or 0) >= 1
        and _evidence_has_safe_execution_flags(payload)
    )


def _replay_proven(payload: Mapping[str, Any]) -> bool:
    return (
        bool(payload)
        and str(payload.get("status", "")) == "replay_pass"
        and str(payload.get("decision", "")) == "replay_pass"
        and not _list(payload.get("blockers"))
        and _nested(payload, "metadata.current_realtime_data_accessed", default=True) is False
    )


def _evidence_has_safe_execution_flags(payload: Mapping[str, Any]) -> bool:
    live_allowed = bool(payload.get("live_order_allowed", False) or payload.get("allows_live_orders", False))
    return (
        live_allowed is False
        and payload.get("private_endpoint_used", False) is False
        and payload.get("order_endpoint_used", False) is False
        and payload.get("real_order_submitted", False) is False
    )


def _evidence_summary(payload: Mapping[str, Any], *, complete: bool) -> dict[str, Any]:
    if not payload:
        return {
            "complete": False,
            "status": "missing",
            "decision": "missing",
            "blockers": ["missing"],
            "artifact_hash": "",
        }
    return {
        "complete": complete,
        "status": str(payload.get("status", "")),
        "decision": str(payload.get("decision", "")),
        "blockers": _list(payload.get("blockers")),
        "artifact_hash": str(payload.get("artifact_hash", "")),
    }


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


def _markdown(payload: Mapping[str, Any]) -> str:
    constitution = _mapping(payload.get("risk_constitution"))
    blockers = _list(payload.get("blockers"))
    gate_checks = _mapping(payload.get("gate_checks"))
    lines = [
        "# BTC 实盘前风控宪法",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        "## 当前结论",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 决策：`{payload.get('decision', '')}`",
        f"- live order allowed：`{payload.get('live_order_allowed', False)}`",
        "",
        "当前 BTC 系统不得实盘。本文档是实盘前门禁和风控宪法，不是实盘授权。",
        "",
        "## Gate 检查",
        "",
        "| 项目 | 结果 |",
        "| --- | --- |",
    ]
    for key, passed in gate_checks.items():
        lines.append(f"| {key} | {'PASS' if passed else 'FAIL'} |")
    lines += [
        "",
        "## 风控宪法",
        "",
        f"- 范围：{constitution.get('scope', '')}",
        f"- 最大实盘本金：`{_nested(constitution, 'capital.max_principal_usd', 0)}`，未人工设置前视为 `0`。",
        f"- 杠杆上限：`{_nested(constitution, 'instrument_limits.leverage_cap', 1.0)}`。",
        f"- 永续合约：`{_nested(constitution, 'instrument_limits.perpetual_allowed', False)}`。",
        f"- 试运行单日亏损停机：`{_nested(constitution, 'loss_limits.pilot_daily_loss_stop_pct_of_principal', 0)}%`。",
        f"- 试运行总回撤停机：`{_nested(constitution, 'loss_limits.pilot_total_drawdown_stop_pct_of_principal', 0)}%`。",
        f"- 数据过期停机：`{_nested(constitution, 'data_and_execution_stops.stale_data_stop_hours', 0)} 小时`。",
        "",
        "## 必须补齐后才能讨论实盘",
        "",
    ]
    for blocker in blockers:
        lines.append(f"- `{blocker}`")
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _source_report_detail(*, payload: Mapping[str, Any], path: Path, root: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        "path": _relpath(path, root),
        "exists": exists,
        "status": str(payload.get("status", "")) if payload else "",
        "generated_at": str(payload.get("generated_at", "") or payload.get("updated_at", "")) if payload else "",
        "sha256": _file_sha256(path) if exists else "",
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _nested(value: Any, dotted: str, default: Any = "") -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _round(value: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(out, 6) if math.isfinite(out) else 0.0


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


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
    parser = argparse.ArgumentParser(description="Build BTC live-readiness risk constitution.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--max-principal-usd", type=float, default=0.0)
    parser.add_argument("--manual-reviewer", default="")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_live_readiness_risk_constitution(
        repo_root=Path(args.repo_root),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        max_principal_usd=args.max_principal_usd,
        manual_reviewer=args.manual_reviewer,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
