from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


BTC_ROOT_CAUSE_DAG_SCHEMA_VERSION = "btc_root_cause_dag_v1"


@dataclass(frozen=True)
class RootCauseDefinition:
    root_cause_id: str
    category: str
    label_cn: str
    description_cn: str
    next_action_cn: str


ROOT_CAUSE_DEFINITIONS: dict[str, RootCauseDefinition] = {
    "data_wait": RootCauseDefinition(
        root_cause_id="data_wait",
        category="data_wait",
        label_cn="数据等待",
        description_cn="盘口、mark/index、funding、liquidation、覆盖窗口或字段可见性证据还没补齐。",
        next_action_cn="继续补齐/等待数据采集与覆盖验证，特别是 depth、mark/index、funding、liquidation 和 slippage 历史证据。",
    ),
    "runtime_not_connected": RootCauseDefinition(
        root_cause_id="runtime_not_connected",
        category="runtime_not_connected",
        label_cn="runtime 未接通",
        description_cn="paper runtime、fill mapping、exchange runtime、replay、kill switch 或成交样本仍未形成闭环。",
        next_action_cn="等待非空策略信号产生 replay/fill 样本，并完成 fill mapping、reconciliation、exchange runtime 和 kill switch 复核。",
    ),
    "runtime_ready_waiting_non_flat_sample": RootCauseDefinition(
        root_cause_id="runtime_ready_waiting_non_flat_sample",
        category="sample_wait",
        label_cn="runtime 已就绪，等待非空样本",
        description_cn="本地 fixture、historical drill 或 flat heartbeat 正常，但当前 observe-only 信号为空，没有可作为 gate evidence 的非空订单/成交样本。",
        next_action_cn="继续 observe-only；非空信号出现时自动捕获 theoretical order、risk decision、OMS lifecycle、funding、liquidation buffer 和 fill mapping。",
    ),
    "strategy_overfit_or_forward_gap": RootCauseDefinition(
        root_cause_id="strategy_overfit_or_forward_gap",
        category="strategy_overfit",
        label_cn="策略过拟合/forward 不足",
        description_cn="策略仍有 observe-only、holdout、参数边界、收益集中、回撤压力或 forward confirmation 缺口。",
        next_action_cn="保持 research-only，继续 30/60 天 observe-only、holdout、行情分段、参数邻域稳定性和成本压力复核。",
    ),
    "manual_review_approval_missing": RootCauseDefinition(
        root_cause_id="manual_review_approval_missing",
        category="manual_review",
        label_cn="人工审批缺失",
        description_cn="人工批准、operator packet、人工复核记录或旧 paper approval 冲突未闭合；API key audit 和 account attestation 只有过期或 redaction 失败时才成为 blocker。",
        next_action_cn="补齐人工批准记录和 operator packet，让当前证据链重新通过人工复核；不允许自动解锁 paper/live。",
    ),
    "operator_paper_intake_envelope_missing": RootCauseDefinition(
        root_cause_id="operator_paper_intake_envelope_missing",
        category="manual_review",
        label_cn="operator paper intake envelope pending",
        description_cn=(
            "Manual paper review can be recorded while the separate paper-intake envelope "
            "for principal, leverage, order notional, or daily order limit is still absent."
        ),
        next_action_cn=(
            "Record the redacted operator intake envelope, then rebuild the gate chain. "
            "This cannot auto-enable paper/live."
        ),
    ),
    "safety_fail_closed": RootCauseDefinition(
        root_cause_id="safety_fail_closed",
        category="safety",
        label_cn="安全 fail-closed",
        description_cn="上游 artifact 暴露了 paper/live/order/broker/private 等安全字段为 true，必须整体关闭。",
        next_action_cn="先修复任何 paper/live/order/private/broker true 或 live 未冻结冲突，再重新生成 gate artifact。",
    ),
    "source_artifact_missing": RootCauseDefinition(
        root_cause_id="source_artifact_missing",
        category="source_artifact",
        label_cn="证据 artifact 缺失",
        description_cn="根因判断所需的上游报告缺失、JSON 无效或 artifact 不可读。",
        next_action_cn="恢复或重新生成缺失/损坏的 upstream artifact，然后重建总控报告。",
    ),
    "source_artifact_stale": RootCauseDefinition(
        root_cause_id="source_artifact_stale",
        category="source_artifact",
        label_cn="证据 artifact 过期",
        description_cn="上游 source artifact 的生成时间晚于聚合报告、缺少时间戳，或超过 freshness SLA。",
        next_action_cn="按依赖顺序重建 stale source artifact，再重建 promotion gate；聚合报告不得消费比自己更新或超过 SLA 的 source。",
    ),
    "artifact_consistency_mismatch": RootCauseDefinition(
        root_cause_id="artifact_consistency_mismatch",
        category="source_artifact",
        label_cn="artifact 一致性不匹配",
        description_cn="dashboard、evidence、promotion 等读模型之间的内嵌 hash 或 source reference 不一致。",
        next_action_cn="按聚合链顺序重建 upstream artifact、dashboard、gate_report_consistency 和 promotion gate；不把该问题归入交易 objective。",
    ),
    "uncategorized_blocker": RootCauseDefinition(
        root_cause_id="uncategorized_blocker",
        category="uncategorized",
        label_cn="未归类 blocker",
        description_cn="当前规则无法稳定归类的 blocker，需要人工补充归因规则。",
        next_action_cn="人工检查 blocker 命名，并把稳定模式补进 root-cause 分类表。",
    ),
}

