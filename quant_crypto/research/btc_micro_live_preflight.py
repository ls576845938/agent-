from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_micro_live_preflight_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_micro_live_preflight/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_micro_live_preflight_report.json"
DEFAULT_MATRIX_PATH = DEFAULT_OUTPUT_DIR / "btc_micro_live_preflight_matrix.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_micro_live_preflight_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_OBSERVE_ONLY_HEALTH_REPORT = Path("artifacts/btc_observe_only_health/latest/btc_observe_only_health_report.json")
DEFAULT_STRATEGY_PROMOTION_READINESS_REPORT = Path(
    "artifacts/btc_strategy_promotion_readiness/latest/btc_strategy_promotion_readiness_report.json"
)
DEFAULT_KILL_SWITCH_STATUS_REPORT = Path("artifacts/btc_exchange_runtime/latest/btc_paper_live_kill_switch_status_report.json")
DEFAULT_EXCHANGE_RUNTIME_GAP_REPORT = Path("artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_replay_gap_report.json")
DEFAULT_PAPER_RUNTIME_REPLAY_REPORT = Path(
    "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_report.json"
)
DEFAULT_PAPER_RUNTIME_RECONCILIATION_REPORT = Path(
    "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_reconciliation_report.json"
)
DEFAULT_PAPER_EXCHANGE_RULE_PREFLIGHT_REPORT = Path(
    "artifacts/btc_exchange_runtime/latest/btc_paper_exchange_rule_preflight_report.json"
)
DEFAULT_PAPER_RISK_CIRCUIT_BREAKER_DRILL_REPORT = Path(
    "artifacts/btc_exchange_runtime/latest/btc_paper_risk_circuit_breaker_drill_report.json"
)
DEFAULT_PERPETUAL_EXECUTION_EVIDENCE_REPORT = Path(
    "artifacts/btc_perpetual_execution_evidence/latest/btc_perpetual_execution_evidence_report.json"
)
DEFAULT_GATE_DASHBOARD_REPORT = Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json")
DEFAULT_MANUAL_PAPER_REVIEW_APPROVAL_REPORT = Path(
    "artifacts/btc_manual_paper_review_approval/latest/btc_manual_paper_review_approval_report.json"
)
DEFAULT_OPERATOR_PAPER_INTAKE_ENVELOPE_PATH = Path("configs/btc/paper_runtime/operator_paper_intake_envelope.json")
OPERATOR_PAPER_INTAKE_ENVELOPE_SCHEMA_VERSION = "btc_operator_paper_intake_envelope_v1"
OPERATOR_PAPER_INTAKE_ENVELOPE_SCOPE = "paper_intake_envelope_review_only_no_auto_paper_no_live"

BAD_TRUE_FLAGS = {
    "paper_queue_write_allowed",
    "paper_candidate_created",
    "paper_order_intake_allowed",
    "position_increase_allowed",
    "strategy_skeleton_generated",
    "micro_live_allowed",
    "live_unlock_allowed",
    "live_order_allowed",
    "broker_access_allowed",
    "oms_access_allowed",
    "private_endpoint_used",
    "order_endpoint_used",
    "real_order_submitted",
    "paper_or_live_unlock_allowed",
}

SOURCE_SPECS = (
    "observe_only_health",
    "strategy_promotion_readiness",
    "paper_live_kill_switch_status",
    "exchange_runtime_gap",
    "paper_runtime_replay",
    "paper_runtime_reconciliation",
    "paper_exchange_rule_preflight",
    "paper_risk_circuit_breaker_drill",
    "perpetual_execution_evidence",
    "gate_dashboard",
    "manual_paper_review_approval",
)

SELF_REFERENCE_BLOCKER_TOKENS = {
    "btc_gate_dashboard_micro_live_preflight_blocked",
}


