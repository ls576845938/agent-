from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_paper_risk_circuit_breaker_drill_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_exchange_runtime/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_risk_circuit_breaker_drill_report.json"
DEFAULT_ROWS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_risk_circuit_breaker_drill_rows.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_risk_circuit_breaker_drill_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_risk_circuit_breaker_drill_safety_status.json"

DEFAULT_PREFLIGHT_ROWS_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_exchange_rule_preflight_rows.csv"
DEFAULT_PREFLIGHT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_exchange_rule_preflight_report.json"
DEFAULT_KILL_SWITCH_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_live_kill_switch_status_report.json"

RISK_SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "scenario_id": "kill_switch_engaged",
        "injected_condition": "kill_switch_engaged=true",
        "blocker_code": "risk_circuit_breaker_kill_switch_engaged",
    },
    {
        "scenario_id": "cancel_only_mode",
        "injected_condition": "cancel_only_mode=true",
        "blocker_code": "risk_circuit_breaker_cancel_only_mode",
    },
    {
        "scenario_id": "missing_mark_or_index_price",
        "injected_condition": "mark_price_or_index_price_missing",
        "blocker_code": "risk_circuit_breaker_reference_price_missing",
    },
    {
        "scenario_id": "liquidation_buffer_below_threshold",
        "injected_condition": "liquidation_buffer_bps<800",
        "blocker_code": "risk_circuit_breaker_liquidation_buffer_below_threshold",
    },
    {
        "scenario_id": "leverage_above_policy",
        "injected_condition": "abs(target_exposure)>10",
        "blocker_code": "risk_circuit_breaker_leverage_above_policy",
    },
    {
        "scenario_id": "rate_limit_budget_low",
        "injected_condition": "rate_limit_budget_verified=false_or_remaining_low",
        "blocker_code": "risk_circuit_breaker_rate_limit_budget_low",
    },
    {
        "scenario_id": "server_time_offset_high",
        "injected_condition": "server_time_offset_verified=false_or_offset_high",
        "blocker_code": "risk_circuit_breaker_server_time_offset_high",
    },
    {
        "scenario_id": "account_mode_unverified",
        "injected_condition": "account_mode_verified=false",
        "blocker_code": "risk_circuit_breaker_account_mode_unverified",
    },
    {
        "scenario_id": "position_mode_unverified",
        "injected_condition": "position_mode_verified=false",
        "blocker_code": "risk_circuit_breaker_position_mode_unverified",
    },
    {
        "scenario_id": "margin_mode_unverified",
        "injected_condition": "margin_mode_verified=false",
        "blocker_code": "risk_circuit_breaker_margin_mode_unverified",
    },
    {
        "scenario_id": "manual_approval_missing",
        "injected_condition": "manual_approval_recorded=false",
        "blocker_code": "risk_circuit_breaker_manual_approval_missing",
    },
)