ROOT_CAUSE_TASK_DEFINITIONS: dict[str, dict[str, Any]] = {
    "data_wait": {
        "owner": "data-runtime automation",
        "source_reports": [
            "artifacts/btc_perpetual_gate_objective_status/latest/btc_perpetual_gate_objective_status_report.json",
            "artifacts/btc_cost_model/latest/btc_depth_slippage_report.json",
        ],
        "next_command": "wait_for_automated_depth_and_market_data_accumulation_then_rebuild_gate_chain",
        "acceptance_criteria": [
            "depth/mark/index/funding/slippage coverage satisfies gate checks",
            "gate fill mapping has current gate-eligible samples when strategy is non-flat",
        ],
        "task_bucket": "data_wait",
    },
    "runtime_not_connected": {
        "owner": "runtime/replay engineer",
        "source_reports": [
            "artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_replay_gap_report.json",
            "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_report.json",
            "artifacts/btc_micro_live_preflight/latest/btc_micro_live_preflight_report.json",
        ],
        "next_command": "py scripts/build_btc_gate_aggregation_chain.py",
        "acceptance_criteria": [
            "current non-flat observe-only sample records theoretical order, risk decision, OMS lifecycle, fill, funding and liquidation buffer",
            "runtime replay and reconciliation reports pass without using private/order endpoints",
        ],
        "task_bucket": "immediate_development",
    },
    "runtime_ready_waiting_non_flat_sample": {
        "owner": "observe-only automation",
        "source_reports": [
            "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_report.json",
            "artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_replay_gap_report.json",
            "artifacts/btc_micro_live_preflight/latest/btc_micro_live_preflight_report.json",
        ],
        "next_command": "continue_observe_only_until_non_flat_sample_then_rebuild_gate_chain",
        "acceptance_criteria": [
            "flat heartbeat does not create false orders or fills",
            "first current non-flat sample records complete gate-eligible replay evidence",
        ],
        "task_bucket": "data_wait",
    },
    "strategy_overfit_or_forward_gap": {
        "owner": "strategy governance",
        "source_reports": [
            "artifacts/btc_strategy_promotion_readiness/latest/btc_strategy_promotion_readiness_report.json",
            "artifacts/btc_strategy_leakage_overfit_audit/latest/btc_strategy_leakage_overfit_audit_report.json",
        ],
        "next_command": "continue_observe_only_forward_window_no_new_strategy_mining",
        "acceptance_criteria": [
            "30/60 day observe-only window reaches required minimum",
            "holdout, cost stress and parameter-boundary audit remain clean after selection lock",
        ],
        "task_bucket": "data_wait",
    },
    "manual_review_approval_missing": {
        "owner": "operator/manual reviewer",
        "source_reports": [
            "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json",
            "artifacts/btc_exchange_runtime/latest/btc_paper_exchange_rule_preflight_report.json",
            "artifacts/btc_micro_live_preflight/latest/btc_micro_live_preflight_report.json",
        ],
        "next_command": "record_manual_paper_review_approval_then_rebuild_gate_chain",
        "acceptance_criteria": [
            "manual approval is recorded in the current operator packet and paper exchange rule report",
            "API key audit and account attestation remain pass/current, but do not auto-enable paper/live",
        ],
        "task_bucket": "immediate_development",
    },
    "operator_paper_intake_envelope_missing": {
        "owner": "operator/risk reviewer",
        "source_reports": [
            "artifacts/btc_micro_live_preflight/latest/btc_micro_live_preflight_report.json",
            "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json",
        ],
        "next_command": "fill_review_only_operator_intake_envelope_then_rebuild_gate_chain",
        "acceptance_criteria": [
            "approved principal, leverage, order notional and daily order limit are explicit and redacted",
            "paper/live/order flags remain false after the envelope is recorded",
        ],
        "task_bucket": "immediate_development",
    },
    "safety_fail_closed": {
        "owner": "safety reviewer",
        "source_reports": [
            "artifacts/btc_dirty_worktree_boundary/latest/btc_dirty_worktree_boundary_report.json",
            "artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json",
        ],
        "next_command": "fix_true_paper_live_order_flags_then_rebuild_gate_chain",
        "acceptance_criteria": [
            "paper/live/order/broker/private true flags are all false in upstream artifacts",
            "dirty-worktree boundary marks local secrets and attestation as never commit",
        ],
        "task_bucket": "immediate_development",
    },
    "source_artifact_missing": {
        "owner": "artifact pipeline",
        "source_reports": ["artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json"],
        "next_command": "rebuild_missing_source_artifact_then_py_scripts_build_btc_gate_aggregation_chain",
        "acceptance_criteria": ["required source artifacts exist, are valid JSON and have generated_at timestamps"],
        "task_bucket": "immediate_development",
    },
    "source_artifact_stale": {
        "owner": "artifact pipeline",
        "source_reports": ["artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_artifact_freshness_matrix.csv"],
        "next_command": "py scripts/build_btc_gate_aggregation_chain.py",
        "acceptance_criteria": [
            "freshness status is pass",
            "stale/future/batch/dependency mismatch counts are zero",
        ],
        "task_bucket": "immediate_development",
    },
    "artifact_consistency_mismatch": {
        "owner": "artifact pipeline",
        "source_reports": [
            "artifacts/btc_gate_report_consistency/latest/btc_gate_report_consistency_report.json",
            "artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json",
            "artifacts/btc_perpetual_execution_evidence/latest/btc_perpetual_execution_evidence_report.json",
        ],
        "next_command": "py scripts/build_btc_gate_aggregation_chain.py",
        "acceptance_criteria": [
            "dashboard embedded perpetual_execution_evidence hash equals current evidence artifact hash",
            "mismatch is reported under artifact consistency, not btc_perpetual_gate_objective",
        ],
        "task_bucket": "immediate_development",
    },
    "uncategorized_blocker": {
        "owner": "gate maintainer",
        "source_reports": ["artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_root_cause_matrix.csv"],
        "next_command": "classify_uncategorized_blocker_patterns",
        "acceptance_criteria": ["uncategorized blocker count is zero or explicitly reviewed"],
        "task_bucket": "immediate_development",
    },
}