def build_btc_micro_live_preflight(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    observe_only_health_report_path: Path = DEFAULT_OBSERVE_ONLY_HEALTH_REPORT,
    strategy_promotion_readiness_report_path: Path = DEFAULT_STRATEGY_PROMOTION_READINESS_REPORT,
    kill_switch_status_report_path: Path = DEFAULT_KILL_SWITCH_STATUS_REPORT,
    exchange_runtime_gap_report_path: Path = DEFAULT_EXCHANGE_RUNTIME_GAP_REPORT,
    paper_runtime_replay_report_path: Path = DEFAULT_PAPER_RUNTIME_REPLAY_REPORT,
    paper_runtime_reconciliation_report_path: Path = DEFAULT_PAPER_RUNTIME_RECONCILIATION_REPORT,
    paper_exchange_rule_preflight_report_path: Path = DEFAULT_PAPER_EXCHANGE_RULE_PREFLIGHT_REPORT,
    paper_risk_circuit_breaker_drill_report_path: Path = DEFAULT_PAPER_RISK_CIRCUIT_BREAKER_DRILL_REPORT,
    perpetual_execution_evidence_report_path: Path = DEFAULT_PERPETUAL_EXECUTION_EVIDENCE_REPORT,
    gate_dashboard_report_path: Path = DEFAULT_GATE_DASHBOARD_REPORT,
    manual_paper_review_approval_report_path: Path = DEFAULT_MANUAL_PAPER_REVIEW_APPROVAL_REPORT,
    operator_paper_intake_envelope_path: Path = DEFAULT_OPERATOR_PAPER_INTAKE_ENVELOPE_PATH,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
    manual_approval_id: str | None = None,
    approved_initial_principal_usdt: float = 0.0,
    approved_max_order_notional_usdt: float = 0.0,
    approved_max_leverage: float = 0.0,
    approved_max_daily_orders: int = 0,
) -> dict[str, Any]:
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    matrix_path = output_dir / DEFAULT_MATRIX_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    paths = {
        "observe_only_health": observe_only_health_report_path,
        "strategy_promotion_readiness": strategy_promotion_readiness_report_path,
        "paper_live_kill_switch_status": kill_switch_status_report_path,
        "exchange_runtime_gap": exchange_runtime_gap_report_path,
        "paper_runtime_replay": paper_runtime_replay_report_path,
        "paper_runtime_reconciliation": paper_runtime_reconciliation_report_path,
        "paper_exchange_rule_preflight": paper_exchange_rule_preflight_report_path,
        "paper_risk_circuit_breaker_drill": paper_risk_circuit_breaker_drill_report_path,
        "perpetual_execution_evidence": perpetual_execution_evidence_report_path,
        "gate_dashboard": gate_dashboard_report_path,
        "manual_paper_review_approval": manual_paper_review_approval_report_path,
    }
    sources = {name: _read_source(path) for name, path in paths.items()}
    matrix = [_source_row(name, sources[name]) for name in SOURCE_SPECS]
    operator_envelope = _operator_paper_intake_envelope(
        operator_paper_intake_envelope_path,
        now=generated,
    )
    manual_gate = _manual_gate(
        manual_paper_review_approval=_mapping(sources["manual_paper_review_approval"].get("payload")),
        operator_envelope=operator_envelope,
        manual_approval_id=manual_approval_id,
        approved_initial_principal_usdt=approved_initial_principal_usdt,
        approved_max_order_notional_usdt=approved_max_order_notional_usdt,
        approved_max_leverage=approved_max_leverage,
        approved_max_daily_orders=approved_max_daily_orders,
    )
    blockers = _blockers(matrix=matrix, sources=sources, manual_gate=manual_gate)
    status = "blocked_fail_closed_research_only" if blockers else "complete_research_only_manual_review_required"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "aggregation_batch_id": aggregation_batch_id or "",
        "status": status,
        "decision": (
            "btc_micro_live_preflight_blocked_fail_closed_no_live"
            if blockers
            else "btc_micro_live_preflight_complete_no_auto_live_unlock"
        ),
        "scope": "btc_micro_live_preflight_evidence_aggregation_no_order_no_broker",
        "code_commit": _git_commit(),
        "input": {
            **{name: _portable_path(path) for name, path in paths.items()},
            "operator_paper_intake_envelope_path": _portable_path(operator_paper_intake_envelope_path),
        },
        "summary": _summary(matrix=matrix, blockers=blockers, sources=sources, manual_gate=manual_gate),
        "source_matrix": matrix,
        "operator_paper_intake_envelope": operator_envelope,
        "manual_gate": manual_gate,
        "micro_live_envelope": _micro_live_envelope(manual_gate),
        "policy_state": _policy_state(blockers=blockers),
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(blockers),
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(report_path),
            "matrix_csv": _portable_path(matrix_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_matrix_csv(matrix_path, matrix)
    _write_text(markdown_path, render_btc_micro_live_preflight_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_micro_live_preflight_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    policy = _mapping(report.get("policy_state"))
    lines = [
        "# BTC micro-live 预检总表",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 输入证据数：`{summary.get('source_count')}`，缺失：`{summary.get('missing_source_count')}`",
        f"- 未通过检查：`{summary.get('failed_source_check_count')}`",
        f"- 上游 blocker：`{summary.get('upstream_blocker_count')}`",
        f"- observe-only 60 天完成：`{summary.get('observe_only_60d_complete')}`",
        f"- 当前 paper runtime 模拟成交数：`{summary.get('paper_runtime_current_simulated_fill_count')}`",
        f"- kill-switch 拉闸：`{summary.get('kill_switch_engaged')}`",
        f"- 人工批准：`{summary.get('manual_approval_recorded')}`",
        f"- micro-live 允许：`{policy.get('micro_live_allowed')}`",
        f"- live 解锁：`{policy.get('live_unlock_allowed')}`",
        "",
        "## 证据矩阵",
        "",
        "| 证据 | 状态 | blocker | 安全旗标异常 | 结论 |",
        "|---|---|---:|---:|---|",
    ]
    for row in report.get("source_matrix", []):
        lines.append(
            "| `{source_id}` | `{status}` | {blockers} | {unsafe} | `{decision}` |".format(
                source_id=row.get("source_id"),
                status=row.get("status"),
                blockers=row.get("blocker_count"),
                unsafe=row.get("true_safety_flag_count"),
                decision=row.get("source_decision"),
            )
        )
    lines.extend(
        [
            "",
            "## 当前含义",
            "",
            "- 这不是实盘入口，只是把 observe-only、paper runtime、交易所规则、熔断演练和 kill-switch 证据合到一张表。",
            "- 当前默认 fail-closed：不写 paper 队列，不生成策略骨架，不接 broker/OMS，不访问 private/order endpoint，不解锁 live。",
            "- 即使未来所有上游证据都干净，也还需要人工批准、明确本金上限、订单上限、杠杆上限和运行手册。",
            "",
            "## 阻断项",
            "",
        ]
    )
    blockers = list(report.get("blockers", []))
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers[:120])
        if len(blockers) > 120:
            lines.append(f"- ... 其余 {len(blockers) - 120} 项见 JSON")
    else:
        lines.append("- 无")
    lines.append("")
    return "\n".join(lines)


def _source_row(source_id: str, source: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(source.get("payload"))
    true_flags = _true_flag_paths(payload)
    blockers = _source_blockers(source_id, payload, present=bool(source.get("present")))
    artifact_blockers = _filtered_artifact_blockers(payload.get("blockers"))
    return {
        "source_id": source_id,
        "path": source.get("path"),
        "present": bool(source.get("present")),
        "status": payload.get("status") or ("present" if payload else "missing"),
        "decision": payload.get("decision"),
        "blocker_count": len(artifact_blockers),
        "ignored_self_reference_blocker_count": len(_list(payload.get("blockers"))) - len(artifact_blockers),
        "true_safety_flag_count": len(true_flags),
        "true_safety_flags": true_flags[:40],
        "source_decision": "source_preflight_pass" if not blockers and not true_flags else "source_preflight_blocked",
        "line_blockers": sorted(set([*blockers, *[f"true_safety_flag:{path}" for path in true_flags]])),
    }


def _source_blockers(source_id: str, payload: Mapping[str, Any], *, present: bool) -> list[str]:
    if not present:
        return [f"missing_input:{source_id}"]
    blockers: list[str] = []
    status = str(payload.get("status") or "").lower()
    decision = str(payload.get("decision") or "").lower()
    source_blockers = _filtered_artifact_blockers(payload.get("blockers"))
    if any(token in status for token in ("blocked", "fail", "incomplete", "missing")):
        blockers.append(f"{source_id}:status:{payload.get('status')}")
    if any(token in decision for token in ("blocked", "fail_closed", "incomplete")):
        blockers.append(f"{source_id}:decision:{payload.get('decision')}")
    blockers.extend(f"{source_id}:source_blocker:{item}" for item in source_blockers)
    blockers.extend(_specific_source_blockers(source_id, payload))
    return blockers


def _operator_paper_intake_envelope(path: Path, *, now: datetime) -> dict[str, Any]:
    payload = _read_json(path)
    blockers: list[str] = []
    if not payload:
        blockers.append("operator_paper_intake_envelope_file_missing")
    if str(payload.get("schema_version", "")) != OPERATOR_PAPER_INTAKE_ENVELOPE_SCHEMA_VERSION:
        blockers.append("operator_paper_intake_envelope_schema_invalid")
    if payload.get("redacted_operator_envelope") is not True:
        blockers.append("operator_paper_intake_envelope_redaction_flag_missing")
    if str(payload.get("approval_scope", "")) != OPERATOR_PAPER_INTAKE_ENVELOPE_SCOPE:
        blockers.append("operator_paper_intake_envelope_scope_invalid")
    expiry = _parse_utc(payload.get("expiry_utc"))
    if not expiry:
        blockers.append("operator_paper_intake_envelope_expiry_invalid")
    elif expiry <= now:
        blockers.append("operator_paper_intake_envelope_expired")
    if _secret_like_key_count(payload):
        blockers.append("operator_paper_intake_envelope_contains_secret_like_field")
    for flag in ("paper_queue_write_allowed", "paper_order_intake_allowed", "live_unlock_allowed"):
        if payload.get(flag) is not False:
            blockers.append(f"operator_paper_intake_envelope_{flag}_not_false")
    values = {
        "approved_initial_principal_usdt": _float(payload.get("approved_initial_principal_usdt")),
        "approved_max_order_notional_usdt": _float(payload.get("approved_max_order_notional_usdt")),
        "approved_max_leverage": _float(payload.get("approved_max_leverage")),
        "approved_max_daily_orders": int(_float(payload.get("approved_max_daily_orders"))),
    }
    if values["approved_initial_principal_usdt"] <= 0:
        blockers.append("operator_paper_intake_envelope_initial_principal_missing")
    if values["approved_max_order_notional_usdt"] <= 0:
        blockers.append("operator_paper_intake_envelope_order_notional_missing")
    if values["approved_max_leverage"] <= 0:
        blockers.append("operator_paper_intake_envelope_leverage_missing")
    if values["approved_max_daily_orders"] <= 0:
        blockers.append("operator_paper_intake_envelope_daily_order_limit_missing")
    return {
        "schema_version": OPERATOR_PAPER_INTAKE_ENVELOPE_SCHEMA_VERSION,
        "path": _portable_path(path),
        "present": bool(payload),
        "status": "recorded_redacted" if not blockers else "missing_or_invalid",
        "redacted_operator_envelope": payload.get("redacted_operator_envelope") is True,
        "reviewer_recorded": bool(str(payload.get("reviewer", "")).strip()),
        "decision_date_utc": str(payload.get("decision_date_utc", "")),
        "expiry_utc": str(payload.get("expiry_utc", "")),
        "approval_scope": str(payload.get("approval_scope", "")),
        "values": values,
        "paper_queue_write_allowed": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "blockers": sorted(set(blockers)),
    }


def _filtered_artifact_blockers(value: Any) -> list[Any]:
    return [item for item in _list(value) if not _is_self_reference_blocker(item)]


def _is_self_reference_blocker(value: Any) -> bool:
    text = str(value)
    return any(token in text for token in SELF_REFERENCE_BLOCKER_TOKENS)


def _specific_source_blockers(source_id: str, payload: Mapping[str, Any]) -> list[str]:
    summary = _mapping(payload.get("summary"))
    policy = _mapping(payload.get("policy_state"))
    blockers: list[str] = []
    if source_id == "observe_only_health":
        if summary.get("all_lines_target_60d_complete") is not True:
            blockers.append("observe_only_health:60d_observe_only_not_complete")
        if _int(summary.get("safety_violation_count")):
            blockers.append("observe_only_health:safety_violation_count_nonzero")
    elif source_id == "strategy_promotion_readiness":
        if _int(summary.get("ready_for_paper_count")) <= 0:
            blockers.append("strategy_promotion_readiness:no_line_ready_for_manual_paper_review")
    elif source_id == "paper_live_kill_switch_status":
        if policy.get("kill_switch_engaged") is not False:
            blockers.append("paper_live_kill_switch_status:kill_switch_engaged")
    elif source_id == "paper_runtime_replay":
        if summary.get("paper_runtime_replay_ready") is not True:
            blockers.append("paper_runtime_replay:paper_runtime_replay_not_ready")
        if _int(summary.get("simulated_fill_count")) <= 0:
            if summary.get("current_flat_heartbeat_healthy") is True:
                blockers.append("paper_runtime_replay:current_flat_heartbeat_waiting_for_trade_sample")
            else:
                blockers.append("paper_runtime_replay:no_current_simulated_fills")
    elif source_id == "paper_runtime_reconciliation":
        if summary.get("paper_runtime_reconciliation_passed") is not True:
            blockers.append("paper_runtime_reconciliation:not_passed")
        if _int(summary.get("violation_count")):
            blockers.append("paper_runtime_reconciliation:violation_count_nonzero")
    elif source_id == "paper_exchange_rule_preflight":
        if _int(summary.get("order_filter_violation_count")):
            blockers.append("paper_exchange_rule_preflight:order_filter_violation_count_nonzero")
        if _int(summary.get("quantity_lot_violation_count")):
            blockers.append("paper_exchange_rule_preflight:quantity_lot_violation_count_nonzero")
        if _int(summary.get("current_order_count")) <= 0:
            if summary.get("current_flat_no_order_healthy") is True:
                blockers.append("paper_exchange_rule_preflight:current_flat_waiting_for_order_filter_sample")
            else:
                blockers.append("paper_exchange_rule_preflight:no_current_theoretical_orders")
    elif source_id == "paper_risk_circuit_breaker_drill":
        if _int(summary.get("unexpected_allow_count")):
            blockers.append("paper_risk_circuit_breaker_drill:unexpected_allow_count_nonzero")
    elif source_id == "perpetual_execution_evidence":
        if _int(summary.get("fail_count")):
            blockers.append("perpetual_execution_evidence:fail_count_nonzero")
    elif source_id == "gate_dashboard":
        if str(payload.get("status") or "").lower() not in {"complete", "pass", "passed", "complete_research_only"}:
            blockers.append(f"gate_dashboard:status:{payload.get('status')}")
    return blockers


def _manual_gate(
    *,
    manual_paper_review_approval: Mapping[str, Any],
    operator_envelope: Mapping[str, Any],
    manual_approval_id: str | None,
    approved_initial_principal_usdt: float,
    approved_max_order_notional_usdt: float,
    approved_max_leverage: float,
    approved_max_daily_orders: int,
) -> dict[str, Any]:
    envelope_values = _mapping(operator_envelope.get("values"))
    principal = _positive_override(approved_initial_principal_usdt, envelope_values.get("approved_initial_principal_usdt"))
    order_notional = _positive_override(approved_max_order_notional_usdt, envelope_values.get("approved_max_order_notional_usdt"))
    leverage = _positive_override(approved_max_leverage, envelope_values.get("approved_max_leverage"))
    daily_orders = int(_positive_override(float(approved_max_daily_orders), envelope_values.get("approved_max_daily_orders")))
    approval = bool(manual_approval_id and manual_approval_id.strip()) or (
        manual_paper_review_approval.get("manual_approval_recorded") is True
        and manual_paper_review_approval.get("manual_review_missing_cleared") is True
        and not _list(manual_paper_review_approval.get("blockers"))
    )
    blockers: list[str] = []
    if not approval:
        blockers.append("manual_approval_missing")
    if operator_envelope.get("status") != "recorded_redacted":
        blockers.append("operator_paper_intake_envelope_missing")
        blockers.extend(str(item) for item in _list(operator_envelope.get("blockers")))
    if principal <= 0:
        blockers.append("micro_live_initial_principal_not_approved")
    if order_notional <= 0:
        blockers.append("micro_live_order_notional_not_approved")
    if leverage <= 0:
        blockers.append("micro_live_leverage_not_approved")
    if daily_orders <= 0:
        blockers.append("micro_live_daily_order_limit_not_approved")
    return {
        "manual_approval_required": True,
        "manual_approval_recorded": approval,
        "manual_approval_id": manual_approval_id or str(_nested(manual_paper_review_approval, "reviewed_packet", "sha256") or ""),
        "manual_approval_source": "approval_report" if manual_paper_review_approval.get("manual_approval_recorded") is True else "cli_argument",
        "operator_paper_intake_envelope_recorded": operator_envelope.get("status") == "recorded_redacted",
        "operator_paper_intake_envelope_source": operator_envelope.get("path"),
        "approved_initial_principal_usdt": float(principal),
        "approved_max_order_notional_usdt": float(order_notional),
        "approved_max_leverage": float(leverage),
        "approved_max_daily_orders": int(daily_orders),
        "blockers": sorted(set(blockers)),
    }


def _blockers(
    *,
    matrix: Sequence[Mapping[str, Any]],
    sources: Mapping[str, Mapping[str, Any]],
    manual_gate: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    for row in matrix:
        source_id = row.get("source_id")
        for item in _list(row.get("line_blockers")):
            text = str(item)
            blockers.append(text if text.startswith(f"{source_id}:") else f"{source_id}:{text}")
    blockers.extend(_list(manual_gate.get("blockers")))
    if _mapping(_mapping(sources.get("paper_live_kill_switch_status")).get("payload")).get("status") != "complete_research_only":
        blockers.append("micro_live_preflight_requires_clean_kill_switch_status")
    return sorted(set(str(item) for item in blockers if item))


def _summary(
    *,
    matrix: Sequence[Mapping[str, Any]],
    blockers: Sequence[str],
    sources: Mapping[str, Mapping[str, Any]],
    manual_gate: Mapping[str, Any],
) -> dict[str, Any]:
    observe_summary = _mapping(_mapping(sources["observe_only_health"].get("payload")).get("summary"))
    replay_summary = _mapping(_mapping(sources["paper_runtime_replay"].get("payload")).get("summary"))
    exchange_rule_summary = _mapping(_mapping(sources["paper_exchange_rule_preflight"].get("payload")).get("summary"))
    kill_policy = _mapping(_mapping(sources["paper_live_kill_switch_status"].get("payload")).get("policy_state"))
    return {
        "source_count": len(matrix),
        "missing_source_count": sum(1 for row in matrix if not row.get("present")),
        "failed_source_check_count": sum(1 for row in matrix if row.get("source_decision") != "source_preflight_pass"),
        "upstream_blocker_count": sum(_int(row.get("blocker_count")) for row in matrix),
        "true_safety_flag_count": sum(_int(row.get("true_safety_flag_count")) for row in matrix),
        "blocker_count": len(blockers),
        "observe_only_60d_complete": observe_summary.get("all_lines_target_60d_complete") is True,
        "observe_only_30d_complete": observe_summary.get("all_lines_minimum_30d_complete") is True,
        "paper_runtime_current_simulated_fill_count": _int(replay_summary.get("simulated_fill_count")),
        "paper_runtime_replay_ready": replay_summary.get("paper_runtime_replay_ready") is True,
        "paper_runtime_health_status": replay_summary.get("paper_runtime_health_status") or "unknown",
        "paper_runtime_current_flat_heartbeat_healthy": replay_summary.get("current_flat_heartbeat_healthy") is True,
        "paper_runtime_trade_execution_evidence_available": replay_summary.get("trade_execution_evidence_available") is True,
        "paper_runtime_trade_execution_evidence_pending_reason": replay_summary.get("trade_execution_evidence_pending_reason"),
        "paper_exchange_current_order_sample_status": exchange_rule_summary.get("current_order_sample_status") or "unknown",
        "paper_exchange_current_order_sample_available": exchange_rule_summary.get("current_order_sample_available") is True,
        "paper_exchange_current_flat_no_order_healthy": exchange_rule_summary.get("current_flat_no_order_healthy") is True,
        "paper_exchange_current_order_sample_pending_reason": exchange_rule_summary.get("current_order_sample_pending_reason"),
        "kill_switch_engaged": kill_policy.get("kill_switch_engaged") is True,
        "paper_order_intake_allowed_by_kill_switch": kill_policy.get("paper_order_intake_allowed") is True,
        "manual_approval_required": manual_gate.get("manual_approval_required"),
        "manual_approval_recorded": manual_gate.get("manual_approval_recorded"),
        "operator_paper_intake_envelope_recorded": manual_gate.get("operator_paper_intake_envelope_recorded"),
        "approved_initial_principal_usdt": manual_gate.get("approved_initial_principal_usdt"),
        "approved_max_order_notional_usdt": manual_gate.get("approved_max_order_notional_usdt"),
        "approved_max_leverage": manual_gate.get("approved_max_leverage"),
        "approved_max_daily_orders": manual_gate.get("approved_max_daily_orders"),
        "micro_live_allowed": False,
        "live_unlock_allowed": False,
    }


def _micro_live_envelope(manual_gate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "envelope_status": "not_active_until_manual_approval_and_all_evidence_pass",
        "approved_initial_principal_usdt": manual_gate.get("approved_initial_principal_usdt"),
        "approved_max_order_notional_usdt": manual_gate.get("approved_max_order_notional_usdt"),
        "approved_max_leverage": manual_gate.get("approved_max_leverage"),
        "approved_max_daily_orders": manual_gate.get("approved_max_daily_orders"),
        "observe_only_min_days_required": 60,
        "paper_runtime_clean_days_required": 30,
        "private_stream_reconciliation_required": True,
        "exchange_rule_preflight_required": True,
        "risk_circuit_breaker_drill_required": True,
        "kill_switch_required": True,
        "reduce_only_emergency_required": True,
        "automatic_live_unlock_allowed": False,
    }


def _policy_state(*, blockers: Sequence[str]) -> dict[str, Any]:
    return {
        "fail_closed": True,
        "blocked": bool(blockers),
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "micro_live_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "cancel_only_mode": True,
        "reduce_only_mode": True,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
    }


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "micro_live_preflight_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "micro_live_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "reason": "This report aggregates evidence only and cannot unlock paper/live.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "research_only": True,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "micro_live_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _warnings(blockers: Sequence[str]) -> list[str]:
    warnings = ["btc_micro_live_preflight_no_order_no_broker_no_live_unlock"]
    if blockers:
        warnings.append("micro_live_blocked_until_upstream_evidence_manual_gate_and_size_envelope_are_clean")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_micro_live_preflight_safety_status_v1",
        "status": report.get("status"),
        "decision": report.get("decision"),
        "research_only": True,
        "micro_live_preflight_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "micro_live_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "blockers": list(report.get("blockers", [])),
    }


def _read_source(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        payload = loaded if isinstance(loaded, dict) else {}
    return {"path": _portable_path(path), "present": bool(payload), "payload": payload}


def _true_flag_paths(value: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_prefix = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in BAD_TRUE_FLAGS and child is True:
                paths.append(child_prefix)
            paths.extend(_true_flag_paths(child, child_prefix))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            paths.extend(_true_flag_paths(child, f"{prefix}[{idx}]"))
    return paths


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_matrix_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_id",
        "path",
        "present",
        "status",
        "decision",
        "blocker_count",
        "true_safety_flag_count",
        "ignored_self_reference_blocker_count",
        "source_decision",
        "line_blockers",
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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested(payload: Mapping[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _positive_override(override: float, fallback: Any) -> float:
    override_value = _float(override)
    return override_value if override_value > 0 else _float(fallback)


def _parse_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _secret_like_key_count(value: Any) -> int:
    secret_tokens = ("api_key", "apikey", "secret", "passphrase", "password", "token", "private_key")
    if isinstance(value, Mapping):
        count = 0
        for key, child in value.items():
            key_text = str(key).lower()
            if any(token in key_text for token in secret_tokens):
                count += 1
            count += _secret_like_key_count(child)
        return count
    if isinstance(value, list):
        return sum(_secret_like_key_count(item) for item in value)
    return 0


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