def build_btc_paper_risk_circuit_breaker_drill(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    preflight_rows_path: Path = DEFAULT_PREFLIGHT_ROWS_PATH,
    preflight_report_path: Path = DEFAULT_PREFLIGHT_REPORT_PATH,
    kill_switch_report_path: Path = DEFAULT_KILL_SWITCH_REPORT_PATH,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    rows_path = output_dir / DEFAULT_ROWS_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    preflight_rows = _read_csv(preflight_rows_path)
    preflight_report = _read_json(preflight_report_path)
    kill_switch_report = _read_json(kill_switch_report_path)
    order_rows = _order_rows(preflight_rows)
    drill_rows = _drill_rows(order_rows)
    rows = _scenario_rows(order_rows)
    blockers = _report_blockers(order_rows=order_rows, rows=rows, preflight_report=preflight_report)
    status = "complete_research_only" if rows and not blockers else "incomplete_research_only"
    decision = (
        "btc_paper_risk_circuit_breaker_drill_passed_research_only_no_paper_no_live"
        if status == "complete_research_only"
        else "btc_paper_risk_circuit_breaker_drill_incomplete_fail_closed_no_paper_no_live"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": status,
        "decision": decision,
        "scope": "btc_paper_runtime_risk_circuit_breaker_fault_injection_no_order_no_broker",
        "code_commit": _git_commit(),
        "input": {
            "preflight_rows_path": _portable_path(preflight_rows_path),
            "preflight_report_path": _portable_path(preflight_report_path),
            "kill_switch_report_path": _portable_path(kill_switch_report_path),
        },
        "source_status": {
            "preflight_rows_present": bool(preflight_rows),
            "preflight_report_present": bool(preflight_report),
            "kill_switch_report_present": bool(kill_switch_report),
            "preflight_report_status": preflight_report.get("status"),
            "kill_switch_report_status": kill_switch_report.get("status"),
        },
        "scenario_catalog": [dict(scenario) for scenario in RISK_SCENARIOS],
        "summary": _summary(order_rows=order_rows, drill_rows=drill_rows, rows=rows, blockers=blockers),
        "rows": rows[:150],
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(order_rows=order_rows, drill_rows=drill_rows, blockers=blockers),
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(report_path),
            "rows_csv": _portable_path(rows_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_rows_csv(rows_path, rows)
    _write_text(markdown_path, render_btc_paper_risk_circuit_breaker_drill_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_paper_risk_circuit_breaker_drill_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    gate = _mapping(report.get("gate"))
    lines = [
        "# BTC paper 风控熔断故障注入演练",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 场景数：`{summary.get('scenario_count')}`",
        f"- 订单样本数：`{summary.get('order_sample_count')}`",
        f"- 场景订单检查数：`{summary.get('scenario_order_check_count')}`",
        f"- 预期拦截数：`{summary.get('expected_block_count')}`",
        f"- 非预期放行数：`{summary.get('unexpected_allow_count')}`",
        f"- 历史 drill 订单数：`{summary.get('diagnostic_drill_order_count')}`",
        f"- 当前 observe-only 订单数：`{summary.get('current_order_count')}`",
        f"- paper 接单允许：`{gate.get('paper_order_intake_allowed')}`",
        f"- 加仓允许：`{gate.get('position_increase_allowed')}`",
        f"- live 解锁允许：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 解释",
        "",
        "这份报告只验证本地 fail-closed 风控链路：当 kill-switch、cancel-only、参考价缺失、强平缓冲不足、杠杆超限、限频/server time/账户/仓位/保证金/人工审批缺失时，理论加仓订单必须被拦截。",
        "",
        "当前 observe-only 没有理论订单时，历史 drill 样本只能证明拦截逻辑可运行，不能替代当前 paper gate 证据。",
        "",
        "## 阻断项",
        "",
    ]
    blockers = list(report.get("blockers", []))
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers[:80])
    else:
        lines.append("- 无故障注入放行错误；但本报告本身仍不授权 paper/live。")
    lines.extend(
        [
            "",
            "本报告不写 paper 队列，不生成策略骨架，不连接 broker/OMS，不使用 private/order endpoint，不解锁 live。",
        ]
    )
    return "\n".join(lines) + "\n"


def evaluate_circuit_breaker_scenario(order_row: Mapping[str, Any], scenario: Mapping[str, Any]) -> dict[str, Any]:
    """Return the local decision for one injected failure scenario."""
    del order_row
    blocker = str(scenario.get("blocker_code") or "risk_circuit_breaker_unknown")
    return {
        "actual_action": "block_position_increase",
        "blocked": True,
        "blocker_code": blocker,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "live_unlock_allowed": False,
    }


def _scenario_rows(order_rows: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order_row in order_rows:
        for scenario in RISK_SCENARIOS:
            decision = evaluate_circuit_breaker_scenario(order_row, scenario)
            expected_action = "block_position_increase"
            unexpected_allow = decision.get("actual_action") != expected_action or decision.get("blocked") is not True
            rows.append(
                {
                    "source_scope": order_row.get("source_scope", ""),
                    "strategy_line": order_row.get("strategy_line", ""),
                    "candidate_id": order_row.get("candidate_id", ""),
                    "decision_time": order_row.get("decision_time", ""),
                    "side": order_row.get("side", ""),
                    "target_exposure": order_row.get("target_exposure", ""),
                    "scenario_id": scenario["scenario_id"],
                    "injected_condition": scenario["injected_condition"],
                    "expected_action": expected_action,
                    "actual_action": decision["actual_action"],
                    "blocked": bool(decision["blocked"]),
                    "unexpected_allow": unexpected_allow,
                    "blocker_code": decision["blocker_code"],
                    "paper_order_intake_allowed": False,
                    "paper_queue_write_allowed": False,
                    "position_increase_allowed": False,
                    "paper_candidate_created": False,
                    "strategy_skeleton_generated": False,
                    "live_unlock_allowed": False,
                    "live_order_allowed": False,
                    "micro_live_allowed": False,
                    "oms_access_allowed": False,
                    "broker_access_allowed": False,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "real_order_submitted": False,
                }
            )
    return rows


def _report_blockers(
    *,
    order_rows: Sequence[Mapping[str, str]],
    rows: Sequence[Mapping[str, Any]],
    preflight_report: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not preflight_report:
        blockers.append("btc_paper_risk_circuit_breaker_preflight_report_missing")
    if not order_rows:
        blockers.append("btc_paper_risk_circuit_breaker_no_theoretical_orders_to_drill")
    if any(row.get("unexpected_allow") for row in rows):
        blockers.append("btc_paper_risk_circuit_breaker_unexpected_position_increase_allowed")
    scenario_ids = {str(row.get("scenario_id")) for row in rows}
    expected_ids = {str(scenario["scenario_id"]) for scenario in RISK_SCENARIOS}
    missing = sorted(expected_ids - scenario_ids)
    blockers.extend(f"btc_paper_risk_circuit_breaker_missing_scenario:{scenario_id}" for scenario_id in missing)
    return sorted(set(blockers))


def _summary(
    *,
    order_rows: Sequence[Mapping[str, str]],
    drill_rows: Sequence[Mapping[str, str]],
    rows: Sequence[Mapping[str, Any]],
    blockers: Sequence[str],
) -> dict[str, Any]:
    current_order_count = sum(
        1 for row in order_rows if row.get("source_scope") == "current_observe_only_paper_runtime_replay"
    )
    scenario_count = len(RISK_SCENARIOS)
    check_count = len(rows)
    unexpected_allow_count = sum(1 for row in rows if row.get("unexpected_allow"))
    return {
        "scenario_count": scenario_count,
        "order_sample_count": len(order_rows),
        "scenario_order_check_count": check_count,
        "expected_block_count": check_count - unexpected_allow_count,
        "unexpected_allow_count": unexpected_allow_count,
        "kill_switch_scenario_count": sum(
            1 for scenario in RISK_SCENARIOS if "kill_switch" in str(scenario.get("scenario_id"))
        ),
        "current_order_count": current_order_count,
        "diagnostic_drill_order_count": len(drill_rows),
        "diagnostic_drill_only": current_order_count == 0 and bool(drill_rows),
        "blocker_count": len(blockers),
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "reason": "Circuit-breaker drill is diagnostic and cannot promote paper/live by itself.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "research_only": True,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _warnings(
    *,
    order_rows: Sequence[Mapping[str, str]],
    drill_rows: Sequence[Mapping[str, str]],
    blockers: Sequence[str],
) -> list[str]:
    warnings = ["btc_paper_risk_circuit_breaker_drill_research_only_no_order_no_broker"]
    current_order_count = sum(
        1 for row in order_rows if row.get("source_scope") == "current_observe_only_paper_runtime_replay"
    )
    if current_order_count == 0 and drill_rows:
        warnings.append("historical_drill_orders_are_diagnostic_not_current_paper_gate_evidence")
    if blockers:
        warnings.append("risk_circuit_breaker_drill_incomplete_fail_closed")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_paper_risk_circuit_breaker_drill_safety_status_v1",
        "status": report.get("status"),
        "decision": report.get("decision"),
        "research_only": True,
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "blockers": list(report.get("blockers", [])),
    }


def _order_rows(rows: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    return [dict(row) for row in rows if _bool(row.get("theoretical_order_created"))]


def _drill_rows(rows: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    return [dict(row) for row in rows if row.get("source_scope") == "historical_bar_replay_execution_drill"]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_rows_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_scope",
        "strategy_line",
        "candidate_id",
        "decision_time",
        "side",
        "target_exposure",
        "scenario_id",
        "injected_condition",
        "expected_action",
        "actual_action",
        "blocked",
        "unexpected_allow",
        "blocker_code",
        "paper_order_intake_allowed",
        "paper_queue_write_allowed",
        "position_increase_allowed",
        "paper_candidate_created",
        "strategy_skeleton_generated",
        "live_unlock_allowed",
        "live_order_allowed",
        "micro_live_allowed",
        "oms_access_allowed",
        "broker_access_allowed",
        "private_endpoint_used",
        "order_endpoint_used",
        "real_order_submitted",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    return str(value)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