SOURCE_MISSING_PATTERNS = (
    "missing_source",
    "missing_input",
    "artifact_missing",
    "missing_artifact",
    "event_ledger_manifest_missing",
    "invalid_json",
    "json_root_not_object",
)
SOURCE_STALE_PATTERNS = (
    "artifact_freshness",
    "source_artifact_stale",
    "source_timestamp_missing",
    "source_newer_than_aggregate",
    "source_different_aggregation_batch",
    "source_batch_mismatch",
    "batch_mismatch",
    "stale_source",
    "freshness_sla",
    "age_hours_gt_sla",
)
ARTIFACT_CONSISTENCY_PATTERNS = (
    "dirty_worktree",
    "artifact_consistency",
    "gate_report_consistency",
    "dashboard_perpetual_execution_evidence_hash_mismatch",
    "dashboard_perpetual_evidence_matches_current_artifact",
    "dashboard_perpetual_execution_evidence_hash_matches_current_artifact",
)
SAFETY_PATTERNS = (
    "safety_violation",
    "unsafe_flag",
    "live_status_not_frozen",
    "live_unlock_allowed",
    "live_order_allowed",
    "paper_start_allowed",
    "paper_execution_authorized",
    "paper_queue_write_allowed",
    "order_endpoint",
    "real_order",
    "broker",
    "private_endpoint",
    "micro_live_allowed=true",
)
MANUAL_PATTERNS = (
    "manual",
    "approval",
    "approved_paper_review",
    "current_packet_unapproved",
    "current_packet_approval_hash_not_current",
    "not_approved",
    "max_principal_usd_not_set",
    "max_principal_not_set",
    "approved_but_current_gate_blocked",
    "attestation",
    "operator_packet",
    "api_key_permission",
    "api_key_class_missing",
    "credential",
    "permission_review",
    "paper_review_pending",
)
OPERATOR_ENVELOPE_PATTERNS = (
    "operator_paper_intake_envelope_initial_principal_missing",
    "operator_paper_intake_envelope_daily_order_limit_missing",
    "operator_paper_intake_envelope_leverage_missing",
    "operator_paper_intake_envelope_order_notional_missing",
    "micro_live_initial_principal_not_approved",
    "micro_live_daily_order_limit_not_approved",
    "micro_live_leverage_not_approved",
    "micro_live_order_notional_not_approved",
    "approved_initial_principal_usdt",
    "daily_order_limit_not_approved",
    "order_notional_not_approved",
    "leverage_not_approved",
)
RUNTIME_PATTERNS = (
    "runtime",
    "replay",
    "simulated_fill",
    "no_simulated",
    "fill_mapping",
    "gate_fill",
    "exchange",
    "kill_switch",
    "order_sample",
    "current_flat",
    "heartbeat",
    "reconciliation",
    "paper_order",
    "oms",
    "route",
    "perpetual_execution",
    "perpetual_execution_evidence",
    "execution_evidence",
    "paper_validation_runtime",
    "gate_dashboard:decision:btc_gate_dashboard_blocked",
    "gate_dashboard:status:blocked",
    "fail_count_nonzero",
    "preflight_blocked",
    "micro_live_preflight_blocked",
    "trade_sample",
    "private_execution_latency_model_missing",
)
RUNTIME_SAMPLE_WAIT_PATTERNS = (
    "btc_runtime_ready_waiting_non_flat_sample",
    "waiting_for_current_gate_eligible_non_flat_fill",
    "current_flat_heartbeat_waiting_for_trade_sample",
    "current_flat_waiting_for_order_filter_sample",
    "current_flat_heartbeat_waiting_for_order_sample",
    "current_observe_only_signal_flat_waiting_for_exchange_filter_sample",
    "flat_no_gate_eligible_trade",
    "flat_waiting_no_false_positive",
    "strategy_fill_mapping_verified",
    "gate_fill_count",
    "mapped_gate_fill_count",
    "no_gate_eligible_fill",
    "no_gate_eligible_trade",
    "no_current_theoretical_orders_to_validate",
    "current_paper_runtime_not_ready",
    "real_or_paper_replay_ready",
    "no_simulated_fills",
    "order_sample_pending",
    "trade_sample_pending",
)
DATA_INSUFFICIENT_PATTERNS = (
    "data_insufficient",
    "btc_maker_taker_fee_tier_missing",
    "btc_slippage_bps_missing",
    "coverage_contract_not_satisfied",
    "event_history_days_insufficient",
    "calendar_span_days_insufficient",
    "public_ws_l2_event_history_days_insufficient",
    "public_ws_l2_calendar_span_days_insufficient",
    "execution_latency_model:data_insufficient",
    "queue_model:data_insufficient",
    "missing_public_ws_coverage_is_not_order_latency",
    "missing_public_l2_coverage_is_not_exchange_queue_position",
    "l2_capture_coverage",
    "public_l2_coverage",
    "public_ws_coverage",
    "depth_aware_slippage_history_verified",
    "depth_history_coverage",
    "slippage_history_verified",
    "fill_mapping_not_older_than_runtime_replay",
    "cost_contract_not_complete",
    "bundle_history_too_short",
    "tick_orderbook_spread_latency_queue_model",
)
STRATEGY_PATTERNS = (
    "overfit",
    "compression_expansion",
    "regime_pass_rate",
    "distribution_edge",
    "walk_forward_regime_cost_stress",
    "full_event_ledger_retest_required",
    "tail_dependency_right_tail_concentrated",
    "profit_factor_failed",
    "micro_surgery_rejected",
    "holdout",
    "forward_observation",
    "observe_only",
    "observation_under",
    "under_30d",
    "under_60d",
    "60d",
    "30d",
    "high_octane",
    "threshold",
    "boundary",
    "drawdown",
    "stress",
    "parameter",
    "candidate",
    "paper_readiness_not_ready",
    "paper_validation_start",
    "paper_validation_evaluation",
    "shadow_live_not_completed",
    "strategy_promotion_readiness",
    "btc_strategy_promotion_readiness_blocked",
    "loss_control",
    "strategy_ledger",
    "strategy_readiness",
    "bar_replay_model_boundary_requires_execution_replay",
)
STRATEGY_PRECEDENCE_PATTERNS = (
    "bar_replay_model_boundary_requires_execution_replay",
    "forward_observation",
    "observation_calendar_gap",
    "latest_observation_stale",
    "under_30d",
    "under_60d",
    "high_octane_40pct",
    "threshold_boundary",
    "loss_control",
    "long_short_top5",
    "high_yield_v2",
)
DATA_PATTERNS = (
    "depth",
    "coverage",
    "slippage_history",
    "mark",
    "index",
    "funding",
    "liquidation",
    "derivatives",
    "kline",
    "data",
    "ohlcv",
    "sentiment",
    "provider",
    "bundle_preflight_not_pass",
    "cost_model_not_pass",
    "fee_tier_cost_model_not_verified",
    "objective_audit_incomplete",
    "tail_dependency_not_pass",
)
DERIVED_CONSEQUENCE_PATTERNS = (
    "status:blocked",
    "status:blocked_research_only",
    "status:incomplete_research_only",
    "status:fail_closed_research_only",
    "decision:btc_gate_dashboard_blocked",
    "decision:btc_paper_live_kill_switch_engaged_fail_closed_no_paper_no_live",
    "decision:btc_paper_exchange_rule_preflight_incomplete_fail_closed_no_paper_no_live",
    "decision:runtime_replay_gap_incomplete_fail_closed_no_paper_no_live",
    "decision:perpetual_execution_evidence_incomplete_fail_closed_no_paper_no_live",
    "decision:btc_strategy_promotion_readiness_blocked_no_paper_no_live",
    "micro_live_preflight_blocked",
    "micro_live_preflight_requires_clean_kill_switch_status",
    "paper_readiness_not_ready",
    "external_evidence_paper_gate_not_ready",
    "paper_live_locked",
    "paper_exchange_rule_kill_switch_currently_engaged",
    "paper_exchange_rule_order_filter_or_kill_switch_failures_present",
    "kill_switch_currently_engaged",
    "kill_switch_engaged",
)


