from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_paper_live_kill_switch_status_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_exchange_runtime/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_live_kill_switch_status_report.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_live_kill_switch_status_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_live_kill_switch_safety_status.json"

DEFAULT_READINESS_REPORT = Path("artifacts/btc_strategy_promotion_readiness/latest/btc_strategy_promotion_readiness_report.json")
DEFAULT_EXCHANGE_RUNTIME_GAP_REPORT = Path("artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_replay_gap_report.json")
DEFAULT_PAPER_RUNTIME_RECONCILIATION_REPORT = Path(
    "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_reconciliation_report.json"
)
DEFAULT_PAPER_EXCHANGE_RULE_PREFLIGHT_REPORT = Path(
    "artifacts/btc_exchange_runtime/latest/btc_paper_exchange_rule_preflight_report.json"
)
DEFAULT_PAPER_RISK_CIRCUIT_BREAKER_DRILL_REPORT = Path(
    "artifacts/btc_exchange_runtime/latest/btc_paper_risk_circuit_breaker_drill_report.json"
)
DEFAULT_PERP_EXECUTION_EVIDENCE_REPORT = Path(
    "artifacts/btc_perpetual_execution_evidence/latest/btc_perpetual_execution_evidence_report.json"
)
DEFAULT_GATE_DASHBOARD_REPORT = Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json")
DEFAULT_MANUAL_PAPER_REVIEW_APPROVAL_REPORT = Path(
    "artifacts/btc_manual_paper_review_approval/latest/btc_manual_paper_review_approval_report.json"
)

BAD_TRUE_FLAGS = {
    "paper_queue_write_allowed",
    "paper_candidate_created",
    "paper_order_intake_allowed",
    "position_increase_allowed",
    "live_unlock_allowed",
    "live_order_allowed",
    "micro_live_allowed",
    "broker_access_allowed",
    "oms_access_allowed",
    "private_endpoint_used",
    "order_endpoint_used",
    "real_order_submitted",
    "strategy_skeleton_generated",
}


