#!/usr/bin/env python3
"""Build US equity monitoring, attribution, and retirement rules report."""

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

SCHEMA_VERSION = "us_equity_monitoring_rules_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_monitoring_rules_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 监控归因停用规则.md")


def build_us_equity_monitoring_rules_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    rules = _rules()
    audit_trail = _audit_trail_contract()
    incident_review = _incident_review_contract()
    replay_requirements = _replay_requirements()
    logging_policy = _logging_policy()
    strategy_lifecycle_review = _strategy_lifecycle_review_contract()
    monitor_count = sum(len(value) for value in rules.values() if isinstance(value, Mapping))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "monitoring_rules_defined",
        "asset": "us_equity",
        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
        "rules": rules,
        "monitor_count": monitor_count,
        "audit_trail": audit_trail,
        "incident_review": incident_review,
        "replay_requirements": replay_requirements,
        "logging_policy": logging_policy,
        "strategy_lifecycle_review": strategy_lifecycle_review,
        "minimum_required_before_paper": [
            "structured_daily_run_report",
            "forward_observation_ledger_reconciliation",
            "data_staleness_stop",
            "unsafe_endpoint_flag_stop",
            "incident_review_template",
            "replay_input_output_contract",
            "strategy_lifecycle_review_contract",
        ],
        "required_before_paper_or_live": True,
        "guardrails": {
            "rules_only": True,
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
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _rules() -> dict[str, dict[str, Any]]:
    return {
        "data_monitors": {
            "etf_price_stale_stop": {
                "severity": "block",
                "threshold": "latest_common_date stale > freshness SLA",
                "evidence": "us_equity_data_freshness_daily_report.json",
                "action": "BLOCK downstream forward/paper/live runners.",
            },
            "fred_macro_stale_stop": {
                "severity": "block",
                "threshold": "FRED macro missing or stale unless explicitly research-neutralized",
                "evidence": "us_equity_fred_macro_preflight_report.json",
                "action": "BLOCK or explicitly degrade only when strategy config allows it.",
            },
            "non_positive_price_stop": {
                "severity": "block",
                "threshold": "any tradable target price <= 0",
                "evidence": "us_equity_etf_kline_quality_daily_report.json",
                "action": "BLOCK strategy validation and forward observation.",
            },
            "extreme_return_review": {
                "severity": "manual_review",
                "threshold": "SPY/QQQ abs daily return > configured benchmark threshold or target sleeve extreme move",
                "evidence": "us_equity_etf_kline_quality_daily_report.json",
                "action": "Require manual data-quality and corporate-action review.",
            },
        },
        "position_and_execution_monitors": {
            "target_actual_weight_drift": {
                "severity": "manual_review",
                "threshold": "target versus simulated/paper/live weight drift > configured tolerance",
                "evidence": "target_positions.jsonl + portfolio_snapshots.jsonl",
                "action": "Review sizing, rounding, fills, cash, and financing before next roll.",
            },
            "cash_and_financing_reconciliation": {
                "severity": "block",
                "threshold": "cash, financing, fees, or exposure cannot be reconciled",
                "evidence": "fills.jsonl + portfolio_snapshots.jsonl",
                "action": "BLOCK paper/live and open incident review.",
            },
            "partial_fill_state_machine_required": {
                "severity": "block_before_paper",
                "threshold": "partial fill, cancel, reject, disconnect, reconnect not covered",
                "evidence": "paper simulation readiness report",
                "action": "Do not start paper simulation.",
            },
            "kill_switch_required": {
                "severity": "block",
                "threshold": "stale data, reconciliation mismatch, unsafe endpoint flag, or manual stop",
                "evidence": "daily production-line run report",
                "action": "Stop downstream execution immediately.",
            },
        },
        "attribution": {
            "asset_selection": {"required": True, "description": "Separate ETF selection effect."},
            "macro_switch": {"required": True, "description": "Separate macro/risk-off switch contribution."},
            "defensive_assets": {"required": True, "description": "Separate SHV/IEF/GLD defensive sleeve contribution."},
            "volatility_scaling": {"required": True, "description": "Separate exposure scaling effect."},
            "leverage_financing_slippage": {"required": True, "description": "Separate leverage, financing, and slippage from alpha."},
        },
        "retirement_rules": {
            "data_integrity_failure": {
                "severity": "freeze_or_retire",
                "trigger": "PIT, corporate-action, survivorship, or macro-lag evidence cannot be repaired.",
            },
            "cost_failure": {
                "severity": "freeze",
                "trigger": "25/50bps cost stress destroys risk-adjusted replacement value.",
            },
            "walk_forward_failure": {
                "severity": "freeze",
                "trigger": "OOS folds are driven by one narrow regime or parameter island.",
            },
            "forward_observation_failure": {
                "severity": "reset_or_new_strategy_id",
                "trigger": "Forward observation ledger breaks, timestamps duplicate, or parameters change.",
            },
            "risk_limit_failure": {
                "severity": "manual_review",
                "trigger": "Drawdown, repeated reconciliation mismatch, or execution drift exceeds policy.",
            },
        },
    }


def _audit_trail_contract() -> dict[str, Any]:
    return {
        "required_chain": [
            "data_snapshot",
            "feature",
            "signal",
            "forecast_or_target_position",
            "risk_decision",
            "simulated_or_paper_order",
            "fill",
            "ledger",
            "pnl",
            "report",
        ],
        "promotion_gate_must_record_reasons": True,
        "manual_approval_requires_reviewer_time_reason": True,
        "historical_result_changes_require_new_run_id": True,
    }


def _incident_review_contract() -> dict[str, Any]:
    return {
        "triggers": [
            "data_interruption",
            "signal_anomaly",
            "backtest_paper_live_mismatch",
            "risk_gate_misfire",
            "order_failure",
            "duplicate_order",
            "ledger_reconciliation_failure",
            "loss_or_drawdown_threshold_breach",
        ],
        "required_template_fields": [
            "timeline",
            "impact_scope",
            "direct_cause",
            "root_cause",
            "gate_that_failed_to_block",
            "remediation",
            "regression_test",
            "pause_or_retire_decision",
        ],
        "incident_review_must_create_test_or_rule_update": True,
    }


def _replay_requirements() -> dict[str, Any]:
    return {
        "must_not_access_current_realtime_data": True,
        "fixed_clock_required": True,
        "fixed_random_seed_required": True,
        "inputs": ["data_snapshot", "strategy_version", "params", "risk_config", "current_position", "orders_and_fills"],
        "outputs": ["replayed_signal", "replayed_target_position", "replayed_risk_decision", "diff_vs_original_artifact"],
        "replay_failure_severity": "serious_auditability_issue",
    }


def _logging_policy() -> dict[str, Any]:
    return {
        "structured_logs_required": True,
        "secret_values_must_not_be_logged": True,
        "required_fields": [
            "run_id",
            "strategy_id",
            "data_version",
            "decision_time",
            "signal",
            "forecast",
            "target_position",
            "risk_decision",
            "order_id",
            "fill_id",
            "error_code",
        ],
    }


def _strategy_lifecycle_review_contract() -> dict[str, Any]:
    return {
        "cadence": [
            {
                "review_id": "forward_30d_manual_review",
                "trigger": "30 valid forward-observation days complete",
                "allowed_decisions": ["continue_observation", "freeze_strategy", "new_strategy_id_required"],
            },
            {
                "review_id": "forward_60_90d_manual_review",
                "trigger": "60 or 90 valid forward-observation days complete",
                "allowed_decisions": ["continue_observation", "paper_simulation_review_candidate", "freeze_strategy"],
            },
            {
                "review_id": "monthly_strategy_health_review",
                "trigger": "calendar month end or material market regime change",
                "allowed_decisions": ["continue", "reduce_scope", "freeze_strategy", "retire_strategy"],
            },
            {
                "review_id": "incident_forced_review",
                "trigger": "data, ledger, risk, execution, or drawdown incident",
                "allowed_decisions": ["freeze_strategy", "retire_strategy", "new_strategy_id_required"],
            },
        ],
        "required_evidence": [
            "latest_daily_production_line_run_report",
            "strategy_validation_gate_report",
            "forward_observation_evaluation_report",
            "paper_or_forward_ledger_reconciliation",
            "data_freshness_and_quality_reports",
            "cost_liquidity_capacity_stress_reports",
            "attribution_report",
            "manual_reviewer_decision_record",
        ],
        "decision_record_fields": [
            "review_id",
            "reviewed_at",
            "reviewer",
            "decision",
            "evidence_paths",
            "reason",
            "follow_up_ticket_ids",
            "parameter_or_strategy_id_change_required",
        ],
        "forbidden_decisions": [
            "auto_live_enable",
            "auto_paper_enable_without_manual_review",
            "reuse_strategy_id_after_parameter_change",
        ],
        "parameter_change_requires_new_strategy_id": True,
        "retirement_requires_manual_reason": True,
        "live_unlock_allowed": False,
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    rules = payload.get("rules") if isinstance(payload.get("rules"), Mapping) else {}
    lines = [
        "# US Equity 监控归因停用规则",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"- 状态：`{payload.get('status', '')}`",
        "",
        "该报告定义 paper/live 前必须具备的监控、归因和停用规则，不授权交易。",
        "",
    ]
    for section, items in rules.items():
        lines += [f"## {section}", ""]
        if isinstance(items, Mapping):
            for key, value in items.items():
                if isinstance(value, Mapping):
                    lines.append(f"- `{key}`：{json.dumps(dict(value), ensure_ascii=False)}")
                else:
                    lines.append(f"- `{key}`：{value}")
        lines.append("")
    return "\n".join(lines).strip()


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


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity monitoring rules report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_monitoring_rules_report(
        repo_root=Path(args.repo_root),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