def classify_btc_blocker_root_cause(blocker: str) -> str:
    text = str(blocker).lower()
    if _contains_any(text, SOURCE_MISSING_PATTERNS):
        return "source_artifact_missing"
    if _contains_any(text, SOURCE_STALE_PATTERNS):
        return "source_artifact_stale"
    if _contains_any(text, ARTIFACT_CONSISTENCY_PATTERNS):
        return "artifact_consistency_mismatch"
    if _contains_any(text, SAFETY_PATTERNS):
        return "safety_fail_closed"
    if _contains_any(text, OPERATOR_ENVELOPE_PATTERNS):
        return "operator_paper_intake_envelope_missing"
    if "no_line_ready_for_manual_paper_review" in text:
        return "strategy_overfit_or_forward_gap"
    if _contains_any(text, MANUAL_PATTERNS):
        return "manual_review_approval_missing"
    if _contains_any(text, RUNTIME_SAMPLE_WAIT_PATTERNS):
        return "runtime_ready_waiting_non_flat_sample"
    if _contains_any(text, DATA_INSUFFICIENT_PATTERNS):
        return "data_wait"
    if _contains_any(text, STRATEGY_PRECEDENCE_PATTERNS):
        return "strategy_overfit_or_forward_gap"
    if _contains_any(text, STRATEGY_PATTERNS):
        return "strategy_overfit_or_forward_gap"
    if _contains_any(text, DATA_PATTERNS):
        return "data_wait"
    if _contains_any(text, RUNTIME_PATTERNS):
        return "runtime_not_connected"
    return "uncategorized_blocker"