def build_btc_paper_live_kill_switch_status(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    readiness_report_path: Path = DEFAULT_READINESS_REPORT,
    exchange_runtime_gap_report_path: Path = DEFAULT_EXCHANGE_RUNTIME_GAP_REPORT,
    paper_runtime_reconciliation_report_path: Path = DEFAULT_PAPER_RUNTIME_RECONCILIATION_REPORT,
    paper_exchange_rule_preflight_report_path: Path = DEFAULT_PAPER_EXCHANGE_RULE_PREFLIGHT_REPORT,
    paper_risk_circuit_breaker_drill_report_path: Path = DEFAULT_PAPER_RISK_CIRCUIT_BREAKER_DRILL_REPORT,
    perp_execution_evidence_report_path: Path = DEFAULT_PERP_EXECUTION_EVIDENCE_REPORT,
    gate_dashboard_report_path: Path = DEFAULT_GATE_DASHBOARD_REPORT,
    manual_paper_review_approval_report_path: Path = DEFAULT_MANUAL_PAPER_REVIEW_APPROVAL_REPORT,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
) -> dict[str, Any]:
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    sources = {
        "strategy_promotion_readiness": _read_source(readiness_report_path),
        "exchange_runtime_gap": _read_source(exchange_runtime_gap_report_path),
        "paper_runtime_reconciliation": _read_source(paper_runtime_reconciliation_report_path),
        "paper_exchange_rule_preflight": _read_source(paper_exchange_rule_preflight_report_path),
        "paper_risk_circuit_breaker_drill": _read_source(paper_risk_circuit_breaker_drill_report_path),
        "perpetual_execution_evidence": _read_source(perp_execution_evidence_report_path),
        "gate_dashboard": _read_source(gate_dashboard_report_path),
        "manual_paper_review_approval": _read_source(manual_paper_review_approval_report_path),
    }
    checks = _checks(sources)
    blockers = _blockers(checks)
    policy = _policy_state(blockers=blockers, manual_approval_recorded=_manual_approval_recorded(sources))
    clearance = _clearance_checklist(blockers=blockers, policy=policy)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "aggregation_batch_id": aggregation_batch_id or "",
        "status": "fail_closed_research_only",
        "decision": "btc_paper_live_kill_switch_engaged_fail_closed_no_paper_no_live",
        "scope": "btc_paper_live_fail_closed_status_no_order_no_broker",
        "code_commit": _git_commit(),
        "input": {
            "strategy_promotion_readiness": _portable_path(readiness_report_path),
            "exchange_runtime_gap": _portable_path(exchange_runtime_gap_report_path),
            "paper_runtime_reconciliation": _portable_path(paper_runtime_reconciliation_report_path),
            "paper_exchange_rule_preflight": _portable_path(paper_exchange_rule_preflight_report_path),
            "paper_risk_circuit_breaker_drill": _portable_path(paper_risk_circuit_breaker_drill_report_path),
            "perpetual_execution_evidence": _portable_path(perp_execution_evidence_report_path),
            "gate_dashboard": _portable_path(gate_dashboard_report_path),
            "manual_paper_review_approval": _portable_path(manual_paper_review_approval_report_path),
        },
        "summary": _summary(checks=checks, blockers=blockers, policy=policy),
        "source_status": {name: _source_status(source) for name, source in sources.items()},
        "checks": checks,
        "clearance_checklist": clearance,
        "policy_state": policy,
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(blockers),
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(report_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_text(markdown_path, render_btc_paper_live_kill_switch_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_paper_live_kill_switch_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    policy = _mapping(report.get("policy_state"))
    lines = [
        "# BTC paper/live 熔断状态总表",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- kill-switch 已拉起：`{policy.get('kill_switch_engaged')}`",
        f"- cancel-only 模式：`{policy.get('cancel_only_mode')}`",
        f"- paper 接单允许：`{policy.get('paper_order_intake_allowed')}`",
        f"- 加仓允许：`{policy.get('position_increase_allowed')}`",
        f"- micro-live 允许：`{policy.get('micro_live_allowed')}`",
        f"- 手工审批已记录：`{policy.get('manual_approval_recorded')}`",
        f"- 输入报告数量：`{summary.get('source_count')}`，缺失：`{summary.get('missing_source_count')}`",
        f"- 阻断项数量：`{summary.get('blocker_count')}`",
        "",
        "## 当前含义",
        "",
        "这张表只做安全汇总：任一上游证据包阻塞、任一 paper/live 安全旗标异常，或者没有人工批准记录时，都默认不能接 paper 单，不能加仓，不能 micro-live。",
        "",
        "## 检查项",
        "",
        "| 检查 | 状态 | 依据 |",
        "|---|---|---|",
    ]
    for check in report.get("checks", []):
        lines.append(f"| `{check.get('check_id')}` | `{check.get('status')}` | {check.get('evidence')} |")
    lines.extend(["", "## 主要阻断项", ""])
    blockers = list(report.get("blockers", []))
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers[:80])
        if len(blockers) > 80:
            lines.append(f"- ... 其余 {len(blockers) - 80} 项见 JSON")
    else:
        lines.append("- 无")
    clearance = _mapping(report.get("clearance_checklist"))
    lines.extend(
        [
            "",
            "## 解除条件 / Runbook",
            "",
            f"- 结论：`{clearance.get('status')}`",
            f"- cancel-only 验证：`{_nested_bool(clearance, 'state_verification', 'cancel_only_verified')}`",
            f"- reduce-only 验证：`{_nested_bool(clearance, 'state_verification', 'reduce_only_verified')}`",
            f"- paper-order-intake 关闭验证：`{_nested_bool(clearance, 'state_verification', 'paper_order_intake_disabled_verified')}`",
            f"- reset drill 边界：`{_nested_text(clearance, 'reset_drill_boundary', 'scope')}`",
            "",
            "| 类别 | 数量 | 示例 |",
            "|---|---:|---|",
        ]
    )
    for key, label in (
        ("manual_confirmation_required", "必须人工确认"),
        ("rerun_reports_required", "必须重跑报告"),
        ("waiting_for_samples_required", "必须等待样本"),
        ("data_backfill_required", "必须补数据"),
    ):
        items = _list(_mapping(clearance).get(key))
        sample = "; ".join(str(item) for item in items[:3]) if items else "无"
        lines.append(f"| {label} | {len(items)} | {sample} |")
    clearance_classes = _mapping(clearance.get("blocker_clearance"))
    class_counts = _mapping(clearance_classes.get("counts"))
    lines.extend(
        [
            "",
            "## Blocker Clearance Classes",
            "",
            "| class | count | note |",
            "|---|---:|---|",
            f"| clearable | {class_counts.get('clearable', 0)} | rebuild/manual/template work can clear these, but no auto paper/live |",
            f"| wait_only | {class_counts.get('wait_only', 0)} | data wait, current runtime sample wait, or forward observation wait |",
            f"| non_clearable | {class_counts.get('non_clearable', 0)} | safety/live/order violations require governance or code fix |",
            f"| data_wait | {class_counts.get('data_wait', 0)} | market/runtime evidence still accumulating |",
            f"| runtime_current_sample | {class_counts.get('runtime_current_sample', 0)} | wait for current observe-only non-flat evidence |",
            f"| strategy_forward_gap | {class_counts.get('strategy_forward_gap', 0)} | strategy forward/holdout evidence still pending |",
            "",
            f"- auto_unlock_after_clearance_allowed: `{clearance.get('auto_unlock_after_clearance_allowed')}`",
        ]
    )
    lines.extend(
        [
            "",
            "本报告不写 paper 队列，不生成策略骨架，不连接 broker/OMS，不使用 private/order endpoint，不解锁 live。",
        ]
    )
    return "\n".join(lines) + "\n"


def _checks(sources: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for name, source in sources.items():
        payload = _mapping(source.get("payload"))
        true_flags = _true_flag_paths(payload)
        blockers = _source_blockers(name, payload)
        checks.append(
            {
                "check_id": f"{name}_present",
                "status": "pass" if source.get("present") else "fail",
                "evidence": source.get("path"),
                "blockers": [] if source.get("present") else [f"missing_input:{name}"],
            }
        )
        checks.append(
            {
                "check_id": f"{name}_status_not_blocked",
                "status": "pass" if _source_is_ready_enough_for_status_check(name, payload) else "fail",
                "evidence": f"status={payload.get('status')} decision={payload.get('decision')}",
                "blockers": blockers,
            }
        )
        checks.append(
            {
                "check_id": f"{name}_paper_live_flags_false",
                "status": "pass" if not true_flags else "fail",
                "evidence": f"true_flag_count={len(true_flags)}",
                "blockers": [f"{name}:true_flag:{path}" for path in true_flags],
            }
        )
    return checks


def _source_blockers(name: str, payload: Mapping[str, Any]) -> list[str]:
    if not payload:
        return [f"missing_input:{name}"]
    blockers: list[str] = []
    status = str(payload.get("status") or "").lower()
    decision = str(payload.get("decision") or "").lower()
    source_blockers = _list(payload.get("blockers"))
    if name == "paper_runtime_reconciliation":
        summary = _mapping(payload.get("summary"))
        if summary.get("paper_runtime_reconciliation_passed") is not True:
            blockers.append(f"{name}:paper_runtime_reconciliation_not_passed")
        if _int(summary.get("violation_count")):
            blockers.append(f"{name}:violation_count_nonzero")
    elif name == "gate_dashboard":
        if status not in {"pass", "passed", "complete", "complete_research_only"}:
            blockers.append(f"{name}:status:{payload.get('status')}")
    elif name == "manual_paper_review_approval":
        if payload.get("manual_approval_recorded") is not True:
            blockers.append(f"{name}:manual_approval_not_recorded")
        if payload.get("manual_review_missing_cleared") is not True:
            blockers.append(f"{name}:manual_review_missing_not_cleared")
    else:
        if any(token in status for token in ["blocked", "incomplete", "fail"]):
            blockers.append(f"{name}:status:{payload.get('status')}")
        if "fail_closed" in decision or "blocked" in decision or "incomplete" in decision:
            blockers.append(f"{name}:decision:{payload.get('decision')}")
    blockers.extend(f"{name}:source_blocker:{item}" for item in source_blockers)
    return sorted(set(blockers))


def _source_is_ready_enough_for_status_check(name: str, payload: Mapping[str, Any]) -> bool:
    return not _source_blockers(name, payload)


def _blockers(checks: Sequence[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for check in checks:
        if check.get("status") != "pass":
            blockers.extend(str(item) for item in _list(check.get("blockers")))
    return sorted(set(blockers))


def _policy_state(*, blockers: Sequence[str], manual_approval_recorded: bool) -> dict[str, Any]:
    return {
        "kill_switch_engaged": True,
        "kill_switch_reason": "blockers_or_manual_gate_missing" if blockers else "manual_gate_required",
        "cancel_only_mode": True,
        "reduce_only_mode": True,
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "micro_live_allowed": False,
        "live_order_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "manual_approval_required": True,
        "manual_approval_recorded": manual_approval_recorded,
        "manual_approval_note": "No paper/live permission can be inferred from research-only artifacts.",
    }


def _manual_approval_recorded(sources: Mapping[str, Mapping[str, Any]]) -> bool:
    payload = _mapping(_mapping(sources.get("manual_paper_review_approval")).get("payload"))
    if payload.get("manual_approval_recorded") is not True:
        return False
    if _list(payload.get("blockers")):
        return False
    if payload.get("paper_queue_write_allowed") is True or payload.get("live_unlock_allowed") is True:
        return False
    return True


def _clearance_checklist(*, blockers: Sequence[str], policy: Mapping[str, Any]) -> dict[str, Any]:
    manual_items = []
    rerun_items = []
    waiting_items = []
    data_items = []
    for blocker in blockers:
        text = str(blocker)
        lower = text.lower()
        if any(token in lower for token in ("manual", "approval", "operator", "attestation")):
            manual_items.append(text)
        if any(token in lower for token in ("status:", "decision:", "reconciliation", "preflight", "runtime_gap", "exchange_runtime")):
            rerun_items.append(text)
        if any(token in lower for token in ("current_flat", "trade_sample", "order_sample", "simulated_fill", "no_simulated")):
            waiting_items.append(text)
        if any(token in lower for token in ("depth", "coverage", "slippage", "mark", "index", "funding", "liquidation")):
            data_items.append(text)
    clearance_classes = _blocker_clearance_classes(blockers)
    state_verification = {
        "cancel_only_verified": policy.get("cancel_only_mode") is True,
        "reduce_only_verified": policy.get("reduce_only_mode") is True,
        "paper_order_intake_disabled_verified": policy.get("paper_order_intake_allowed") is False,
        "position_increase_disabled_verified": policy.get("position_increase_allowed") is False,
        "live_unlock_disabled_verified": policy.get("live_unlock_allowed") is False,
    }
    return {
        "schema_version": "btc_kill_switch_clearance_checklist_v1",
        "status": "blocked_clearance_required" if blockers else "manual_clearance_required",
        "manual_confirmation_required": _dedupe(manual_items or ["manual_approval_required_before_any_paper_intake"]),
        "rerun_reports_required": _dedupe(rerun_items),
        "waiting_for_samples_required": _dedupe(waiting_items),
        "data_backfill_required": _dedupe(data_items),
        "blocker_clearance": clearance_classes,
        "clearable_blockers": clearance_classes["clearable"],
        "wait_only_blockers": clearance_classes["wait_only"],
        "non_clearable_blockers": clearance_classes["non_clearable"],
        "auto_unlock_after_clearance_allowed": False,
        "state_verification": state_verification,
        "reset_drill_boundary": {
            "scope": "paper_intake_clearance_only",
            "can_clear_paper_intake_blocker": True,
            "can_clear_live_blocker": False,
            "live_remains_frozen_after_reset_drill": True,
            "requires_manual_review_after_reset": True,
        },
        "next_action_by_category": {
            "manual_confirmation_required": "人工确认 approval、attestation、operator packet；不得填写真实 key。",
            "rerun_reports_required": "按聚合链重跑 runtime/preflight/reconciliation/gate 报告。",
            "waiting_for_samples_required": "等待 observe-only 非 flat 样本产生 theoretical order/fill/replay 证据。",
            "data_backfill_required": "继续补 depth/mark/index/slippage/funding/liquidation 覆盖。",
        },
    }


def _blocker_clearance_classes(blockers: Sequence[str]) -> dict[str, Any]:
    clearable: list[str] = []
    wait_only: list[str] = []
    non_clearable: list[str] = []
    data_wait: list[str] = []
    runtime_current_sample: list[str] = []
    strategy_forward_gap: list[str] = []
    manual_approval: list[str] = []
    for blocker in blockers:
        text = str(blocker)
        lower = text.lower()
        is_safety_or_live = any(
            token in lower
            for token in (
                ":true_flag:",
                "live_unlock",
                "live_order",
                "broker_access",
                "oms_access",
                "private_endpoint",
                "order_endpoint",
                "real_order",
                "safety_violation",
            )
        )
        is_data_wait = any(
            token in lower
            for token in (
                "depth",
                "coverage",
                "slippage",
                "mark",
                "index",
                "funding",
                "liquidation",
                "fill_mapping",
                "no_gate_eligible",
                "gate_fill",
            )
        )
        is_runtime_sample = any(
            token in lower
            for token in (
                "current_flat",
                "trade_sample",
                "order_sample",
                "current_non_flat",
                "no_simulated",
                "simulated_fill",
                "runtime_contract_local_fixture_only",
                "public_or_paper_runtime_layer_required",
            )
        )
        is_strategy_forward = any(
            token in lower
            for token in ("observe", "forward", "30d", "60d", "holdout", "strategy_promotion_readiness")
        )
        is_manual = any(token in lower for token in ("manual", "approval", "attestation", "operator"))
        is_rebuildable = any(
            token in lower
            for token in (
                "artifact_freshness",
                "stale",
                "status:",
                "decision:",
                "reconciliation",
                "preflight",
                "runtime_gap",
                "exchange_runtime",
                "missing_input",
            )
        )
        if is_safety_or_live:
            non_clearable.append(text)
        elif is_data_wait or is_runtime_sample or is_strategy_forward:
            wait_only.append(text)
        elif is_manual or is_rebuildable:
            clearable.append(text)
        else:
            clearable.append(text)
        if is_data_wait:
            data_wait.append(text)
        if is_runtime_sample:
            runtime_current_sample.append(text)
        if is_strategy_forward:
            strategy_forward_gap.append(text)
        if is_manual:
            manual_approval.append(text)
    non_clearable_after_all_clearance = [
        "paper_queue_write_allowed_remains_false_until_separate_operator_enablement",
        "live_unlock_allowed_remains_false_until_separate_live_governance",
        "broker_order_private_endpoints_remain_disabled_by_this_report",
    ]
    return {
        "schema_version": "btc_kill_switch_blocker_clearance_classes_v1",
        "clearable": _dedupe(clearable),
        "wait_only": _dedupe(wait_only),
        "non_clearable": _dedupe(non_clearable),
        "data_wait": _dedupe(data_wait),
        "manual_approval": _dedupe(manual_approval),
        "runtime_current_sample": _dedupe(runtime_current_sample),
        "strategy_forward_gap": _dedupe(strategy_forward_gap),
        "non_clearable_after_all_clearance": non_clearable_after_all_clearance,
        "counts": {
            "clearable": len(_dedupe(clearable)),
            "wait_only": len(_dedupe(wait_only)),
            "non_clearable": len(_dedupe(non_clearable)),
            "data_wait": len(_dedupe(data_wait)),
            "manual_approval": len(_dedupe(manual_approval)),
            "runtime_current_sample": len(_dedupe(runtime_current_sample)),
            "strategy_forward_gap": len(_dedupe(strategy_forward_gap)),
        },
    }


def _summary(*, checks: Sequence[Mapping[str, Any]], blockers: Sequence[str], policy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_count": sum(1 for check in checks if str(check.get("check_id", "")).endswith("_present")),
        "missing_source_count": sum(
            1
            for check in checks
            if str(check.get("check_id", "")).endswith("_present") and check.get("status") != "pass"
        ),
        "check_count": len(checks),
        "check_fail_count": sum(1 for check in checks if check.get("status") != "pass"),
        "blocker_count": len(blockers),
        "true_safety_flag_blocker_count": sum(1 for item in blockers if ":true_flag:" in item),
        "manual_approval_required": policy.get("manual_approval_required"),
        "manual_approval_recorded": policy.get("manual_approval_recorded"),
        "kill_switch_engaged": policy.get("kill_switch_engaged"),
        "cancel_only_mode": policy.get("cancel_only_mode"),
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "micro_live_allowed": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _source_status(source: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(source.get("payload"))
    true_flags = _true_flag_paths(payload)
    return {
        "path": source.get("path"),
        "present": bool(source.get("present")),
        "status": payload.get("status"),
        "decision": payload.get("decision"),
        "blocker_count": len(_list(payload.get("blockers"))),
        "true_safety_flag_count": len(true_flags),
        "true_safety_flags": true_flags[:40],
    }


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "reason": "Kill-switch status is fail-closed and cannot promote paper/live by itself.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "research_only": True,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "paper_candidate_created": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _warnings(blockers: Sequence[str]) -> list[str]:
    warnings = [
        "btc_paper_live_kill_switch_research_only_no_order_no_broker",
        "manual_approval_required_even_if_all_artifacts_are_clean",
    ]
    if blockers:
        warnings.append("fail_closed_until_all_blockers_and_manual_gate_are_cleared")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    policy = _mapping(report.get("policy_state"))
    return {
        "schema_version": "btc_paper_live_kill_switch_safety_status_v1",
        "status": report.get("status"),
        "decision": report.get("decision"),
        "kill_switch_engaged": True,
        "cancel_only_mode": True,
        "reduce_only_mode": True,
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
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
        "manual_approval_required": policy.get("manual_approval_required"),
        "manual_approval_recorded": policy.get("manual_approval_recorded") is True,
        "blockers": list(report.get("blockers", [])),
    }


def _read_source(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        payload = data if isinstance(data, dict) else {}
    return {"path": _portable_path(path), "present": bool(payload), "payload": payload}


def _true_flag_paths(value: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_str = str(key)
            child_prefix = f"{prefix}.{key_str}" if prefix else key_str
            if key_str in BAD_TRUE_FLAGS and child is True:
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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _nested_bool(payload: Mapping[str, Any], *keys: str) -> bool | None:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current if isinstance(current, bool) else None


def _nested_text(payload: Mapping[str, Any], *keys: str) -> str:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return ""
        current = current.get(key)
    return str(current or "")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
