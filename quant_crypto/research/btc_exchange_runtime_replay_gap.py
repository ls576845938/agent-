from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_exchange_runtime_replay_gap_report_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_exchange_runtime/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_exchange_runtime_replay_gap_report.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_exchange_runtime_replay_gap_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_RUNTIME_CONTRACT_PATH = Path("artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_contract.json")
DEFAULT_PUBLIC_RUNTIME_DRY_PROBE_PATH = Path(
    "artifacts/btc_exchange_runtime/latest/btc_exchange_public_runtime_dry_probe_report.json"
)
DEFAULT_PUBLIC_WS_COVERAGE_PATH = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_l2_capture_coverage_report.json")
DEFAULT_PAPER_RUNTIME_REPLAY_PATH = Path("artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_report.json")
DEFAULT_PAPER_RUNTIME_DRILL_PATH = Path("artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_drill_report.json")
DEFAULT_PAPER_RUNTIME_FIXTURE_DRILL_PATH = Path(
    "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_fixture_drill_report.json"
)
DEFAULT_PAPER_RUNTIME_RECONCILIATION_PATH = Path(
    "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_reconciliation_report.json"
)


def build_btc_exchange_runtime_replay_gap_report(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    runtime_contract_path: Path = DEFAULT_RUNTIME_CONTRACT_PATH,
    public_runtime_dry_probe_path: Path = DEFAULT_PUBLIC_RUNTIME_DRY_PROBE_PATH,
    public_ws_coverage_path: Path = DEFAULT_PUBLIC_WS_COVERAGE_PATH,
    paper_runtime_replay_path: Path = DEFAULT_PAPER_RUNTIME_REPLAY_PATH,
    paper_runtime_drill_path: Path = DEFAULT_PAPER_RUNTIME_DRILL_PATH,
    paper_runtime_fixture_drill_path: Path = DEFAULT_PAPER_RUNTIME_FIXTURE_DRILL_PATH,
    paper_runtime_reconciliation_path: Path = DEFAULT_PAPER_RUNTIME_RECONCILIATION_PATH,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    runtime = _read_json(runtime_contract_path)
    public_runtime_dry_probe = _read_json(public_runtime_dry_probe_path)
    coverage = _read_json(public_ws_coverage_path)
    paper_replay = _read_json(paper_runtime_replay_path)
    paper_drill = _read_json(paper_runtime_drill_path)
    paper_fixture_drill = _read_json(paper_runtime_fixture_drill_path)
    paper_reconciliation = _read_json(paper_runtime_reconciliation_path)
    latency_model = _latency_model_boundary(runtime=runtime, coverage=coverage, paper_replay=paper_replay)
    queue_model = _queue_model_boundary(coverage=coverage, paper_replay=paper_replay)

    gap = _gap_analysis(
        runtime=runtime,
        public_runtime_dry_probe=public_runtime_dry_probe,
        coverage=coverage,
        paper_replay=paper_replay,
        paper_drill=paper_drill,
        paper_fixture_drill=paper_fixture_drill,
        paper_reconciliation=paper_reconciliation,
        paper_runtime_replay_path=paper_runtime_replay_path,
        paper_runtime_drill_path=paper_runtime_drill_path,
        paper_runtime_fixture_drill_path=paper_runtime_fixture_drill_path,
        paper_runtime_reconciliation_path=paper_runtime_reconciliation_path,
        latency_model=latency_model,
        queue_model=queue_model,
    )
    evidence_layers = _evidence_layers(gap)
    runtime_capability_layers = _runtime_capability_layers(
        runtime=runtime,
        public_runtime_dry_probe=public_runtime_dry_probe,
        coverage=coverage,
        gap=gap,
    )
    blockers = _blockers(
        runtime=runtime,
        public_runtime_dry_probe=public_runtime_dry_probe,
        coverage=coverage,
        paper_replay=paper_replay,
        gap=gap,
        paper_runtime_replay_path=paper_runtime_replay_path,
    )
    decision = (
        "runtime_replay_gap_incomplete_fail_closed_no_paper_no_live"
        if blockers
        else "runtime_replay_ready_for_manual_review_research_only_no_auto_paper_no_live"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "aggregation_batch_id": aggregation_batch_id or "",
        "status": "incomplete_research_only" if blockers else "complete_research_only",
        "decision": decision,
        "scope": "btc_exchange_runtime_public_ws_and_paper_replay_gap_no_order_no_broker",
        "code_commit": _git_commit(),
        "input": {
            "runtime_contract_path": _portable_path(runtime_contract_path),
            "public_runtime_dry_probe_path": _portable_path(public_runtime_dry_probe_path),
            "public_ws_coverage_path": _portable_path(public_ws_coverage_path),
            "paper_runtime_replay_path": _portable_path(paper_runtime_replay_path),
            "paper_runtime_drill_path": _portable_path(paper_runtime_drill_path),
            "paper_runtime_fixture_drill_path": _portable_path(paper_runtime_fixture_drill_path),
            "paper_runtime_reconciliation_path": _portable_path(paper_runtime_reconciliation_path),
        },
        "runtime_contract": _runtime_contract_summary(runtime),
        "public_runtime_dry_probe": _public_runtime_dry_probe_summary(public_runtime_dry_probe, public_runtime_dry_probe_path),
        "public_market_replay": _public_coverage_summary(coverage),
        "paper_runtime_replay": _paper_replay_summary(paper_replay, paper_runtime_replay_path),
        "paper_runtime_drill": _paper_drill_summary(paper_drill, paper_runtime_drill_path),
        "paper_runtime_reconciliation": _paper_reconciliation_summary(
            paper_reconciliation,
            paper_runtime_reconciliation_path,
        ),
        "latency_model": latency_model,
        "queue_model": queue_model,
        "gap_analysis": gap,
        "evidence_layers": evidence_layers,
        "runtime_capability_layers": runtime_capability_layers,
        "summary": _summary(gap=gap, blockers=blockers, evidence_layers=evidence_layers),
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(blockers=blockers, gap=gap),
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(report_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_text(markdown_path, render_btc_exchange_runtime_replay_gap_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_exchange_runtime_replay_gap_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    gap = report.get("gap_analysis", {})
    public = report.get("public_market_replay", {})
    gate = report.get("gate", {})
    latency = _mapping(report.get("latency_model"))
    queue = _mapping(report.get("queue_model"))
    layers = _mapping(report.get("evidence_layers"))
    fixture_layer = _mapping(layers.get("fixture_capability"))
    historical_layer = _mapping(layers.get("historical_drill"))
    current_layer = _mapping(layers.get("current_observe_only_gate_evidence"))
    promotion_rule = _mapping(layers.get("promotion_rule"))
    runtime_layers = _mapping(report.get("runtime_capability_layers"))
    public_runtime_layer = _mapping(runtime_layers.get("public_runtime_dry_probe"))
    paper_private_layer = _mapping(runtime_layers.get("paper_private_order_simulated_entry"))
    lines = [
        "# BTC exchange runtime replay 缺口报告",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 当前 runtime 是否仍是模拟探针：`{gap.get('runtime_contract_is_simulated_probe')}`",
        f"- runtime effective layer：`{gap.get('runtime_contract_effective_layer')}`",
        f"- public runtime dry probe passed：`{gap.get('public_runtime_dry_probe_passed')}`",
        f"- 公共 WS replay 序列是否就绪：`{gap.get('public_ws_replay_sequence_ready')}`",
        f"- 公共 WS 覆盖合约是否满足：`{gap.get('public_ws_coverage_contract_satisfied')}`",
        f"- 执行延迟模型是否就绪：`{gap.get('execution_latency_model_ready')}`",
        f"- 队列位置模型是否就绪：`{gap.get('queue_model_ready')}`",
        f"- latency model 状态：`{latency.get('status')}` / blocker_type=`{latency.get('gate_blocker_type')}`",
        f"- queue model 状态：`{queue.get('status')}` / blocker_type=`{queue.get('gate_blocker_type')}`",
        f"- paper runtime replay 是否存在：`{gap.get('paper_runtime_replay_ready')}`",
        f"- public runtime dry probe：`{public_runtime_layer.get('status')}`",
        f"- paper/private/order 入口：`{paper_private_layer.get('status')}`",
        f"- blocker 数：`{summary.get('blocker_count')}`",
        f"- paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- live 解锁：`{gate.get('live_unlock_allowed')}`",
        "",
        "## Evidence Layers",
        "",
        f"- fixture_capability: status=`{fixture_layer.get('status')}`, passed=`{fixture_layer.get('passed')}`, paper_gate_eligible=`{fixture_layer.get('paper_gate_eligible')}`",
        f"- historical_drill: status=`{historical_layer.get('status')}`, passed=`{historical_layer.get('passed')}`, paper_gate_eligible=`{historical_layer.get('paper_gate_eligible')}`",
        f"- current_observe_only_gate_evidence: status=`{current_layer.get('status')}`, passed=`{current_layer.get('passed')}`, paper_gate_eligible=`{current_layer.get('paper_gate_eligible')}`, pending_reason=`{current_layer.get('pending_reason')}`",
        f"- paper gate rule: may_consider_only=`{promotion_rule.get('paper_gate_may_consider_only_layer')}`, fixture_or_drill_cannot_satisfy_gate=`{promotion_rule.get('fixture_or_drill_cannot_satisfy_gate')}`",
        "",
        "## 现在已有的东西",
        "",
        f"- 公共 WS/L2 已验证 session：`{public.get('verified_public_session_count')}`",
        f"- 总捕获秒数：`{public.get('total_capture_duration_seconds')}`",
        f"- 事件历史天数：`{public.get('total_event_ledger_history_days')}`",
        f"- 日历跨度天数：`{public.get('calendar_span_days')}`",
        f"- replay sequence ready session：`{public.get('replay_sequence_ready_session_count')}`",
        f"- resync policy ready session：`{public.get('resync_policy_ready_session_count')}`",
        "",
        "## 不能放行的原因",
        "",
        "- 公共行情 replay 只能证明市场数据序列和断线重建的一部分，不能证明真实订单延迟、撮合队列位置或 paper fill 行为。",
        "- runtime 现在按三层记录：local deterministic fixture、public-runtime dry probe、paper/private/order simulated entry。",
        "- local fixture / historical drill 只能证明本地链路，不能替代 current observe-only gate evidence。",
        "- 30 天级别的 WS/L2 历史覆盖仍不足，不能把几段短捕获包装成执行层证据。",
        "",
        "本报告只做 research-only 缺口审计，不写 paper 队列，不接 broker/OMS，不使用 private/order endpoint，不解锁 live。",
    ]
    return "\n".join(lines) + "\n"


def _latency_model_boundary(
    *,
    runtime: Mapping[str, Any],
    coverage: Mapping[str, Any],
    paper_replay: Mapping[str, Any],
) -> dict[str, Any]:
    validation = _mapping(coverage.get("validation"))
    coverage_ready = bool(coverage.get("execution_latency_model_ready") or validation.get("execution_latency_model_ready"))
    paper_summary = _mapping(paper_replay.get("summary"))
    simulated_fill_count = _int(paper_summary.get("simulated_fill_count"))
    real_order_latency_sample_count = 0
    schema = {
        "decision_time_utc": "strategy decision timestamp from completed bar",
        "send_time_utc": "paper/theoretical send timestamp; real order endpoint not used",
        "ack_time_utc": "exchange ack timestamp; unavailable without private/order runtime",
        "fill_time_utc": "simulated or observed fill timestamp",
        "clock_offset_ms": "server time offset diagnostic",
    }
    if coverage_ready:
        status = "ready_public_proxy_research_only"
        gate_blocker_type = "not_applicable"
        blockers: list[str] = []
    else:
        status = "data_insufficient_no_order_latency_samples"
        gate_blocker_type = "data_insufficient"
        blockers = ["latency_model:data_insufficient_no_current_order_latency_samples"]
    return {
        "schema_version": "btc_execution_latency_model_artifact_v1",
        "status": status,
        "gate_blocker_type": gate_blocker_type,
        "field_schema": schema,
        "sample_counts": {
            "simulated_fill_count": simulated_fill_count,
            "real_order_latency_sample_count": real_order_latency_sample_count,
            "public_ws_session_count": _int(_mapping(coverage.get("coverage_totals")).get("verified_public_session_count")),
        },
        "boundaries": {
            "public_l2_can_estimate_execution_difficulty": True,
            "public_l2_is_not_real_order_latency": True,
            "private_or_order_endpoint_used": bool(runtime.get("private_endpoint_used") or runtime.get("order_endpoint_used")),
            "paper_gate_evidence": False,
        },
        "lower_upper_model": {
            "lower_bound_ms": 0,
            "upper_bound_ms": None,
            "reason": "real send/ack/fill latency requires current observe-only order sample or private/order runtime evidence",
        },
        "blockers": blockers,
    }


def _queue_model_boundary(*, coverage: Mapping[str, Any], paper_replay: Mapping[str, Any]) -> dict[str, Any]:
    validation = _mapping(coverage.get("validation"))
    coverage_ready = bool(coverage.get("queue_model_ready") or validation.get("queue_model_ready"))
    paper_summary = _mapping(paper_replay.get("summary"))
    gate_eligible_count = _int(paper_summary.get("gate_eligible_current_capture_count"))
    schema = {
        "visible_depth": "public L2 levels available at or before decision/fill time",
        "order_size": "theoretical order notional and quantity",
        "level_consumption": "estimated L2 levels consumed by order size",
        "estimated_queue_position": "diagnostic public L2 proxy; not real exchange queue priority",
    }
    if coverage_ready:
        status = "ready_public_l2_proxy_research_only"
        gate_blocker_type = "not_applicable"
        blockers: list[str] = []
    else:
        status = "data_insufficient_public_l2_only_no_order_queue_samples"
        gate_blocker_type = "data_insufficient"
        blockers = ["queue_model:data_insufficient_public_l2_only_no_order_queue_samples"]
    return {
        "schema_version": "btc_queue_model_artifact_v1",
        "status": status,
        "gate_blocker_type": gate_blocker_type,
        "field_schema": schema,
        "sample_counts": {
            "gate_eligible_current_capture_count": gate_eligible_count,
            "public_ws_session_count": _int(_mapping(coverage.get("coverage_totals")).get("verified_public_session_count")),
            "real_queue_position_sample_count": 0,
        },
        "boundaries": {
            "public_l2_can_estimate_execution_difficulty": True,
            "public_l2_cannot_observe_real_exchange_queue_position": True,
            "paper_gate_evidence": False,
        },
        "lower_upper_model": {
            "lower_bound_queue_position": 0,
            "upper_bound_queue_position": None,
            "reason": "public depth lacks account/order priority and cancellation dynamics",
        },
        "blockers": blockers,
    }


def _gap_analysis(
    *,
    runtime: Mapping[str, Any],
    public_runtime_dry_probe: Mapping[str, Any],
    coverage: Mapping[str, Any],
    paper_replay: Mapping[str, Any],
    paper_drill: Mapping[str, Any],
    paper_fixture_drill: Mapping[str, Any],
    paper_reconciliation: Mapping[str, Any],
    paper_runtime_replay_path: Path,
    paper_runtime_drill_path: Path,
    paper_runtime_fixture_drill_path: Path,
    paper_runtime_reconciliation_path: Path,
    latency_model: Mapping[str, Any],
    queue_model: Mapping[str, Any],
) -> dict[str, Any]:
    runtime_notes = runtime.get("notes", {}) if isinstance(runtime.get("notes"), Mapping) else {}
    public_runtime_passed = _public_runtime_dry_probe_passed(public_runtime_dry_probe)
    local_contract_is_simulated = runtime_notes.get("evidence_type") == "simulated_contract_probe"
    validation = coverage.get("validation", {}) if isinstance(coverage.get("validation"), Mapping) else {}
    totals = coverage.get("coverage_totals", {}) if isinstance(coverage.get("coverage_totals"), Mapping) else {}
    paper_replay_summary = _mapping(paper_replay.get("summary"))
    paper_drill_summary = _mapping(paper_drill.get("summary"))
    paper_fixture_summary = _mapping(paper_fixture_drill.get("summary"))
    paper_reconciliation_summary = _mapping(paper_reconciliation.get("summary"))
    return {
        "runtime_contract_present": bool(runtime),
        "runtime_contract_status_complete": runtime.get("status") == "complete",
        "runtime_contract_decision": runtime.get("decision"),
        "runtime_contract_evidence_type": runtime_notes.get("evidence_type"),
        "runtime_local_contract_is_simulated_probe": local_contract_is_simulated,
        "runtime_contract_is_simulated_probe": local_contract_is_simulated and not public_runtime_passed,
        "runtime_contract_effective_layer": (
            "public_runtime_dry_probe_verified" if public_runtime_passed else str(runtime_notes.get("evidence_type") or "")
        ),
        "runtime_contract_local_fixture_only": local_contract_is_simulated and not public_runtime_passed,
        "public_runtime_dry_probe_present": bool(public_runtime_dry_probe),
        "public_runtime_dry_probe_passed": public_runtime_passed,
        "public_runtime_dry_probe_status": public_runtime_dry_probe.get("status"),
        "public_runtime_dry_probe_decision": public_runtime_dry_probe.get("decision"),
        "public_runtime_dry_probe_blockers": public_runtime_dry_probe.get("blockers", []),
        "public_runtime_server_time_verified": _nested(public_runtime_dry_probe, "runtime_layer", "server_time_verified") is True,
        "public_runtime_symbol_rules_visible": _nested(public_runtime_dry_probe, "runtime_layer", "symbol_rules_visible") is True,
        "public_runtime_mark_price_available": _nested(public_runtime_dry_probe, "runtime_layer", "mark_price_available") is True,
        "public_runtime_index_price_available": _nested(public_runtime_dry_probe, "runtime_layer", "index_price_available") is True,
        "public_runtime_funding_available": _nested(public_runtime_dry_probe, "runtime_layer", "funding_available") is True,
        "public_runtime_public_ws_replay_verified": _nested(public_runtime_dry_probe, "runtime_layer", "public_ws_replay_verified") is True,
        "runtime_contract_private_endpoint_used": bool(runtime.get("private_endpoint_used") or runtime_notes.get("private_endpoint_used")),
        "runtime_contract_order_endpoint_used": bool(runtime.get("order_endpoint_used") or runtime_notes.get("order_endpoint_used")),
        "public_ws_coverage_present": bool(coverage),
        "public_ws_coverage_contract_satisfied": bool(coverage.get("coverage_contract_satisfied") or validation.get("coverage_contract_satisfied")),
        "public_ws_replay_sequence_ready": bool(validation.get("all_verified_sessions_have_replay_sequence_ready")),
        "public_ws_resync_policy_ready": bool(validation.get("resync_policy_exercised")),
        "public_ws_required_channels_observed": bool(validation.get("required_channels_observed")),
        "minimum_event_ledger_history_days_satisfied": bool(validation.get("minimum_event_ledger_history_days_satisfied")),
        "minimum_calendar_span_days_satisfied": bool(validation.get("minimum_calendar_span_days_satisfied")),
        "execution_latency_model_ready": latency_model.get("status") == "ready_public_proxy_research_only",
        "execution_latency_model_status": latency_model.get("status"),
        "execution_latency_model_gate_blocker_type": latency_model.get("gate_blocker_type"),
        "queue_model_ready": queue_model.get("status") == "ready_public_l2_proxy_research_only",
        "queue_model_status": queue_model.get("status"),
        "queue_model_gate_blocker_type": queue_model.get("gate_blocker_type"),
        "verified_public_session_count": _int(totals.get("verified_public_session_count")),
        "total_event_ledger_history_days": _float(totals.get("total_event_ledger_history_days")),
        "calendar_span_days": _float(totals.get("calendar_span_days")),
        "paper_runtime_replay_path": _portable_path(paper_runtime_replay_path),
        "paper_runtime_replay_present": bool(paper_replay),
        "paper_runtime_replay_ready": _paper_replay_ready(paper_replay),
        "paper_runtime_current_flat_heartbeat_healthy": bool(paper_replay_summary.get("current_flat_heartbeat_healthy")),
        "paper_runtime_trade_execution_evidence_available": bool(
            paper_replay_summary.get("trade_execution_evidence_available")
        ),
        "paper_runtime_trade_execution_evidence_pending_reason": paper_replay_summary.get(
            "trade_execution_evidence_pending_reason"
        ),
        "paper_runtime_health_status": paper_replay_summary.get("paper_runtime_health_status"),
        "paper_runtime_current_non_flat_sample_capture_status": paper_replay_summary.get(
            "current_non_flat_sample_capture_status"
        ),
        "paper_runtime_ready_waiting_non_flat_sample": _paper_replay_waiting_for_non_flat_sample(paper_replay),
        "paper_runtime_gate_eligible_current_capture_count": _int(
            paper_replay_summary.get("gate_eligible_current_capture_count")
        ),
        "paper_runtime_current_non_flat_capture_ready": paper_replay_summary.get(
            "current_non_flat_sample_capture_status"
        )
        == "gate_eligible_non_flat_capture_ready",
        "paper_runtime_non_blocking_pending_conditions": paper_replay_summary.get("non_blocking_pending_conditions", []),
        "paper_runtime_drill_path": _portable_path(paper_runtime_drill_path),
        "paper_runtime_drill_present": bool(paper_drill),
        "paper_runtime_drill_complete": paper_drill.get("status") == "complete_research_only",
        "paper_runtime_drill_simulated_fill_count": _int(paper_drill_summary.get("simulated_fill_count")),
        "paper_runtime_drill_event_ledger_row_count": _int(paper_drill_summary.get("event_ledger_row_count")),
        "paper_runtime_drill_reconciliation_passed": paper_drill_summary.get("oms_session_reconciliation_status") == "complete"
        and _int(paper_drill_summary.get("oms_session_unreconciled_count")) == 0,
        "paper_runtime_drill_gate_evidence": bool(paper_drill_summary.get("paper_runtime_gate_evidence")),
        "paper_runtime_fixture_drill_path": _portable_path(paper_runtime_fixture_drill_path),
        "paper_runtime_fixture_drill_present": bool(paper_fixture_drill),
        "paper_runtime_fixture_drill_complete": paper_fixture_drill.get("status") == "complete_research_only",
        "paper_runtime_fixture_drill_ready": bool(paper_fixture_summary.get("paper_runtime_fixture_drill_ready")),
        "paper_runtime_fixture_drill_simulated_fill_count": _int(paper_fixture_summary.get("simulated_fill_count")),
        "paper_runtime_fixture_drill_event_ledger_row_count": _int(paper_fixture_summary.get("event_ledger_row_count")),
        "paper_runtime_fixture_drill_reconciliation_passed": paper_fixture_summary.get("oms_session_reconciliation_status")
        == "complete"
        and _int(paper_fixture_summary.get("oms_session_unreconciled_count")) == 0,
        "paper_runtime_fixture_drill_gate_evidence": bool(paper_fixture_summary.get("paper_runtime_gate_evidence")),
        "paper_runtime_reconciliation_path": _portable_path(paper_runtime_reconciliation_path),
        "paper_runtime_reconciliation_present": bool(paper_reconciliation),
        "paper_runtime_reconciliation_passed": bool(
            paper_reconciliation_summary.get("paper_runtime_reconciliation_passed")
        ),
        "paper_runtime_reconciliation_violation_count": _int(paper_reconciliation_summary.get("violation_count")),
        "paper_runtime_reconciliation_event_row_count": _int(paper_reconciliation_summary.get("event_row_count")),
        "ready_for_manual_runtime_review": False,
    }


def _evidence_layers(gap: Mapping[str, Any]) -> dict[str, Any]:
    fixture_passed = (
        gap.get("paper_runtime_fixture_drill_complete") is True
        and gap.get("paper_runtime_fixture_drill_ready") is True
        and gap.get("paper_runtime_fixture_drill_reconciliation_passed") is True
        and gap.get("paper_runtime_fixture_drill_gate_evidence") is False
    )
    historical_passed = (
        gap.get("paper_runtime_drill_complete") is True
        and _int(gap.get("paper_runtime_drill_simulated_fill_count")) > 0
        and _int(gap.get("paper_runtime_drill_event_ledger_row_count")) > 0
        and gap.get("paper_runtime_drill_reconciliation_passed") is True
        and gap.get("paper_runtime_drill_gate_evidence") is False
    )
    current_passed = gap.get("paper_runtime_replay_ready") is True and gap.get("paper_runtime_reconciliation_passed") is True
    current_pending_reason = gap.get("paper_runtime_trade_execution_evidence_pending_reason") or (
        "current_runtime_replay_not_ready" if not current_passed else ""
    )
    return {
        "schema_version": "btc_runtime_replay_evidence_layers_v1",
        "layer_order": [
            "fixture_capability",
            "historical_drill",
            "current_observe_only_gate_evidence",
        ],
        "fixture_capability": {
            "status": "passed" if fixture_passed else ("pending" if not gap.get("paper_runtime_fixture_drill_present") else "failed"),
            "passed": fixture_passed,
            "report_present": bool(gap.get("paper_runtime_fixture_drill_present")),
            "source_path": gap.get("paper_runtime_fixture_drill_path"),
            "simulated_fill_count": gap.get("paper_runtime_fixture_drill_simulated_fill_count"),
            "event_ledger_row_count": gap.get("paper_runtime_fixture_drill_event_ledger_row_count"),
            "oms_reconciliation_passed": gap.get("paper_runtime_fixture_drill_reconciliation_passed"),
            "paper_runtime_gate_evidence": False,
            "paper_gate_eligible": False,
            "meaning": "deterministic fixture proves local order/fill/funding/liquidation plumbing only",
        },
        "historical_drill": {
            "status": "passed" if historical_passed else ("pending" if not gap.get("paper_runtime_drill_present") else "failed"),
            "passed": historical_passed,
            "report_present": bool(gap.get("paper_runtime_drill_present")),
            "source_path": gap.get("paper_runtime_drill_path"),
            "simulated_fill_count": gap.get("paper_runtime_drill_simulated_fill_count"),
            "event_ledger_row_count": gap.get("paper_runtime_drill_event_ledger_row_count"),
            "oms_reconciliation_passed": gap.get("paper_runtime_drill_reconciliation_passed"),
            "paper_runtime_gate_evidence": False,
            "paper_gate_eligible": False,
            "meaning": "historical drill proves the replay chain on selected historical non-flat rows only",
        },
        "current_observe_only_gate_evidence": {
            "status": "passed" if current_passed else "pending",
            "passed": current_passed,
            "report_present": bool(gap.get("paper_runtime_replay_present")),
            "source_path": gap.get("paper_runtime_replay_path"),
            "current_flat_heartbeat_healthy": gap.get("paper_runtime_current_flat_heartbeat_healthy"),
            "trade_execution_evidence_available": gap.get("paper_runtime_trade_execution_evidence_available"),
            "current_non_flat_sample_capture_status": gap.get("paper_runtime_current_non_flat_sample_capture_status"),
            "gate_eligible_current_capture_count": gap.get("paper_runtime_gate_eligible_current_capture_count"),
            "current_non_flat_capture_ready": gap.get("paper_runtime_current_non_flat_capture_ready"),
            "pending_reason": "" if current_passed else current_pending_reason,
            "paper_runtime_replay_ready": gap.get("paper_runtime_replay_ready"),
            "paper_runtime_reconciliation_passed": gap.get("paper_runtime_reconciliation_passed"),
            "paper_gate_eligible": current_passed,
            "meaning": "only this layer can satisfy current paper gate evidence after real observe-only trade samples exist",
        },
        "promotion_rule": {
            "paper_gate_may_consider_only_layer": "current_observe_only_gate_evidence",
            "fixture_or_drill_cannot_satisfy_gate": True,
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
    }


def _runtime_capability_layers(
    *,
    runtime: Mapping[str, Any],
    public_runtime_dry_probe: Mapping[str, Any],
    coverage: Mapping[str, Any],
    gap: Mapping[str, Any],
) -> dict[str, Any]:
    runtime_notes = _mapping(runtime.get("notes"))
    ws_proxy_passed = (
        bool(gap.get("public_ws_replay_sequence_ready"))
        and bool(gap.get("public_ws_resync_policy_ready"))
        and bool(gap.get("public_ws_required_channels_observed"))
        and _int(gap.get("verified_public_session_count")) > 0
    )
    public_probe_passed = _public_runtime_dry_probe_passed(public_runtime_dry_probe)
    public_layer = _mapping(public_runtime_dry_probe.get("runtime_layer"))
    return {
        "schema_version": "btc_runtime_capability_layers_v1",
        "local_deterministic_fixture": {
            "status": "passed" if runtime.get("status") == "complete" else "missing",
            "evidence_type": runtime_notes.get("evidence_type"),
            "meaning": "local contract/fixture checks state-machine fields only; it is not current gate evidence",
            "paper_gate_eligible": False,
        },
        "public_runtime_dry_probe": {
            "status": "passed" if public_probe_passed else "pending",
            "source_report_present": bool(public_runtime_dry_probe),
            "decision": public_runtime_dry_probe.get("decision"),
            "server_time_verified": public_layer.get("server_time_verified") is True,
            "symbol_rules_visible": public_layer.get("symbol_rules_visible") is True,
            "mark_price_available": public_layer.get("mark_price_available") is True,
            "index_price_available": public_layer.get("index_price_available") is True,
            "funding_available": public_layer.get("funding_available") is True,
            "public_depth_available": public_layer.get("public_depth_available") is True,
            "open_interest_available": public_layer.get("open_interest_available") is True,
            "metadata_version_visible": bool(
                public_layer.get("symbol_rules_visible")
                or runtime.get("metadata_version")
                or coverage.get("metadata_version")
                or runtime
            ),
            "public_ws_sequence_gapfill_replay_verified": bool(
                public_layer.get("public_ws_replay_verified") or gap.get("public_ws_replay_sequence_ready")
            ),
            "public_ws_resync_policy_verified": bool(
                public_layer.get("public_ws_resync_policy_verified") or gap.get("public_ws_resync_policy_ready")
            ),
            "required_channels_observed": bool(
                _nested(public_runtime_dry_probe, "public_ws_runtime_state", "required_channels_observed")
                or gap.get("public_ws_required_channels_observed")
            ),
            "verified_public_session_count": gap.get("verified_public_session_count"),
            "ws_proxy_passed": ws_proxy_passed,
            "coverage_history_sufficient": bool(gap.get("public_ws_coverage_contract_satisfied")),
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "paper_gate_eligible": False,
            "meaning": "public runtime dry probe can validate market-data/runtime plumbing, not private paper fills",
        },
        "paper_private_order_simulated_entry": {
            "status": "disabled_interface_ready_waiting_for_authorization_or_current_sample",
            "private_endpoint_used": bool(gap.get("runtime_contract_private_endpoint_used")),
            "order_endpoint_used": bool(gap.get("runtime_contract_order_endpoint_used")),
            "paper_runtime_replay_ready": bool(gap.get("paper_runtime_replay_ready")),
            "current_non_flat_capture_ready": bool(gap.get("paper_runtime_current_non_flat_capture_ready")),
            "paper_gate_eligible": False,
            "current_observe_only_gate_evidence_layer_required": True,
            "meaning": "paper/private/order endpoints remain disabled; only current observe-only non-flat samples can become gate evidence",
        },
    }


def _blockers(
    *,
    runtime: Mapping[str, Any],
    public_runtime_dry_probe: Mapping[str, Any],
    coverage: Mapping[str, Any],
    paper_replay: Mapping[str, Any],
    gap: Mapping[str, Any],
    paper_runtime_replay_path: Path,
) -> list[str]:
    blockers: list[str] = []
    if not runtime:
        blockers.append("btc_runtime_contract_missing")
    if gap.get("runtime_contract_local_fixture_only") is True:
        blockers.append("btc_runtime_contract_local_fixture_only_public_or_paper_runtime_layer_required")
    if _public_runtime_dry_probe_passed(public_runtime_dry_probe) is not True:
        blockers.append("btc_public_runtime_dry_probe_missing_or_not_verified")
        blockers.extend(
            f"btc_public_runtime_dry_probe:{item}"
            for item in public_runtime_dry_probe.get("blockers", [])
            if isinstance(item, str)
        )
    if gap.get("runtime_contract_status_complete") is not True:
        blockers.append("btc_runtime_contract_not_complete")
    if not coverage:
        blockers.append("btc_public_ws_l2_coverage_report_missing")
    if gap.get("public_ws_coverage_contract_satisfied") is not True:
        blockers.append("btc_public_ws_l2_coverage_contract_not_satisfied")
    if gap.get("minimum_event_ledger_history_days_satisfied") is not True:
        blockers.append("btc_public_ws_l2_event_history_days_insufficient")
    if gap.get("minimum_calendar_span_days_satisfied") is not True:
        blockers.append("btc_public_ws_l2_calendar_span_days_insufficient")
    if gap.get("execution_latency_model_ready") is not True:
        blocker_type = gap.get("execution_latency_model_gate_blocker_type") or "model_missing"
        blockers.append(f"btc_execution_latency_model:{blocker_type}")
    if gap.get("queue_model_ready") is not True:
        blocker_type = gap.get("queue_model_gate_blocker_type") or "model_missing"
        blockers.append(f"btc_queue_model:{blocker_type}")
    if not paper_runtime_replay_path.exists() or not paper_replay:
        blockers.append("btc_paper_runtime_replay_missing")
    elif gap.get("paper_runtime_replay_ready") is not True:
        if gap.get("paper_runtime_ready_waiting_non_flat_sample") is True:
            blockers.append("btc_runtime_ready_waiting_non_flat_sample")
        else:
            blockers.append("btc_paper_runtime_replay_not_ready")
            blockers.extend(str(item) for item in paper_replay.get("blockers", []) if isinstance(item, str))
    elif gap.get("paper_runtime_reconciliation_passed") is not True:
        blockers.append("btc_paper_runtime_reconciliation_not_passed")
    blockers.extend(str(item) for item in coverage.get("blockers", []) if isinstance(item, str))
    return sorted(set(blockers))


def _runtime_contract_summary(runtime: Mapping[str, Any]) -> dict[str, Any]:
    notes = runtime.get("notes", {}) if isinstance(runtime.get("notes"), Mapping) else {}
    return {
        "present": bool(runtime),
        "status": runtime.get("status"),
        "decision": runtime.get("decision"),
        "venue": runtime.get("venue"),
        "mode": runtime.get("mode"),
        "evidence_type": notes.get("evidence_type"),
        "private_endpoint_used": bool(runtime.get("private_endpoint_used") or notes.get("private_endpoint_used")),
        "order_endpoint_used": bool(runtime.get("order_endpoint_used") or notes.get("order_endpoint_used")),
        "real_order_submitted": bool(runtime.get("real_order_submitted") or notes.get("real_order_submitted")),
        "public_ws_gapfill": runtime.get("public_ws_gapfill", {}),
        "private_ws_gapfill": runtime.get("private_ws_gapfill", {}),
    }


def _public_runtime_dry_probe_summary(report: Mapping[str, Any], path: Path) -> dict[str, Any]:
    layer = _mapping(report.get("runtime_layer"))
    ws = _mapping(report.get("public_ws_runtime_state"))
    return {
        "path": _portable_path(path),
        "present": bool(report),
        "status": report.get("status"),
        "decision": report.get("decision"),
        "passed": _public_runtime_dry_probe_passed(report),
        "network_called": report.get("network_called") is True,
        "server_time_verified": layer.get("server_time_verified") is True,
        "symbol_rules_visible": layer.get("symbol_rules_visible") is True,
        "mark_price_available": layer.get("mark_price_available") is True,
        "index_price_available": layer.get("index_price_available") is True,
        "funding_available": layer.get("funding_available") is True,
        "public_depth_available": layer.get("public_depth_available") is True,
        "open_interest_available": layer.get("open_interest_available") is True,
        "public_ws_replay_verified": layer.get("public_ws_replay_verified") is True,
        "public_ws_resync_policy_verified": layer.get("public_ws_resync_policy_verified") is True,
        "verified_public_session_count": ws.get("verified_public_session_count", 0),
        "paper_gate_eligible": False,
        "private_endpoint_used": bool(report.get("private_endpoint_used")),
        "order_endpoint_used": bool(report.get("order_endpoint_used")),
        "real_order_submitted": bool(report.get("real_order_submitted")),
        "blockers": report.get("blockers", []),
    }


def _public_coverage_summary(coverage: Mapping[str, Any]) -> dict[str, Any]:
    validation = coverage.get("validation", {}) if isinstance(coverage.get("validation"), Mapping) else {}
    totals = coverage.get("coverage_totals", {}) if isinstance(coverage.get("coverage_totals"), Mapping) else {}
    return {
        "present": bool(coverage),
        "status": coverage.get("status"),
        "decision": coverage.get("decision"),
        "coverage_contract_satisfied": bool(coverage.get("coverage_contract_satisfied") or validation.get("coverage_contract_satisfied")),
        "verified_public_session_count": _int(totals.get("verified_public_session_count")),
        "total_capture_duration_seconds": _float(totals.get("total_capture_duration_seconds")),
        "total_event_ledger_history_days": _float(totals.get("total_event_ledger_history_days")),
        "calendar_span_days": _float(totals.get("calendar_span_days")),
        "replay_sequence_ready_session_count": _int(totals.get("replay_sequence_ready_session_count")),
        "resync_policy_ready_session_count": _int(totals.get("resync_policy_ready_session_count")),
        "actual_reconnect_or_gap_exercised_session_count": _int(totals.get("actual_reconnect_or_gap_exercised_session_count")),
        "execution_latency_model_ready": bool(coverage.get("execution_latency_model_ready") or validation.get("execution_latency_model_ready")),
        "queue_model_ready": bool(coverage.get("queue_model_ready") or validation.get("queue_model_ready")),
        "blockers": coverage.get("blockers", []),
    }


def _paper_replay_summary(paper_replay: Mapping[str, Any], path: Path) -> dict[str, Any]:
    summary = _mapping(paper_replay.get("summary"))
    return {
        "path": _portable_path(path),
        "present": bool(paper_replay),
        "status": paper_replay.get("status"),
        "decision": paper_replay.get("decision"),
        "ready": _paper_replay_ready(paper_replay),
        "current_flat_heartbeat_healthy": bool(summary.get("current_flat_heartbeat_healthy")),
        "trade_execution_evidence_available": bool(summary.get("trade_execution_evidence_available")),
        "trade_execution_evidence_pending_reason": summary.get("trade_execution_evidence_pending_reason"),
        "current_non_flat_sample_capture_status": summary.get("current_non_flat_sample_capture_status"),
        "gate_eligible_current_capture_count": _int(summary.get("gate_eligible_current_capture_count")),
        "current_non_flat_capture_ready": summary.get("current_non_flat_sample_capture_status")
        == "gate_eligible_non_flat_capture_ready",
        "paper_runtime_health_status": summary.get("paper_runtime_health_status"),
        "non_blocking_pending_conditions": summary.get("non_blocking_pending_conditions", []),
        "private_endpoint_used": bool(paper_replay.get("private_endpoint_used")),
        "order_endpoint_used": bool(paper_replay.get("order_endpoint_used")),
        "real_order_submitted": bool(paper_replay.get("real_order_submitted")),
        "blockers": paper_replay.get("blockers", []),
    }


def _paper_drill_summary(paper_drill: Mapping[str, Any], path: Path) -> dict[str, Any]:
    summary = _mapping(paper_drill.get("summary"))
    return {
        "path": _portable_path(path),
        "present": bool(paper_drill),
        "status": paper_drill.get("status"),
        "decision": paper_drill.get("decision"),
        "simulated_fill_count": _int(summary.get("simulated_fill_count")),
        "theoretical_order_count": _int(summary.get("theoretical_order_count")),
        "event_ledger_row_count": _int(summary.get("event_ledger_row_count")),
        "event_type_counts": summary.get("event_type_counts", {}),
        "paper_runtime_gate_evidence": bool(summary.get("paper_runtime_gate_evidence")),
        "private_endpoint_used": bool(paper_drill.get("private_endpoint_used")),
        "order_endpoint_used": bool(paper_drill.get("order_endpoint_used")),
        "real_order_submitted": bool(paper_drill.get("real_order_submitted")),
        "warnings": paper_drill.get("warnings", []),
        "blockers": paper_drill.get("blockers", []),
    }


def _paper_reconciliation_summary(paper_reconciliation: Mapping[str, Any], path: Path) -> dict[str, Any]:
    summary = _mapping(paper_reconciliation.get("summary"))
    return {
        "path": _portable_path(path),
        "present": bool(paper_reconciliation),
        "status": paper_reconciliation.get("status"),
        "decision": paper_reconciliation.get("decision"),
        "passed": bool(summary.get("paper_runtime_reconciliation_passed")),
        "violation_count": _int(summary.get("violation_count")),
        "event_row_count": _int(summary.get("event_row_count")),
        "fill_event_count": _int(summary.get("fill_event_count")),
        "funding_cashflow_event_count": _int(summary.get("funding_cashflow_event_count")),
        "warnings": paper_reconciliation.get("warnings", []),
    }


def _paper_replay_ready(paper_replay: Mapping[str, Any]) -> bool:
    if not paper_replay:
        return False
    if paper_replay.get("status") not in {"complete_research_only", "complete"}:
        return False
    if paper_replay.get("decision") not in {"paper_runtime_replay_ready_for_manual_review", "runtime_ready_for_paper_replay"}:
        return False
    if paper_replay.get("blockers"):
        return False
    return not any(bool(paper_replay.get(key)) for key in ("private_endpoint_used", "order_endpoint_used", "real_order_submitted"))


def _paper_replay_waiting_for_non_flat_sample(paper_replay: Mapping[str, Any]) -> bool:
    if not paper_replay or paper_replay.get("blockers"):
        return False
    summary = _mapping(paper_replay.get("summary"))
    return (
        summary.get("current_flat_heartbeat_healthy") is True
        and summary.get("trade_execution_evidence_available") is not True
        and str(summary.get("trade_execution_evidence_pending_reason") or "")
        == "waiting_for_current_gate_eligible_non_flat_fill"
    )


def _public_runtime_dry_probe_passed(report: Mapping[str, Any]) -> bool:
    if not report:
        return False
    if report.get("status") != "verified_research_only":
        return False
    if report.get("blockers"):
        return False
    layer = _mapping(report.get("runtime_layer"))
    required = (
        "server_time_verified",
        "symbol_rules_visible",
        "mark_price_available",
        "index_price_available",
        "funding_available",
        "public_ws_replay_verified",
    )
    return all(layer.get(key) is True for key in required) and not any(
        bool(report.get(key)) for key in ("private_endpoint_used", "order_endpoint_used", "real_order_submitted")
    )


def _summary(*, gap: Mapping[str, Any], blockers: list[str], evidence_layers: Mapping[str, Any]) -> dict[str, Any]:
    fixture_layer = _mapping(evidence_layers.get("fixture_capability"))
    historical_layer = _mapping(evidence_layers.get("historical_drill"))
    current_layer = _mapping(evidence_layers.get("current_observe_only_gate_evidence"))
    return {
        "blocker_count": len(blockers),
        "runtime_contract_is_simulated_probe": gap.get("runtime_contract_is_simulated_probe"),
        "runtime_local_contract_is_simulated_probe": gap.get("runtime_local_contract_is_simulated_probe"),
        "runtime_contract_effective_layer": gap.get("runtime_contract_effective_layer"),
        "runtime_contract_local_fixture_only": gap.get("runtime_contract_local_fixture_only"),
        "public_runtime_dry_probe_passed": gap.get("public_runtime_dry_probe_passed"),
        "public_runtime_server_time_verified": gap.get("public_runtime_server_time_verified"),
        "public_runtime_symbol_rules_visible": gap.get("public_runtime_symbol_rules_visible"),
        "public_runtime_mark_price_available": gap.get("public_runtime_mark_price_available"),
        "public_runtime_index_price_available": gap.get("public_runtime_index_price_available"),
        "public_runtime_funding_available": gap.get("public_runtime_funding_available"),
        "public_ws_coverage_contract_satisfied": gap.get("public_ws_coverage_contract_satisfied"),
        "public_ws_replay_sequence_ready": gap.get("public_ws_replay_sequence_ready"),
        "execution_latency_model_ready": gap.get("execution_latency_model_ready"),
        "queue_model_ready": gap.get("queue_model_ready"),
        "paper_runtime_replay_ready": gap.get("paper_runtime_replay_ready"),
        "paper_runtime_current_flat_heartbeat_healthy": gap.get("paper_runtime_current_flat_heartbeat_healthy"),
        "paper_runtime_trade_execution_evidence_available": gap.get("paper_runtime_trade_execution_evidence_available"),
        "paper_runtime_trade_execution_evidence_pending_reason": gap.get(
            "paper_runtime_trade_execution_evidence_pending_reason"
        ),
        "paper_runtime_ready_waiting_non_flat_sample": gap.get("paper_runtime_ready_waiting_non_flat_sample"),
        "runtime_gate_wait_state": (
            "runtime_ready_waiting_non_flat_sample"
            if gap.get("paper_runtime_ready_waiting_non_flat_sample") is True
            else ("current_gate_evidence_passed" if gap.get("paper_runtime_replay_ready") is True else "runtime_evidence_incomplete")
        ),
        "paper_runtime_current_non_flat_sample_capture_status": gap.get(
            "paper_runtime_current_non_flat_sample_capture_status"
        ),
        "paper_runtime_gate_eligible_current_capture_count": gap.get("paper_runtime_gate_eligible_current_capture_count"),
        "paper_runtime_current_non_flat_capture_ready": gap.get("paper_runtime_current_non_flat_capture_ready"),
        "paper_runtime_health_status": gap.get("paper_runtime_health_status"),
        "fixture_capability_status": fixture_layer.get("status"),
        "fixture_capability_passed": fixture_layer.get("passed"),
        "historical_drill_status": historical_layer.get("status"),
        "historical_drill_passed": historical_layer.get("passed"),
        "current_observe_only_gate_evidence_status": current_layer.get("status"),
        "current_observe_only_gate_evidence_passed": current_layer.get("passed"),
        "current_observe_only_gate_evidence_pending_reason": current_layer.get("pending_reason"),
        "fixture_or_drill_cannot_satisfy_paper_gate": True,
        "paper_runtime_drill_present": gap.get("paper_runtime_drill_present"),
        "paper_runtime_drill_simulated_fill_count": gap.get("paper_runtime_drill_simulated_fill_count"),
        "paper_runtime_drill_event_ledger_row_count": gap.get("paper_runtime_drill_event_ledger_row_count"),
        "paper_runtime_drill_gate_evidence": gap.get("paper_runtime_drill_gate_evidence"),
        "paper_runtime_fixture_drill_present": gap.get("paper_runtime_fixture_drill_present"),
        "paper_runtime_fixture_drill_ready": gap.get("paper_runtime_fixture_drill_ready"),
        "paper_runtime_fixture_drill_simulated_fill_count": gap.get("paper_runtime_fixture_drill_simulated_fill_count"),
        "paper_runtime_fixture_drill_event_ledger_row_count": gap.get("paper_runtime_fixture_drill_event_ledger_row_count"),
        "paper_runtime_fixture_drill_gate_evidence": gap.get("paper_runtime_fixture_drill_gate_evidence"),
        "paper_runtime_reconciliation_present": gap.get("paper_runtime_reconciliation_present"),
        "paper_runtime_reconciliation_passed": gap.get("paper_runtime_reconciliation_passed"),
        "paper_runtime_reconciliation_violation_count": gap.get("paper_runtime_reconciliation_violation_count"),
        "paper_runtime_reconciliation_event_row_count": gap.get("paper_runtime_reconciliation_event_row_count"),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Runtime replay gap report is diagnostic and cannot promote paper/live.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _warnings(*, blockers: list[str], gap: Mapping[str, Any]) -> list[str]:
    warnings = ["btc_exchange_runtime_replay_gap_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("runtime_replay_gap_incomplete_fail_closed")
    if gap.get("public_ws_replay_sequence_ready") is True and gap.get("paper_runtime_replay_ready") is not True:
        warnings.append("public_market_replay_is_not_paper_execution_replay")
    if (
        gap.get("paper_runtime_current_flat_heartbeat_healthy") is True
        and gap.get("paper_runtime_trade_execution_evidence_available") is not True
    ):
        warnings.append("paper_runtime_currently_flat_heartbeat_healthy_but_trade_sample_missing")
    if gap.get("paper_runtime_drill_simulated_fill_count", 0) > 0:
        warnings.append("paper_runtime_drill_has_simulated_fills_but_is_not_gate_evidence")
    if gap.get("paper_runtime_fixture_drill_ready") is True:
        warnings.append("paper_runtime_fixture_capability_passed_but_is_not_gate_evidence")
    if gap.get("paper_runtime_reconciliation_present") is True and gap.get("paper_runtime_reconciliation_passed") is not True:
        warnings.append("paper_runtime_event_ledger_reconciliation_not_passed")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_exchange_runtime_replay_gap_safety_status_v1",
        "status": "research_only",
        "decision": report.get("decision"),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "blockers": list(report.get("blockers", [])),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested(payload: Mapping[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current