def root_cause_ids_for_blockers(blockers: Sequence[str]) -> list[str]:
    return _dedupe(
        [
            classify_btc_blocker_root_cause(str(item))
            for item in blockers
            if str(item) and not is_derived_consequence_blocker(str(item))
        ]
    )


def is_derived_consequence_blocker(blocker: str) -> bool:
    text = str(blocker).lower()
    if _contains_any(text, DERIVED_CONSEQUENCE_PATTERNS):
        return True
    if _contains_any(text, RUNTIME_SAMPLE_WAIT_PATTERNS):
        return False
    if _contains_any(text, DATA_INSUFFICIENT_PATTERNS):
        return False
    if _contains_any(text, STRATEGY_PATTERNS):
        return False
    if _contains_any(text, DATA_PATTERNS):
        return False
    if _contains_any(text, MANUAL_PATTERNS):
        return False
    if _contains_any(text, SAFETY_PATTERNS):
        return False
    return False


def build_btc_root_cause_dag(
    blockers_by_gate: Mapping[str, Sequence[str]],
    *,
    gate_sources: Mapping[str, Sequence[str]] | None = None,
    root_node_id: str = "btc_promotion_gate_blocked",
) -> dict[str, Any]:
    gate_sources = gate_sources or {}
    cause_stats: dict[str, dict[str, Any]] = {}
    gate_nodes: list[dict[str, Any]] = []
    raw_blocker_count = 0
    all_blockers: list[str] = []

    for gate_id, raw_blockers in blockers_by_gate.items():
        blockers = [str(item) for item in raw_blockers if str(item) and not is_derived_consequence_blocker(str(item))]
        raw_blocker_count += len(blockers)
        all_blockers.extend(blockers)
        gate_root_cause_ids = root_cause_ids_for_blockers(blockers)
        gate_nodes.append(
            {
                "node_id": f"gate:{gate_id}",
                "node_type": "gate",
                "gate_id": str(gate_id),
                "root_cause_ids": gate_root_cause_ids,
                "raw_blocker_count": len(blockers),
                "unique_blocker_count": len(set(blockers)),
            }
        )
        for blocker in blockers:
            root_cause_id = classify_btc_blocker_root_cause(blocker)
            stats = cause_stats.setdefault(
                root_cause_id,
                {
                    "raw_blocker_count": 0,
                    "blockers": [],
                    "affected_gates": [],
                    "source_ids": [],
                },
            )
            stats["raw_blocker_count"] += 1
            stats["blockers"].append(blocker)
            if gate_id not in stats["affected_gates"]:
                stats["affected_gates"].append(str(gate_id))
            for source_id in gate_sources.get(gate_id, ()):
                if source_id not in stats["source_ids"]:
                    stats["source_ids"].append(str(source_id))

    root_cause_matrix = []
    for root_cause_id, stats in cause_stats.items():
        definition = ROOT_CAUSE_DEFINITIONS.get(root_cause_id, ROOT_CAUSE_DEFINITIONS["uncategorized_blocker"])
        unique_blockers = _dedupe(stats["blockers"])
        root_cause_matrix.append(
            {
                "root_cause_id": root_cause_id,
                "category": definition.category,
                "label_cn": definition.label_cn,
                "description_cn": definition.description_cn,
                **_task_definition(root_cause_id),
                "raw_blocker_count": int(stats["raw_blocker_count"]),
                "unique_blocker_count": len(unique_blockers),
                "affected_gates": sorted(stats["affected_gates"]),
                "source_ids": sorted(stats["source_ids"]),
                "blocker_examples": unique_blockers[:8],
                "next_action_cn": definition.next_action_cn,
            }
        )
    root_cause_matrix.sort(key=lambda item: (-int(item["raw_blocker_count"]), str(item["root_cause_id"])))

    cause_nodes = [
        {
            "node_id": f"root_cause:{item['root_cause_id']}",
            "node_type": "root_cause",
            **item,
        }
        for item in root_cause_matrix
    ]
    edges = [
        {
            "from": root_node_id,
            "to": f"root_cause:{item['root_cause_id']}",
            "edge_type": "has_root_cause",
        }
        for item in root_cause_matrix
    ]
    for item in root_cause_matrix:
        for gate_id in item["affected_gates"]:
            edges.append(
                {
                    "from": f"root_cause:{item['root_cause_id']}",
                    "to": f"gate:{gate_id}",
                    "edge_type": "blocks_gate",
                }
            )

    unique_blocker_count = len(set(all_blockers))
    root_cause_count = len(root_cause_matrix)
    compression_ratio = round(raw_blocker_count / root_cause_count, 4) if root_cause_count else 0.0
    task_queue = _task_queue(root_cause_matrix)
    return {
        "schema_version": BTC_ROOT_CAUSE_DAG_SCHEMA_VERSION,
        "root_node_id": root_node_id,
        "raw_blocker_count": raw_blocker_count,
        "unique_blocker_count": unique_blocker_count,
        "root_cause_count": root_cause_count,
        "compression_ratio_raw_to_root": compression_ratio,
        "dominant_root_cause_id": root_cause_matrix[0]["root_cause_id"] if root_cause_matrix else "",
        "nodes": [
            {
                "node_id": root_node_id,
                "node_type": "root",
                "label_cn": "BTC promotion gate blocked",
                "raw_blocker_count": raw_blocker_count,
                "unique_blocker_count": unique_blocker_count,
                "root_cause_count": root_cause_count,
            },
            *cause_nodes,
            *gate_nodes,
        ],
        "edges": edges,
        "root_cause_matrix": root_cause_matrix,
        "task_queue": task_queue,
    }


def root_cause_summary(root_cause_dag: Mapping[str, Any]) -> dict[str, Any]:
    task_queue = root_cause_dag.get("task_queue")
    task_queue_map = task_queue if isinstance(task_queue, Mapping) else {}
    return {
        "schema_version": root_cause_dag.get("schema_version"),
        "root_node_id": root_cause_dag.get("root_node_id"),
        "raw_blocker_count": root_cause_dag.get("raw_blocker_count", 0),
        "unique_blocker_count": root_cause_dag.get("unique_blocker_count", 0),
        "root_cause_count": root_cause_dag.get("root_cause_count", 0),
        "compression_ratio_raw_to_root": root_cause_dag.get("compression_ratio_raw_to_root", 0.0),
        "dominant_root_cause_id": root_cause_dag.get("dominant_root_cause_id", ""),
        "data_wait_task_count": len(task_queue_map.get("data_wait_items", [])) if isinstance(task_queue_map.get("data_wait_items"), list) else 0,
        "immediate_development_task_count": (
            len(task_queue_map.get("immediate_development_items", []))
            if isinstance(task_queue_map.get("immediate_development_items"), list)
            else 0
        ),
    }


def _task_definition(root_cause_id: str) -> dict[str, Any]:
    task = ROOT_CAUSE_TASK_DEFINITIONS.get(root_cause_id, ROOT_CAUSE_TASK_DEFINITIONS["uncategorized_blocker"])
    return {
        "owner": task["owner"],
        "source_reports": list(task["source_reports"]),
        "next_command": task["next_command"],
        "acceptance_criteria": list(task["acceptance_criteria"]),
        "task_bucket": task["task_bucket"],
    }


def _task_queue(root_cause_matrix: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    data_wait_items = []
    immediate_items = []
    for item in root_cause_matrix:
        task = {
            "root_cause_id": item.get("root_cause_id"),
            "label_cn": item.get("label_cn"),
            "owner": item.get("owner"),
            "source_reports": item.get("source_reports", []),
            "next_command": item.get("next_command"),
            "acceptance_criteria": item.get("acceptance_criteria", []),
            "raw_blocker_count": item.get("raw_blocker_count", 0),
            "affected_gates": item.get("affected_gates", []),
        }
        if item.get("task_bucket") == "data_wait":
            data_wait_items.append(task)
        else:
            immediate_items.append(task)
    return {
        "schema_version": "btc_root_cause_task_queue_v1",
        "data_wait_items": data_wait_items,
        "immediate_development_items": immediate_items,
        "display_limit": 8,
        "dashboard_should_show_root_causes_only": True,
    }


def _contains_any(text: str, patterns: Sequence[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
