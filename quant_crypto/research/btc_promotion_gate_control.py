from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.monitoring.artifact_schema import stable_payload_hash
from quant_crypto.monitoring.btc_root_cause_dag import (
    build_btc_root_cause_dag,
    root_cause_ids_for_blockers,
    root_cause_summary,
)
from quant_crypto.monitoring.btc_dirty_worktree_boundary import build_dirty_state_summary


SCHEMA_VERSION = "btc_promotion_gate_control_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_promotion_gate_control/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_promotion_gate_control_report.json"
DEFAULT_MATRIX_PATH = DEFAULT_OUTPUT_DIR / "btc_promotion_gate_control_matrix.csv"
DEFAULT_ROOT_CAUSE_DAG_PATH = DEFAULT_OUTPUT_DIR / "btc_promotion_gate_control_root_cause_dag.json"
DEFAULT_ROOT_CAUSE_MATRIX_PATH = DEFAULT_OUTPUT_DIR / "btc_promotion_gate_control_root_cause_matrix.csv"
DEFAULT_FRESHNESS_MATRIX_PATH = DEFAULT_OUTPUT_DIR / "btc_promotion_gate_control_artifact_freshness_matrix.csv"
DEFAULT_SUMMARY_CN_PATH = DEFAULT_OUTPUT_DIR / "btc_promotion_gate_control_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"
DEFAULT_SOURCE_FRESHNESS_SLA_HOURS = 48.0

DEFAULT_SOURCE_PATHS: dict[str, Path] = {
    "strategy_ledger": Path("artifacts/btc_strategy_ledger/latest/btc_strategy_ledger_report.json"),
    "strategy_readiness": Path(
        "artifacts/btc_strategy_promotion_readiness/latest/btc_strategy_promotion_readiness_report.json"
    ),
    "observe_only_health": Path("artifacts/btc_observe_only_health/latest/btc_observe_only_health_report.json"),
    "leakage_overfit": Path(
        "artifacts/btc_strategy_leakage_overfit_audit/latest/btc_strategy_leakage_overfit_audit_report.json"
    ),
    "bar_replay": Path("artifacts/btc_strategy_bar_replay_visibility/latest/btc_strategy_bar_replay_visibility_report.json"),
    "perpetual_objective": Path(
        "artifacts/btc_perpetual_gate_objective_status/latest/btc_perpetual_gate_objective_status_report.json"
    ),
    "gate_dashboard": Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json"),
    "gate_report_consistency": Path(
        "artifacts/btc_gate_report_consistency/latest/btc_gate_report_consistency_report.json"
    ),
    "paper_readiness": Path("artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json"),
    "micro_live_preflight": Path("artifacts/btc_micro_live_preflight/latest/btc_micro_live_preflight_report.json"),
    "kill_switch": Path("artifacts/btc_exchange_runtime/latest/btc_paper_live_kill_switch_status_report.json"),
    "paper_runtime_replay": Path("artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_report.json"),
    "paper_runtime_reconciliation": Path(
        "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_reconciliation_report.json"
    ),
    "paper_exchange_rule": Path("artifacts/btc_exchange_runtime/latest/btc_paper_exchange_rule_preflight_report.json"),
    "paper_risk_drill": Path("artifacts/btc_exchange_runtime/latest/btc_paper_risk_circuit_breaker_drill_report.json"),
    "exchange_runtime_gap": Path("artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_replay_gap_report.json"),
    "perpetual_execution": Path("artifacts/btc_perpetual_execution_evidence/latest/btc_perpetual_execution_evidence_report.json"),
    "depth_slippage": Path("artifacts/btc_cost_model/latest/btc_depth_slippage_report.json"),
    "fill_mapping": Path("artifacts/btc_cost_model/latest/btc_depth_slippage_fill_mapping_report.json"),
    "cost_model": Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json"),
    "manual_packet": Path("artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json"),
    "api_key_audit": Path("artifacts/btc_security/latest/btc_api_key_permission_audit.json"),
    "order_surface_audit": Path("artifacts/btc_security/latest/btc_order_surface_audit_report.json"),
    "account_attestation": Path(
        "artifacts/btc_exchange_runtime/latest/btc_paper_account_runtime_attestation_report.json"
    ),
    "manual_paper_review_approval": Path(
        "artifacts/btc_manual_paper_review_approval/latest/btc_manual_paper_review_approval_report.json"
    ),
    "dirty_worktree_boundary": Path(
        "artifacts/btc_dirty_worktree_boundary/latest/btc_dirty_worktree_boundary_report.json"
    ),
}

PROMOTION_SOURCE_FRESHNESS_SLA_HOURS: dict[str, float] = {
    "strategy_ledger": 168.0,
    "strategy_readiness": 72.0,
    "observe_only_health": 72.0,
    "leakage_overfit": 168.0,
    "bar_replay": 168.0,
    "perpetual_objective": 48.0,
    "gate_dashboard": 6.0,
    "gate_report_consistency": 6.0,
    "paper_readiness": 72.0,
    "micro_live_preflight": 6.0,
    "kill_switch": 24.0,
    "paper_runtime_replay": 24.0,
    "paper_runtime_reconciliation": 72.0,
    "paper_exchange_rule": 24.0,
    "paper_risk_drill": 168.0,
    "exchange_runtime_gap": 24.0,
    "perpetual_execution": 24.0,
    "depth_slippage": 24.0,
    "fill_mapping": 24.0,
    "cost_model": 24.0,
    "manual_packet": 720.0,
    "api_key_audit": 168.0,
    "order_surface_audit": 24.0,
    "account_attestation": 168.0,
    "manual_paper_review_approval": 168.0,
    "dirty_worktree_boundary": 24.0,
}

PROMOTION_SAME_BATCH_SOURCE_IDS = {
    "gate_dashboard",
    "gate_report_consistency",
    "micro_live_preflight",
    "kill_switch",
    "paper_exchange_rule",
    "exchange_runtime_gap",
    "manual_paper_review_approval",
    "order_surface_audit",
    "dirty_worktree_boundary",
}

PROMOTION_SOURCE_HEAD_COMMIT_REQUIRED_IDS = {
    "strategy_readiness",
    "perpetual_objective",
    "gate_dashboard",
    "gate_report_consistency",
    "paper_readiness",
    "micro_live_preflight",
    "kill_switch",
    "paper_runtime_replay",
    "paper_runtime_reconciliation",
    "paper_exchange_rule",
    "exchange_runtime_gap",
    "perpetual_execution",
    "depth_slippage",
    "fill_mapping",
    "cost_model",
    "order_surface_audit",
    "manual_paper_review_approval",
    "dirty_worktree_boundary",
}

PROMOTION_SOURCE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "kill_switch": (
        "manual_paper_review_approval",
        "paper_exchange_rule",
        "exchange_runtime_gap",
    ),
    "micro_live_preflight": (
        "strategy_readiness",
        "observe_only_health",
        "kill_switch",
        "exchange_runtime_gap",
        "paper_runtime_replay",
        "paper_runtime_reconciliation",
        "paper_exchange_rule",
        "paper_risk_drill",
        "perpetual_execution",
        "gate_dashboard",
        "manual_paper_review_approval",
    ),
    "gate_dashboard": (
        "paper_readiness",
        "micro_live_preflight",
        "perpetual_execution",
        "cost_model",
    ),
    "gate_report_consistency": (
        "gate_dashboard",
        "perpetual_execution",
    ),
}

PROMOTION_SOURCE_REBUILD_COMMANDS: dict[str, str] = {
    "strategy_ledger": "py scripts/research/build_btc_strategy_ledger.py",
    "strategy_readiness": "py scripts/research/build_btc_strategy_promotion_readiness_review.py",
    "observe_only_health": "py scripts/research/build_btc_observe_only_health_report.py",
    "leakage_overfit": "py scripts/research/build_btc_strategy_leakage_overfit_audit.py",
    "bar_replay": "py scripts/research/build_btc_strategy_bar_replay_visibility.py",
    "perpetual_objective": "py scripts/research/build_btc_perpetual_gate_objective_status.py",
    "gate_dashboard": "py scripts/build_btc_gate_dashboard.py",
    "gate_report_consistency": "py scripts/build_btc_gate_report_consistency.py",
    "paper_readiness": "py scripts/build_btc_paper_readiness_report.py",
    "micro_live_preflight": "py scripts/build_btc_micro_live_preflight.py",
    "kill_switch": "py scripts/build_btc_paper_live_kill_switch_status.py",
    "paper_runtime_replay": "py scripts/build_btc_perpetual_paper_runtime_replay_report.py",
    "paper_runtime_reconciliation": "py scripts/build_btc_perpetual_paper_runtime_reconciliation_report.py",
    "paper_exchange_rule": "py scripts/build_btc_paper_exchange_rule_preflight.py",
    "paper_risk_drill": "py scripts/build_btc_paper_risk_circuit_breaker_drill.py",
    "exchange_runtime_gap": "py scripts/build_btc_exchange_runtime_replay_gap_report.py",
    "perpetual_execution": "py scripts/research/build_btc_perpetual_execution_evidence.py",
    "depth_slippage": "py scripts/build_btc_depth_slippage_report.py",
    "fill_mapping": "py scripts/build_btc_depth_slippage_fill_mapping_report.py",
    "cost_model": "py scripts/build_btc_cost_model_report.py",
    "manual_packet": "manual_operator_packet_refresh_required",
    "api_key_audit": "py scripts/build_btc_api_key_permission_audit.py",
    "order_surface_audit": "py scripts/build_btc_order_surface_audit.py",
    "account_attestation": "py scripts/build_btc_paper_account_runtime_attestation.py",
    "manual_paper_review_approval": "py scripts/build_btc_manual_paper_review_approval.py",
    "dirty_worktree_boundary": "py scripts/build_btc_dirty_worktree_boundary_report.py",
}

FORBIDDEN_DIRECT_RESEARCH_SOURCE_PATTERNS = (
    "btc_ga_factor_mining",
    "btc_ga_rule_component_mining",
    "btc_multi_timeframe_rule_lab",
    "btc_long_short_trend_following_lab",
    "btc_small_account_high_yield_lab",
    "btc_high_octane_attack_sleeve_lab",
    "btc_pyramiding_sleeve_lab",
    "btc_bankroll_rollover_lab",
    "btc_10u_rollover_rulebook",
    "btc_multi_timeframe_ma_ladder",
    "btc_timesfm_smoke_forecast",
    "compare_btc_timesfm_vs_trend_baseline",
)

PROMOTION_ALLOWED_RESEARCH_BRIDGE_SOURCE_IDS = {
    "strategy_ledger",
    "strategy_readiness",
    "observe_only_health",
    "leakage_overfit",
    "bar_replay",
}

PROMOTION_SOURCE_CONSUMPTION_POLICIES: dict[str, dict[str, Any]] = {
    source_id: {
        "freshness_sla_hours": PROMOTION_SOURCE_FRESHNESS_SLA_HOURS[source_id],
        "batch_policy": (
            "same_batch_or_declared_valid_until"
            if source_id in PROMOTION_SAME_BATCH_SOURCE_IDS
            else "promotion_sla_or_declared_valid_until"
        ),
        "commit_policy": (
            "source_code_commit_must_match_current_head"
            if source_id in PROMOTION_SOURCE_HEAD_COMMIT_REQUIRED_IDS
            else "source_code_commit_not_required"
        ),
        "rebuild_command": PROMOTION_SOURCE_REBUILD_COMMANDS.get(source_id, "manual_rebuild_required"),
    }
    for source_id in DEFAULT_SOURCE_PATHS
}

CHAIN_AGGREGATE_REBUILD_COMMAND = "py scripts/build_btc_gate_aggregation_chain.py"
SOURCE_TIMELINE_SKEW_TOLERANCE_SECONDS = 180.0

GATE_IDS = (
    "artifact_freshness_gate",
    "artifact_consistency_gate",
    "data_gate",
    "strategy_gate",
    "risk_gate",
    "execution_gate",
    "kill_switch_gate",
    "drawdown_stress_gate",
    "leakage_overfit_gate",
    "manual_review_gate",
)

DANGEROUS_TRUE_KEYS = {
    "broker_access_allowed",
    "broker_or_order_allowed",
    "broker_calls_used",
    "live_allowed",
    "live_order_allowed",
    "live_unlock_allowed",
    "micro_live_allowed",
    "oms_access_allowed",
    "order_endpoint_allowed",
    "order_endpoint_used",
    "paper_allowed",
    "paper_candidate_allowed",
    "paper_candidate_created",
    "paper_execution_authorized",
    "paper_order_intake_allowed",
    "paper_or_live_unlock_allowed",
    "paper_queue_write_allowed",
    "paper_start_allowed",
    "position_increase_allowed",
    "private_endpoint_allowed",
    "private_endpoint_used",
    "real_order_submitted",
    "strategy_skeleton_generated",
}


@dataclass(frozen=True)
class SourceLoad:
    source_id: str
    path: Path
    payload: Mapping[str, Any]
    exists: bool
    error: str | None
    file_mtime_utc: str = ""
    file_mtime_ns: int | None = None
    file_size_bytes: int | None = None
    file_sha256: str = ""
    stable_hash: str = ""


def build_btc_promotion_gate_control(
    *,
    repo_root: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    source_paths: Mapping[str, Path] | None = None,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at_utc or datetime.now(timezone.utc)
    batch_id = aggregation_batch_id or _default_aggregation_batch_id(generated)
    output_dir = _resolve(root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = dict(DEFAULT_SOURCE_PATHS)
    paths.update(source_paths or {})
    sources = {source_id: _read_source(root, source_id, path) for source_id, path in paths.items()}
    current_code_commit = _git(["rev-parse", "--short", "HEAD"], cwd=root)
    current_blocked = _current_evidence_blocked(sources)
    research_isolation = _research_promotion_isolation(paths)
    freshness = _artifact_freshness(
        sources=sources,
        generated=generated,
        aggregation_batch_id=batch_id,
        current_code_commit=current_code_commit,
    )
    matrix = [
        _artifact_freshness_gate(freshness),
        _artifact_consistency_gate(sources),
        _data_gate(sources),
        _strategy_gate(sources),
        _risk_gate(sources),
        _execution_gate(sources),
        _kill_switch_gate(sources),
        _drawdown_stress_gate(sources),
        _leakage_overfit_gate(sources),
        _manual_review_gate(sources, current_blocked=current_blocked),
    ]
    safety_violations = _source_safety_violations(sources)
    safety_violations.extend(
        f"research_promotion_isolation:{item}"
        for item in _list_of_strings(research_isolation.get("blockers"))
    )
    safety_violations = sorted(set(safety_violations))
    for row in matrix:
        row["root_cause_ids"] = root_cause_ids_for_blockers(_list_of_strings(row.get("blockers")))
    root_cause_dag = _build_root_cause_dag(matrix, safety_violations)
    root_cause_matrix = _list_of_mappings(root_cause_dag.get("root_cause_matrix"))
    blockers = _all_blockers(matrix)
    blockers.extend(f"safety_violation:{item}" for item in safety_violations)
    blockers = sorted(set(blockers))
    if safety_violations:
        status = "safety_violation_fail_closed"
        decision = "btc_promotion_gate_control_safety_violation_fail_closed_no_paper_no_live"
    elif blockers:
        status = "blocked_research_only"
        decision = "btc_promotion_gate_control_blocked_no_paper_no_live"
    else:
        status = "complete_research_only_manual_review_required"
        decision = "btc_promotion_gate_control_complete_manual_review_only_no_auto_paper_no_live"
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    matrix_path = output_dir / DEFAULT_MATRIX_PATH.name
    root_cause_dag_path = output_dir / DEFAULT_ROOT_CAUSE_DAG_PATH.name
    root_cause_matrix_path = output_dir / DEFAULT_ROOT_CAUSE_MATRIX_PATH.name
    freshness_matrix_path = output_dir / DEFAULT_FRESHNESS_MATRIX_PATH.name
    summary_path = output_dir / DEFAULT_SUMMARY_CN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "aggregation_batch_id": batch_id,
        "code_commit": current_code_commit,
        "branch": _git(["branch", "--show-current"], cwd=root),
        "dirty_state_summary": build_dirty_state_summary(root),
        "status": status,
        "decision": decision,
        "scope": "btc_paper_promotion_gate_control_read_only_fail_closed",
        "gate_count": len(matrix),
        "blocked_gate_count": sum(1 for row in matrix if row["status"] != "pass"),
        "missing_source_count": sum(1 for source in sources.values() if not source.exists),
        "safety_violation_count": len(safety_violations),
        "key_blockers_cn": _key_blockers_cn(sources, matrix),
        "artifact_freshness": freshness,
        "required_rebuild_reports": freshness.get("required_rebuild_reports", []),
        "freshness_rebuild_plan": freshness.get("rebuild_plan", []),
        "root_cause_summary": root_cause_summary(root_cause_dag),
        "root_cause_dag": root_cause_dag,
        "root_cause_matrix": root_cause_matrix,
        "root_cause_task_queue": root_cause_dag.get("task_queue", {}),
        "research_promotion_isolation": research_isolation,
        "source_paths": {source_id: _portable_path(source.path) for source_id, source in sources.items()},
        "gate_matrix": matrix,
        "legacy_paper_readiness_conflict": _legacy_paper_conflict(sources, current_blocked=current_blocked),
        "gate": _gate(),
        "guardrails": _guardrails(),
        "safety_violations": safety_violations,
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(report_path),
            "matrix_csv": _portable_path(matrix_path),
            "root_cause_dag_json": _portable_path(root_cause_dag_path),
            "root_cause_matrix_csv": _portable_path(root_cause_matrix_path),
            "artifact_freshness_matrix_csv": _portable_path(freshness_matrix_path),
            "summary_cn": _portable_path(summary_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_matrix_csv(matrix_path, matrix)
    _write_json(root_cause_dag_path, root_cause_dag)
    _write_root_cause_matrix_csv(root_cause_matrix_path, root_cause_matrix)
    _write_freshness_matrix_csv(freshness_matrix_path, _list_of_mappings(freshness.get("sources")))
    _write_text(summary_path, render_btc_promotion_gate_control_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_promotion_gate_control_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# BTC Promotion Gate 总控报告",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- gate 维度数量：`{report.get('gate_count')}`",
        f"- blocked 维度数量：`{report.get('blocked_gate_count')}`",
        f"- 缺失证据源数量：`{report.get('missing_source_count')}`",
        f"- 安全异常数量：`{report.get('safety_violation_count')}`",
        f"- aggregation batch：`{report.get('aggregation_batch_id')}`",
        "- 边界：只读总控，不写 paper 队列，不解锁 live，不连接 broker/OMS/order。",
        "",
        "## Gate 矩阵",
        "",
        "| Gate | 状态 | 证据源 | 关键检查 | 阻塞原因 | 下一步 |",
        "|---|---|---|---|---|---|",
    ]
    for row in _list_of_mappings(report.get("gate_matrix")):
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(f"{row.get('gate_name_cn')} (`{row.get('gate_id')}`)"),
                    _md(row.get("status")),
                    _md(", ".join(_list_of_strings(row.get("source_ids")))),
                    _md(_checks_cell(row.get("checks"))),
                    _md(_limited_cell(_list_of_strings(row.get("blockers")), limit=6)),
                    _md(row.get("next_action_cn")),
                ]
            )
            + " |"
        )
    lines.extend(["", "## 当前最关键阻塞", ""])
    key_blockers = _list_of_strings(report.get("key_blockers_cn"))
    if key_blockers:
        lines.extend(f"- {item}" for item in key_blockers)
    else:
        lines.append("- 无。")
    _append_freshness_markdown(lines, report)
    _append_root_cause_markdown(lines, report)
    _append_dirty_state_markdown(lines, report)
    lines.extend(
        [
            "",
            "## 下一步等什么",
            "",
            "- 等自动任务继续累计 OKX depth，直到 depth window 满足 gate。",
            "- 等 observe-only 策略出现 gate-eligible fill，再做 fill mapping 和 depth-aware slippage 复核。",
            "- 等 30/60 天观察窗口完成，再把策略线做人工 paper 复核。",
            "- 等执行、kill switch、reconciliation、人工复核全部通过后，才允许讨论 paper。",
            "",
            "## 哪些不能做",
            "",
            "- 不能因为旧 paper readiness 显示 approved 就写 paper 队列。",
            "- 不能解锁 live。",
            "- 不能接 broker/OMS/order。",
            "- 不能把 TimesFM、GA、回测收益或单一高收益结果当成晋级依据。",
            "",
            "## Safety",
            "",
            f"- 写 paper 队列：`{_nested(report, 'gate', 'paper_queue_write_allowed')}`",
            f"- 允许 paper：`{_nested(report, 'gate', 'paper_allowed')}`",
            f"- 解锁 live：`{_nested(report, 'gate', 'live_unlock_allowed')}`",
            f"- broker/order：`{_nested(report, 'gate', 'broker_or_order_allowed')}`",
            "",
            "本报告是 paper promotion 总控入口，不是 paper/live 晋级证据本身。",
        ]
    )
    return "\n".join(lines) + "\n"


def _append_freshness_markdown(lines: list[str], report: Mapping[str, Any]) -> None:
    freshness = _mapping(report.get("artifact_freshness"))
    plan = _list_of_mappings(report.get("freshness_rebuild_plan"))
    lines.extend(
        [
            "",
            "## Artifact Freshness / 流水线一致性",
            "",
            f"- 状态：`{freshness.get('status', '')}`",
            f"- source 数：`{freshness.get('source_count', 0)}`",
            f"- stale source：`{freshness.get('stale_source_count', 0)}`",
            f"- source 晚于聚合报告：`{freshness.get('future_source_count', 0)}`",
            f"- 缺少 batch 且未声明有效期：`{freshness.get('batch_missing_count', 0)}`",
            f"- batch 不一致：`{freshness.get('batch_mismatch_count', 0)}`",
            f"- 上游报告晚于消费者报告：`{freshness.get('dependency_newer_than_consumer_count', 0)}`",
            f"- source 时间线一致：`{freshness.get('source_timeline_consistent', False)}`",
            "",
        ]
    )
    if not plan:
        lines.append("- 无需重建 freshness source。")
        return
    lines.extend(["| 需要重建 | 原因 | 命令 |", "|---|---|---|"])
    for row in plan[:20]:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row.get("source_id")),
                    _md("; ".join(_list_of_strings(row.get("reasons")))),
                    _md(row.get("rebuild_command")),
                ]
            )
            + " |"
        )
    if len(plan) > 20:
        lines.append(f"| ... | 其余 {len(plan) - 20} 项见 JSON/CSV | - |")


def _append_dirty_state_markdown(lines: list[str], report: Mapping[str, Any]) -> None:
    dirty = _mapping(report.get("dirty_state_summary"))
    if not dirty:
        return
    group_counts = _mapping(dirty.get("group_counts"))
    lines.extend(
        [
            "",
            "## 工作区边界 / Dirty Worktree",
            "",
            f"- 工作区是否 dirty：`{dirty.get('is_dirty')}`",
            f"- dirty 文件数：`{dirty.get('file_count', 0)}`",
            f"- 可提交 source/test 数：`{dirty.get('committable_source_or_test_count', 0)}`",
            f"- generated artifact/data 数：`{dirty.get('generated_artifact_count', 0)}`",
            f"- never-commit 本地文件数：`{dirty.get('never_commit_count', 0)}`",
            f"- 是否只剩 generated/never-commit：`{dirty.get('only_generated_or_never_commit_dirty')}`",
            f"- security/attestation 分组文件数：`{group_counts.get('security_attestation', 0)}`",
            "",
            "- 本地 account attestation、operator paper intake envelope、真实 key/secret/passphrase 只能作为本机证明材料，不能提交、不能输出到聊天、不能写入 paper/live 解锁路径。",
        ]
    )
    never_commit_paths = _list_of_strings(dirty.get("never_commit_paths"))
    if never_commit_paths:
        lines.extend(["", "### Never-Commit 本地文件", ""])
        for path in never_commit_paths[:12]:
            lines.append(f"- `{path}`")
        if len(never_commit_paths) > 12:
            lines.append(f"- 其余 {len(never_commit_paths) - 12} 项见 JSON。")


def _append_root_cause_markdown(lines: list[str], report: Mapping[str, Any]) -> None:
    summary = _mapping(report.get("root_cause_summary"))
    matrix = _list_of_mappings(report.get("root_cause_matrix"))
    task_queue = _mapping(report.get("root_cause_task_queue"))
    data_wait_items = _list_of_mappings(task_queue.get("data_wait_items"))
    immediate_items = _list_of_mappings(task_queue.get("immediate_development_items"))
    lines.extend(
        [
            "",
            "## Root-cause DAG / 根因收敛",
            "",
            f"- 原始 blocker 数：`{summary.get('raw_blocker_count', 0)}`",
            f"- 唯一 blocker 数：`{summary.get('unique_blocker_count', 0)}`",
            f"- 根因数：`{summary.get('root_cause_count', 0)}`",
            f"- 压缩比 raw/root：`{summary.get('compression_ratio_raw_to_root', 0.0)}`",
            f"- 主导根因：`{summary.get('dominant_root_cause_id', '')}`",
            f"- 数据等待任务：`{len(data_wait_items)}`",
            f"- 可立即开发任务：`{len(immediate_items)}`",
            "",
            "| 根因 | 原始 blocker 数 | 影响 gate | 示例 | 下一步 |",
            "|---|---:|---|---|---|",
        ]
    )
    if not matrix:
        lines.append("| 无 | 0 | - | - | - |")
        return
    for row in matrix:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(f"{row.get('label_cn')} (`{row.get('root_cause_id')}`)"),
                    _md(row.get("raw_blocker_count")),
                    _md(", ".join(_list_of_strings(row.get("affected_gates")))),
                    _md(_limited_cell(_list_of_strings(row.get("blocker_examples")), limit=3)),
                    _md(row.get("next_action_cn")),
                ]
                )
            + " |"
        )
    lines.extend(["", "## Root-cause 任务队列", "", "| 类型 | 根因 | owner | next command | 验收标准 |", "|---|---|---|---|---|"])
    for bucket_name, rows in (("数据等待", data_wait_items), ("可立即开发", immediate_items)):
        for row in rows[:8]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md(bucket_name),
                        _md(f"{row.get('label_cn')} (`{row.get('root_cause_id')}`)"),
                        _md(row.get("owner")),
                        _md(row.get("next_command")),
                        _md(_limited_cell(_list_of_strings(row.get("acceptance_criteria")), limit=2)),
                    ]
                )
                + " |"
            )


def _research_promotion_isolation(source_paths: Mapping[str, Path]) -> dict[str, Any]:
    direct_research_sources = []
    bridge_sources = []
    blockers: list[str] = []
    for source_id, path in source_paths.items():
        normalized = _portable_path(path).lower()
        matched_patterns = [
            pattern for pattern in FORBIDDEN_DIRECT_RESEARCH_SOURCE_PATTERNS if pattern.lower() in normalized
        ]
        if matched_patterns:
            direct_research_sources.append(
                {
                    "source_id": source_id,
                    "path": _portable_path(path),
                    "matched_patterns": matched_patterns,
                }
            )
            blockers.append(f"direct_research_artifact_source:{source_id}")
        if source_id in PROMOTION_ALLOWED_RESEARCH_BRIDGE_SOURCE_IDS:
            bridge_sources.append(
                {
                    "source_id": source_id,
                    "path": _portable_path(path),
                    "role": "allowed_governance_or_audit_bridge_not_raw_strategy_lab",
                }
            )
    return {
        "schema_version": "btc_research_promotion_isolation_v1",
        "status": "pass" if not blockers else "fail",
        "rule": "promotion may consume governance/audit bridge artifacts, not raw research lab/backtest artifacts",
        "allowed_bridge_source_ids": sorted(PROMOTION_ALLOWED_RESEARCH_BRIDGE_SOURCE_IDS),
        "forbidden_direct_research_source_patterns": list(FORBIDDEN_DIRECT_RESEARCH_SOURCE_PATTERNS),
        "bridge_sources": bridge_sources,
        "direct_research_sources": direct_research_sources,
        "blockers": sorted(set(blockers)),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _artifact_freshness(
    *,
    sources: Mapping[str, SourceLoad],
    generated: datetime,
    aggregation_batch_id: str,
    current_code_commit: str = "",
) -> dict[str, Any]:
    generated = generated.astimezone(timezone.utc)
    source_generated_by_id = {
        source_id: _source_generated_at(source.payload)
        for source_id, source in sources.items()
    }
    rows: list[dict[str, Any]] = []
    for source_id, source in sorted(sources.items()):
        blockers: list[str] = []
        policy = _source_consumption_policy(source_id)
        batch_policy = str(policy.get("batch_policy") or "promotion_sla_or_declared_valid_until")
        source_generated = source_generated_by_id.get(source_id)
        declared_valid_until = _source_valid_until(source.payload)
        source_batch_id = _source_batch_id(source.payload)
        source_code_commit = _source_code_commit(source.payload)
        source_code_commit_field = _source_code_commit_field(source.payload)
        sla_hours = _source_freshness_sla_hours(source_id)
        age_hours = None
        policy_valid_until = None
        effective_valid_until = declared_valid_until
        dependency_checks: list[dict[str, Any]] = []
        consumption_allowed_reason = ""
        commit_policy = (
            "source_code_commit_must_match_current_head"
            if source_id in PROMOTION_SOURCE_HEAD_COMMIT_REQUIRED_IDS
            else "source_code_commit_not_required"
        )
        if not source.exists:
            blockers.append(f"artifact_freshness:{source_id}:missing_source_report")
        elif source.error:
            blockers.append(f"artifact_freshness:{source_id}:invalid_json")
        elif source_generated is None:
            blockers.append(f"artifact_freshness:{source_id}:source_timestamp_missing")
        else:
            if (
                commit_policy == "source_code_commit_must_match_current_head"
                and current_code_commit
                and current_code_commit != "unknown"
            ):
                if not source_code_commit:
                    blockers.append(f"artifact_freshness:{source_id}:source_code_commit_missing")
                elif source_code_commit != current_code_commit:
                    blockers.append(f"artifact_freshness:{source_id}:source_code_commit_mismatch_current_head")
            age_hours = (generated - source_generated).total_seconds() / 3600.0
            policy_valid_until = source_generated + _hours_delta(sla_hours)
            effective_valid_until = declared_valid_until or policy_valid_until
            if age_hours < -(SOURCE_TIMELINE_SKEW_TOLERANCE_SECONDS / 3600.0):
                blockers.append(f"artifact_freshness:{source_id}:source_newer_than_aggregate_report")
            if batch_policy == "same_batch_or_declared_valid_until" and declared_valid_until is None and age_hours >= 0:
                if not source_batch_id:
                    blockers.append(f"artifact_freshness:{source_id}:source_missing_aggregation_batch_without_valid_until")
                elif source_batch_id != aggregation_batch_id:
                    blockers.append(f"artifact_freshness:{source_id}:source_different_aggregation_batch_without_valid_until")
            if effective_valid_until is not None and generated > effective_valid_until:
                blockers.append(f"artifact_freshness:{source_id}:source_artifact_stale_age_hours_gt_sla")
            dependency_checks = _source_dependency_checks(
                source_id=source_id,
                source_generated=source_generated,
                source_generated_by_id=source_generated_by_id,
            )
            blockers.extend(
                blocker
                for check in dependency_checks
                for blocker in _list_of_strings(check.get("blockers"))
            )
            consumption_allowed_reason = _consumption_allowed_reason(
                source_batch_id=source_batch_id,
                aggregation_batch_id=aggregation_batch_id,
                declared_valid_until=declared_valid_until,
                policy_valid_until=policy_valid_until,
                generated=generated,
            )
        rows.append(
            {
                "source_id": source_id,
                "path": _portable_path(source.path),
                "exists": source.exists,
                "freshness_policy": batch_policy,
                "source_generated_at_utc": source_generated.isoformat() if source_generated else None,
                "aggregate_generated_at_utc": generated.isoformat(),
                "aggregation_batch_id": aggregation_batch_id,
                "source_aggregation_batch_id": source_batch_id,
                "same_aggregation_batch": source_batch_id == aggregation_batch_id if source_batch_id else False,
                "commit_policy": commit_policy,
                "current_code_commit": current_code_commit,
                "source_code_commit": source_code_commit,
                "source_code_commit_field": source_code_commit_field,
                "source_code_commit_matches_current_head": (
                    source_code_commit == current_code_commit
                    if current_code_commit and current_code_commit != "unknown" and source_code_commit
                    else None
                ),
                "source_file_mtime_utc": source.file_mtime_utc,
                "source_file_mtime_ns": source.file_mtime_ns,
                "source_file_size_bytes": source.file_size_bytes,
                "source_file_sha256": source.file_sha256,
                "source_file_stable_hash": source.stable_hash,
                "age_hours": round(age_hours, 6) if age_hours is not None else None,
                "freshness_sla_hours": sla_hours,
                "policy_valid_until_utc": policy_valid_until.isoformat() if policy_valid_until else None,
                "declared_valid_until_utc": declared_valid_until.isoformat() if declared_valid_until else None,
                "effective_valid_until_utc": effective_valid_until.isoformat() if effective_valid_until else None,
                "consumption_allowed_reason": consumption_allowed_reason,
                "dependency_newer_than_consumer_count": sum(
                    1
                    for check in dependency_checks
                    if _list_of_strings(check.get("blockers"))
                ),
                "dependency_checks": dependency_checks,
                "status": "pass" if not blockers else "fail",
                "blockers": blockers,
                "required_rebuild_report": _required_rebuild_report(source_id, blockers),
                "rebuild_command": _rebuild_command(source_id, blockers),
            }
        )
    all_blockers = [blocker for row in rows for blocker in _list_of_strings(row.get("blockers"))]
    ages = [_float(row.get("age_hours")) for row in rows if row.get("age_hours") is not None]
    rebuild_plan = _freshness_rebuild_plan(rows)
    return {
        "schema_version": "btc_promotion_gate_artifact_freshness_v1",
        "status": "pass" if not all_blockers else "fail",
        "aggregation_batch_id": aggregation_batch_id,
        "source_count": len(rows),
        "checked_source_count": sum(1 for row in rows if row.get("source_generated_at_utc")),
        "missing_source_count": sum(1 for row in rows if row.get("exists") is not True),
        "timestamp_missing_count": sum(
            1
            for row in rows
            if row.get("exists") is True and not row.get("source_generated_at_utc")
        ),
        "future_source_count": sum(
            1
            for row in rows
            if any("source_newer_than_aggregate_report" in item for item in _list_of_strings(row.get("blockers")))
        ),
        "batch_missing_count": sum(
            1
            for row in rows
            if any("source_missing_aggregation_batch_without_valid_until" in item for item in _list_of_strings(row.get("blockers")))
        ),
        "batch_mismatch_count": sum(
            1
            for row in rows
            if any("source_different_aggregation_batch_without_valid_until" in item for item in _list_of_strings(row.get("blockers")))
        ),
        "dependency_newer_than_consumer_count": sum(
            _int(row.get("dependency_newer_than_consumer_count")) for row in rows
        ),
        "source_code_commit_missing_count": sum(
            1
            for row in rows
            if any("source_code_commit_missing" in item for item in _list_of_strings(row.get("blockers")))
        ),
        "source_code_commit_mismatch_count": sum(
            1
            for row in rows
            if any("source_code_commit_mismatch_current_head" in item for item in _list_of_strings(row.get("blockers")))
        ),
        "stale_source_count": sum(
            1
            for row in rows
            if any("source_artifact_stale_age_hours_gt_sla" in item for item in _list_of_strings(row.get("blockers")))
        ),
        "source_timeline_consistent": not any(
            _int(row.get("dependency_newer_than_consumer_count")) for row in rows
        ),
        "source_consumption_policies": PROMOTION_SOURCE_CONSUMPTION_POLICIES,
        "max_source_age_hours": round(max(ages), 6) if ages else None,
        "blockers": sorted(set(all_blockers)),
        "required_rebuild_reports": sorted({str(row["required_rebuild_report"]) for row in rebuild_plan}),
        "rebuild_plan": rebuild_plan,
        "sources": rows,
    }


def _source_consumption_policy(source_id: str) -> Mapping[str, Any]:
    return PROMOTION_SOURCE_CONSUMPTION_POLICIES.get(
        source_id,
        {
            "freshness_sla_hours": DEFAULT_SOURCE_FRESHNESS_SLA_HOURS,
            "batch_policy": "promotion_sla_or_declared_valid_until",
            "rebuild_command": "manual_rebuild_required",
        },
    )


def _source_dependency_checks(
    *,
    source_id: str,
    source_generated: datetime | None,
    source_generated_by_id: Mapping[str, datetime | None],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for dependency_id in PROMOTION_SOURCE_DEPENDENCIES.get(source_id, ()):
        dependency_generated = source_generated_by_id.get(dependency_id)
        blockers: list[str] = []
        lag_hours = None
        if source_generated is not None and dependency_generated is not None:
            lag_hours = (dependency_generated - source_generated).total_seconds() / 3600.0
            if lag_hours > (SOURCE_TIMELINE_SKEW_TOLERANCE_SECONDS / 3600.0):
                blockers.append(
                    f"artifact_freshness:{source_id}:dependency_source_newer_than_consumer:{dependency_id}"
                )
        checks.append(
            {
                "consumer_source_id": source_id,
                "dependency_source_id": dependency_id,
                "consumer_generated_at_utc": source_generated.isoformat() if source_generated else None,
                "dependency_generated_at_utc": dependency_generated.isoformat() if dependency_generated else None,
                "dependency_minus_consumer_hours": round(lag_hours, 6) if lag_hours is not None else None,
                "status": "pass" if not blockers else "fail",
                "blockers": blockers,
            }
        )
    return checks


def _consumption_allowed_reason(
    *,
    source_batch_id: str,
    aggregation_batch_id: str,
    declared_valid_until: datetime | None,
    policy_valid_until: datetime | None,
    generated: datetime,
) -> str:
    if source_batch_id and source_batch_id == aggregation_batch_id:
        return "same_aggregation_batch"
    if declared_valid_until is not None and generated <= declared_valid_until:
        return "source_declared_valid_until"
    if policy_valid_until is not None and generated <= policy_valid_until:
        return "promotion_freshness_sla"
    return "blocked"


def _artifact_freshness_gate(freshness: Mapping[str, Any]) -> dict[str, Any]:
    blockers = _artifact_freshness_summary_blockers(freshness)
    return _gate_row(
        gate_id="artifact_freshness_gate",
        gate_name_cn="Artifact freshness gate",
        source_ids=tuple(str(row.get("source_id")) for row in _list_of_mappings(freshness.get("sources"))),
        checks={
            "source_count": freshness.get("source_count"),
            "checked_source_count": freshness.get("checked_source_count"),
            "timestamp_missing_count": freshness.get("timestamp_missing_count"),
            "future_source_count": freshness.get("future_source_count"),
            "batch_missing_count": freshness.get("batch_missing_count"),
            "batch_mismatch_count": freshness.get("batch_mismatch_count"),
            "dependency_newer_than_consumer_count": freshness.get("dependency_newer_than_consumer_count"),
            "source_code_commit_missing_count": freshness.get("source_code_commit_missing_count"),
            "source_code_commit_mismatch_count": freshness.get("source_code_commit_mismatch_count"),
            "source_timeline_consistent": freshness.get("source_timeline_consistent"),
            "stale_source_count": freshness.get("stale_source_count"),
            "max_source_age_hours": freshness.get("max_source_age_hours"),
        },
        blockers=blockers,
        next_action_cn="按依赖顺序重建所有 stale/missing/future source artifact，再重建 promotion gate；禁止消费过期证据。",
        responsible_automation="BTC gate aggregation chain rebuild",
    )


def _artifact_freshness_summary_blockers(freshness: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if _int(freshness.get("missing_source_count")):
        blockers.append(f"artifact_freshness:missing_source_count={freshness.get('missing_source_count')}:see_rebuild_plan")
    if _int(freshness.get("timestamp_missing_count")):
        blockers.append(
            f"artifact_freshness:source_timestamp_missing_count={freshness.get('timestamp_missing_count')}:see_freshness_matrix"
        )
    if _int(freshness.get("future_source_count")):
        blockers.append(
            f"artifact_freshness:source_newer_than_aggregate_count={freshness.get('future_source_count')}:rebuild_aggregate_chain"
        )
    if _int(freshness.get("batch_missing_count")):
        blockers.append(
            f"artifact_freshness:source_batch_missing_count={freshness.get('batch_missing_count')}:rebuild_aggregate_chain"
        )
    if _int(freshness.get("batch_mismatch_count")):
        blockers.append(
            f"artifact_freshness:source_batch_mismatch_count={freshness.get('batch_mismatch_count')}:rebuild_aggregate_chain"
        )
    if _int(freshness.get("dependency_newer_than_consumer_count")):
        blockers.append(
            "artifact_freshness:"
            f"dependency_newer_than_consumer_count={freshness.get('dependency_newer_than_consumer_count')}:see_rebuild_plan"
        )
    if _int(freshness.get("source_code_commit_missing_count")):
        blockers.append(
            "artifact_freshness:"
            f"source_code_commit_missing_count={freshness.get('source_code_commit_missing_count')}:see_rebuild_plan"
        )
    if _int(freshness.get("source_code_commit_mismatch_count")):
        blockers.append(
            "artifact_freshness:"
            f"source_code_commit_mismatch_count={freshness.get('source_code_commit_mismatch_count')}:rebuild_current_head_chain"
        )
    if _int(freshness.get("stale_source_count")):
        blockers.append(
            f"artifact_freshness:source_artifact_stale_count={freshness.get('stale_source_count')}:see_rebuild_plan"
        )
    return blockers


def _artifact_consistency_gate(sources: Mapping[str, SourceLoad]) -> dict[str, Any]:
    source = sources.get("gate_report_consistency")
    payload = _mapping(source.payload) if source else {}
    summary = _mapping(payload.get("summary"))
    blockers: list[str] = []
    if source is None or not source.exists:
        blockers.append("artifact_consistency:gate_report_consistency:missing_source_report")
    elif source.error:
        blockers.append("artifact_consistency:gate_report_consistency:invalid_json")
    else:
        if str(payload.get("status") or "") != "pass":
            blockers.append("artifact_consistency:gate_report_consistency:status_not_pass")
        blockers.extend(
            f"artifact_consistency:{item}"
            for item in _list_of_strings(payload.get("blockers"))
        )
        if summary.get("dashboard_hash_matches_current_evidence") is not True:
            blockers.append(
                "artifact_consistency:dashboard_perpetual_execution_evidence_hash_mismatch"
            )
    return _gate_row(
        gate_id="artifact_consistency_gate",
        gate_name_cn="Artifact consistency gate",
        source_ids=("gate_report_consistency", "gate_dashboard", "perpetual_execution"),
        checks={
            "gate_report_consistency_status": payload.get("status", "missing"),
            "gate_report_consistency_fail_count": summary.get("fail_count"),
            "dashboard_hash_matches_current_evidence": summary.get("dashboard_hash_matches_current_evidence"),
            "dashboard_perpetual_execution_evidence_hash": summary.get(
                "dashboard_perpetual_execution_evidence_hash"
            ),
            "current_evidence_artifact_hash": summary.get("current_evidence_artifact_hash"),
        },
        blockers=sorted(set(blockers)),
        next_action_cn="重建 gate dashboard、perpetual execution evidence 和 gate report consistency，直到 dashboard 内嵌 hash 与当前 evidence artifact 一致。",
        responsible_automation="BTC gate aggregation chain rebuild",
    )


def _source_generated_at(payload: Mapping[str, Any]) -> datetime | None:
    for key in ("generated_at_utc", "generated_at", "as_of_utc", "as_of"):
        parsed = _parse_utc(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def _source_valid_until(payload: Mapping[str, Any]) -> datetime | None:
    for key in ("valid_until_utc", "source_valid_until_utc", "fresh_until_utc"):
        parsed = _parse_utc(payload.get(key))
        if parsed is not None:
            return parsed
    freshness = _mapping(payload.get("freshness"))
    for key in ("valid_until_utc", "source_valid_until_utc", "fresh_until_utc"):
        parsed = _parse_utc(freshness.get(key))
        if parsed is not None:
            return parsed
    return None


def _source_batch_id(payload: Mapping[str, Any]) -> str:
    for key in ("aggregation_batch_id", "batch_id", "run_batch_id"):
        value = payload.get(key)
        if value:
            return str(value)
    lineage = _mapping(payload.get("lineage"))
    for key in ("aggregation_batch_id", "batch_id", "run_batch_id"):
        value = lineage.get(key)
        if value:
            return str(value)
    return ""


def _source_code_commit(payload: Mapping[str, Any]) -> str:
    field = _source_code_commit_field(payload)
    if field.startswith("lineage."):
        return str(_mapping(payload.get("lineage")).get(field.split(".", 1)[1]) or "")
    return str(payload.get(field) or "") if field else ""


def _source_code_commit_field(payload: Mapping[str, Any]) -> str:
    for key in ("code_commit", "commit", "commit_hash", "git_commit", "git_sha"):
        if payload.get(key):
            return key
    lineage = _mapping(payload.get("lineage"))
    for key in ("code_commit", "commit", "commit_hash", "git_commit", "git_sha"):
        if lineage.get(key):
            return f"lineage.{key}"
    return ""


def _source_freshness_sla_hours(source_id: str) -> float:
    return PROMOTION_SOURCE_FRESHNESS_SLA_HOURS.get(source_id, DEFAULT_SOURCE_FRESHNESS_SLA_HOURS)


def _default_aggregation_batch_id(generated: datetime) -> str:
    return "btc_gate_aggregation_" + generated.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _hours_delta(hours: float):
    from datetime import timedelta

    return timedelta(hours=float(hours))


def _rebuild_command(source_id: str, blockers: Sequence[str]) -> str:
    if any("source_newer_than_aggregate_report" in item for item in blockers):
        return CHAIN_AGGREGATE_REBUILD_COMMAND
    if any("source_missing_aggregation_batch_without_valid_until" in item for item in blockers):
        return CHAIN_AGGREGATE_REBUILD_COMMAND
    if any("source_different_aggregation_batch_without_valid_until" in item for item in blockers):
        return CHAIN_AGGREGATE_REBUILD_COMMAND
    if any("dependency_source_newer_than_consumer" in item for item in blockers):
        return CHAIN_AGGREGATE_REBUILD_COMMAND
    if any("source_code_commit_" in item for item in blockers):
        return CHAIN_AGGREGATE_REBUILD_COMMAND
    return PROMOTION_SOURCE_REBUILD_COMMANDS.get(source_id, "manual_rebuild_required")


def _required_rebuild_report(source_id: str, blockers: Sequence[str]) -> str:
    if any("source_newer_than_aggregate_report" in item for item in blockers):
        return "promotion_gate_control"
    if any("source_missing_aggregation_batch_without_valid_until" in item for item in blockers):
        return source_id
    if any("source_different_aggregation_batch_without_valid_until" in item for item in blockers):
        return "promotion_gate_control"
    if any("dependency_source_newer_than_consumer" in item for item in blockers):
        return source_id
    if any("source_code_commit_" in item for item in blockers):
        return source_id
    return source_id if blockers else ""


def _freshness_rebuild_plan(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    plan = []
    for row in rows:
        blockers = _list_of_strings(row.get("blockers"))
        if not blockers:
            continue
        plan.append(
            {
                "source_id": str(row.get("source_id")),
                "required_rebuild_report": row.get("required_rebuild_report"),
                "path": row.get("path"),
                "status": row.get("status"),
                "age_hours": row.get("age_hours"),
                "freshness_sla_hours": row.get("freshness_sla_hours"),
                "effective_valid_until_utc": row.get("effective_valid_until_utc"),
                "reasons": blockers,
                "rebuild_command": row.get("rebuild_command"),
            }
        )
    return plan



def _data_gate(sources: Mapping[str, SourceLoad]) -> dict[str, Any]:
    objective = sources["perpetual_objective"].payload
    perp = sources["perpetual_execution"].payload
    blockers = _prefixed_blockers("perpetual_objective", objective)
    blockers.extend(_selected_prefixed_blockers("perpetual_execution", perp, ("data", "depth", "slippage", "mark", "index", "liquidation", "fill")))
    blockers.extend(_missing_blockers(sources, ("perpetual_objective", "perpetual_execution", "depth_slippage", "fill_mapping", "cost_model")))
    summary = _mapping(objective.get("summary"))
    checks = {
        "current_mark_price_age_hours": summary.get("current_mark_price_age_hours"),
        "two_sided_coverage_days": summary.get("two_sided_coverage_days"),
        "remaining_two_sided_coverage_days": summary.get("remaining_two_sided_coverage_days"),
        "gate_fill_count": summary.get("gate_fill_count"),
        "mapped_gate_fill_count": summary.get("mapped_gate_fill_count"),
        "depth_aware_slippage_history_verified": summary.get("depth_aware_slippage_history_verified"),
    }
    return _gate_row(
        gate_id="data_gate",
        gate_name_cn="数据 gate",
        source_ids=("perpetual_objective", "perpetual_execution", "depth_slippage", "fill_mapping", "cost_model"),
        checks=checks,
        blockers=blockers,
        next_action_cn="继续由 OKX L2 hourly 和市场/衍生品刷新任务累计 depth、mark/funding、fill mapping 证据。",
        responsible_automation="BTC OKX L2 depth accumulator hourly; BTC market and derivatives refresh daily",
    )


def _strategy_gate(sources: Mapping[str, SourceLoad]) -> dict[str, Any]:
    ledger = sources["strategy_ledger"].payload
    readiness = sources["strategy_readiness"].payload
    observe = sources["observe_only_health"].payload
    blockers = _prefixed_blockers("strategy_ledger", ledger)
    blockers.extend(_prefixed_blockers("strategy_readiness", readiness))
    blockers.extend(_prefixed_blockers("observe_only_health", observe))
    blockers.extend(_missing_blockers(sources, ("strategy_ledger", "strategy_readiness", "observe_only_health")))
    checks = {
        "strategy_line_count": ledger.get("line_count"),
        "ready_for_paper_count": _nested(readiness, "summary", "ready_for_paper_count"),
        "observe_only_minimum_30d_complete_count": _nested(observe, "summary", "minimum_30d_complete_count"),
        "observe_only_target_60d_complete_count": _nested(observe, "summary", "target_60d_complete_count"),
        "observe_only_safety_violation_count": _nested(observe, "summary", "safety_violation_count"),
    }
    return _gate_row(
        gate_id="strategy_gate",
        gate_name_cn="策略 gate",
        source_ids=("strategy_ledger", "strategy_readiness", "observe_only_health"),
        checks=checks,
        blockers=blockers,
        next_action_cn="继续 observe-only；等 30/60 天窗口完成后再做人工 paper 复核。",
        responsible_automation="BTC long-short Top5 observe-only daily; BTC attack observe-only daily; BTC high-yield v2 observe-only daily",
    )


def _risk_gate(sources: Mapping[str, SourceLoad]) -> dict[str, Any]:
    readiness = sources["strategy_readiness"].payload
    micro = sources["micro_live_preflight"].payload
    cost = sources["cost_model"].payload
    blockers = _selected_prefixed_blockers("strategy_readiness", readiness, ("risk", "margin", "leverage", "liquidation", "cost", "funding", "buffer", "circuit"))
    blockers.extend(_selected_prefixed_blockers("micro_live_preflight", micro, ("risk", "leverage", "principal", "notional", "daily_order", "kill_switch")))
    blockers.extend(_selected_prefixed_blockers("cost_model", cost, ("cost", "fee", "slippage", "funding")))
    blockers.extend(_missing_blockers(sources, ("strategy_readiness", "micro_live_preflight", "cost_model", "paper_risk_drill")))
    checks = {
        "approved_initial_principal_usdt": _nested(micro, "summary", "approved_initial_principal_usdt"),
        "paper_risk_drill_status": sources["paper_risk_drill"].payload.get("status") if sources["paper_risk_drill"].exists else "missing",
        "cost_model_status": cost.get("status"),
        "kill_switch_engaged": _nested(micro, "summary", "kill_switch_engaged"),
        "true_safety_flag_count": _nested(micro, "summary", "true_safety_flag_count"),
    }
    return _gate_row(
        gate_id="risk_gate",
        gate_name_cn="风控 gate",
        source_ids=("strategy_readiness", "micro_live_preflight", "cost_model", "paper_risk_drill"),
        checks=checks,
        blockers=blockers,
        next_action_cn="补齐风险闸门、强平/成本压力、人工批准的 size envelope；继续保持 fail-closed。",
        responsible_automation="BTC perpetual evidence daily review",
    )


def _execution_gate(sources: Mapping[str, SourceLoad]) -> dict[str, Any]:
    replay = sources["paper_runtime_replay"].payload
    reconciliation = sources["paper_runtime_reconciliation"].payload
    exchange_gap = sources["exchange_runtime_gap"].payload
    perp = sources["perpetual_execution"].payload
    blockers = _prefixed_blockers("paper_runtime_replay", replay)
    blockers.extend(_prefixed_blockers("exchange_runtime_gap", exchange_gap))
    blockers.extend(_prefixed_blockers("perpetual_execution", perp))
    blockers.extend(_selected_prefixed_blockers("paper_runtime_reconciliation", reconciliation, ("violation", "reconciliation", "ledger")))
    blockers.extend(_missing_blockers(sources, ("paper_runtime_replay", "paper_runtime_reconciliation", "exchange_runtime_gap", "perpetual_execution")))
    checks = {
        "paper_runtime_replay_ready": _nested(replay, "summary", "paper_runtime_replay_ready"),
        "simulated_fill_count": _nested(replay, "summary", "simulated_fill_count"),
        "trade_execution_evidence_available": _nested(replay, "summary", "trade_execution_evidence_available"),
        "paper_runtime_reconciliation_passed": _nested(reconciliation, "summary", "paper_runtime_reconciliation_passed"),
        "exchange_runtime_gap_status": exchange_gap.get("status"),
    }
    return _gate_row(
        gate_id="execution_gate",
        gate_name_cn="执行 gate",
        source_ids=("paper_runtime_replay", "paper_runtime_reconciliation", "exchange_runtime_gap", "perpetual_execution"),
        checks=checks,
        blockers=blockers,
        next_action_cn="等待非空 observe-only 信号产生 simulated fill；再复核 fill mapping、depth-aware slippage、exchange runtime gap。",
        responsible_automation="BTC perpetual evidence daily review; BTC OKX L2 depth accumulator hourly",
    )


def _kill_switch_gate(sources: Mapping[str, SourceLoad]) -> dict[str, Any]:
    micro = sources["micro_live_preflight"].payload
    kill = sources["kill_switch"].payload
    exchange = sources["paper_exchange_rule"].payload
    blockers = _selected_prefixed_blockers("micro_live_preflight", micro, ("kill_switch", "paper_order_intake", "manual", "cancel", "reduce", "order_sample"))
    blockers.extend(_prefixed_blockers("kill_switch", kill))
    blockers.extend(_selected_prefixed_blockers("paper_exchange_rule", exchange, ("order", "exchange", "server_time", "credential")))
    blockers.extend(_missing_blockers(sources, ("micro_live_preflight", "kill_switch", "paper_exchange_rule")))
    checks = {
        "kill_switch_engaged": _nested(micro, "summary", "kill_switch_engaged") or _nested(kill, "policy_state", "kill_switch_engaged"),
        "paper_order_intake_allowed": _nested(micro, "policy_state", "paper_order_intake_allowed"),
        "cancel_only_mode": _nested(micro, "policy_state", "cancel_only_mode"),
        "reduce_only_mode": _nested(micro, "policy_state", "reduce_only_mode"),
        "current_order_sample_status": _nested(exchange, "summary", "current_order_sample_status"),
    }
    return _gate_row(
        gate_id="kill_switch_gate",
        gate_name_cn="Kill switch gate",
        source_ids=("micro_live_preflight", "kill_switch", "paper_exchange_rule"),
        checks=checks,
        blockers=blockers,
        next_action_cn="保持 kill switch 拉闸；等 paper/runtime/order sample 和人工批准齐备后再复核。",
        responsible_automation="BTC perpetual evidence daily review",
    )


def _drawdown_stress_gate(sources: Mapping[str, SourceLoad]) -> dict[str, Any]:
    leakage = sources["leakage_overfit"].payload
    readiness = sources["strategy_readiness"].payload
    blockers = _selected_prefixed_blockers("strategy_readiness", readiness, ("drawdown", "stress", "funding", "cost", "high_octane", "high_yield", "margin", "threshold"))
    if "overfit_risk_high" in str(_nested(leakage, "summary", "decision")):
        blockers.append("leakage_overfit:high_octane_overfit_risk_high")
    if _nested(leakage, "summary", "high_octane_likely_parameter_mined_boundary_candidate") is True:
        blockers.append("leakage_overfit:high_octane_boundary_candidate")
    blockers.extend(_missing_blockers(sources, ("leakage_overfit", "strategy_readiness")))
    checks = {
        "high_octane_best_margin_over_40pct_threshold": _nested(leakage, "summary", "high_octane_best_margin_over_40pct_threshold"),
        "high_octane_parameter_mining_verdict": _nested(leakage, "summary", "high_octane_parameter_mining_verdict"),
        "data_coverage_liquidation_one_hour_history_complete": _nested(leakage, "summary", "data_coverage_liquidation_one_hour_history_complete"),
        "paper_runtime_trade_execution_evidence_available": _nested(readiness, "summary", "paper_runtime_trade_execution_evidence_available"),
    }
    return _gate_row(
        gate_id="drawdown_stress_gate",
        gate_name_cn="回撤/压力 gate",
        source_ids=("leakage_overfit", "strategy_readiness"),
        checks=checks,
        blockers=blockers,
        next_action_cn="继续做行情分段、回撤、插针、funding/cost 压力复核；压线候选不能晋级。",
        responsible_automation="observe-only reports plus manual research review",
    )


def _leakage_overfit_gate(sources: Mapping[str, SourceLoad]) -> dict[str, Any]:
    leakage = sources["leakage_overfit"].payload
    bar = sources["bar_replay"].payload
    blockers = _prefixed_blockers("leakage_overfit", leakage) if str(leakage.get("status", "")).startswith("blocked") else []
    if _int(_nested(leakage, "summary", "check_fail_count")) > 0:
        blockers.append("leakage_overfit:check_fail_count_gt_0")
    if "overfit_risk_high" in str(leakage.get("decision", "")):
        blockers.append("leakage_overfit:research_only_overfit_risk_high")
    if _int(_nested(bar, "summary", "check_fail_count")) > 0:
        blockers.append("bar_replay:check_fail_count_gt_0")
    blockers.extend(_missing_blockers(sources, ("leakage_overfit", "bar_replay")))
    checks = {
        "leakage_check_fail_count": _nested(leakage, "summary", "check_fail_count"),
        "leakage_check_warn_count": _nested(leakage, "summary", "check_warn_count"),
        "long_short_overfit_verdict": _nested(leakage, "summary", "long_short_overfit_verdict"),
        "high_octane_overfit_verdict": _nested(leakage, "summary", "high_octane_overfit_verdict"),
        "bar_replay_check_fail_count": _nested(bar, "summary", "check_fail_count"),
    }
    return _gate_row(
        gate_id="leakage_overfit_gate",
        gate_name_cn="未来函数/过拟合 gate",
        source_ids=("leakage_overfit", "bar_replay"),
        checks=checks,
        blockers=blockers,
        next_action_cn="继续保留 holdout 锁；高风险参数挖掘候选只能 research-only。",
        responsible_automation="manual research audit",
    )


def _manual_review_gate(sources: Mapping[str, SourceLoad], *, current_blocked: bool) -> dict[str, Any]:
    paper = sources["paper_readiness"].payload
    micro = sources["micro_live_preflight"].payload
    packet = sources["manual_packet"].payload
    api_key = sources["api_key_audit"].payload
    attestation = sources["account_attestation"].payload
    approval = sources["manual_paper_review_approval"].payload
    blockers = _missing_blockers(
        sources,
        (
            "paper_readiness",
            "micro_live_preflight",
            "manual_packet",
            "api_key_audit",
            "account_attestation",
            "manual_paper_review_approval",
        ),
    )
    if _legacy_paper_conflict(sources, current_blocked=current_blocked):
        blockers.append("manual_review:legacy_paper_readiness_approved_but_current_gate_blocked")
    if _nested(micro, "summary", "manual_approval_recorded") is not True:
        blockers.append("manual_review:manual_approval_missing")
    if approval.get("manual_approval_recorded") is not True:
        blockers.append("manual_review:manual_paper_review_approval_record_missing")
    if approval.get("manual_review_missing_cleared") is not True:
        blockers.append("manual_review:manual_paper_review_missing_not_cleared")
    blockers.extend(f"manual_paper_review_approval:{item}" for item in _list_of_strings(approval.get("blockers")))
    if approval.get("paper_queue_write_allowed") is True or approval.get("live_unlock_allowed") is True:
        blockers.append("manual_review:manual_paper_review_approval_has_unlock_flag")
    if str(paper.get("paper_queue_status", "")) not in {"pending_review", "approved"}:
        blockers.extend(_prefixed_blockers("paper_readiness", paper))
    blockers.extend(_api_key_audit_blockers(api_key))
    blockers.extend(_account_attestation_blockers(attestation))
    checks = {
        "paper_readiness_status": paper.get("status"),
        "paper_readiness_queue_status": paper.get("paper_queue_status"),
        "paper_readiness_paper_start_allowed": paper.get("paper_start_allowed"),
        "manual_approval_recorded": _nested(micro, "summary", "manual_approval_recorded"),
        "operator_packet_exists": sources["manual_packet"].exists,
        "api_key_permission_reviewed": _nested(packet, "api_key_permission_reviewed"),
        "api_key_audit_status": api_key.get("status"),
        "api_key_audit_decision": api_key.get("decision"),
        "api_key_audit_blocker_count": len(_list_of_strings(api_key.get("blockers"))),
        "account_attestation_status": attestation.get("status"),
        "account_attestation_current": attestation.get("attestation_current"),
        "account_attestation_manual_only": _nested(attestation, "gate", "manual_attestation_only"),
        "account_attestation_manual_approval_recorded": attestation.get("manual_approval_recorded"),
        "account_attestation_credential_permissions_verified": attestation.get("credential_permissions_verified"),
        "account_attestation_credential_separation_verified": attestation.get("credential_separation_verified"),
        "manual_paper_review_approval_status": approval.get("status"),
        "manual_paper_review_approval_recorded": approval.get("manual_approval_recorded"),
        "manual_paper_review_missing_cleared": approval.get("manual_review_missing_cleared"),
        "manual_paper_review_packet_sha256": _nested(approval, "reviewed_packet", "sha256"),
    }
    return _gate_row(
        gate_id="manual_review_gate",
        gate_name_cn="人工复核 gate",
        source_ids=(
            "paper_readiness",
            "micro_live_preflight",
            "manual_packet",
            "api_key_audit",
            "account_attestation",
            "manual_paper_review_approval",
        ),
        checks=checks,
        blockers=blockers,
        next_action_cn="旧 paper approval 不能覆盖当前 gate；需要当前证据链全绿后重新人工复核。",
        responsible_automation="manual reviewer / operator packet",
    )


def _api_key_audit_blockers(payload: Mapping[str, Any]) -> list[str]:
    if not payload:
        return []
    blockers = [f"api_key_audit:{item}" for item in _list_of_strings(payload.get("blockers"))]
    status = str(payload.get("status") or "").lower()
    if status not in {"complete", "complete_research_only", "verified_research_only"}:
        blockers.append(f"api_key_audit:status:{payload.get('status')}")
    if str(payload.get("decision") or "") != "api_key_permissions_ready_for_paper_only":
        blockers.append(f"api_key_audit:decision:{payload.get('decision')}")
    return sorted(set(blockers))


def _account_attestation_blockers(payload: Mapping[str, Any]) -> list[str]:
    if not payload:
        return []
    blockers = [f"account_attestation:{item}" for item in _list_of_strings(payload.get("blockers"))]
    if str(payload.get("status") or "") != "verified_research_only":
        blockers.append(f"account_attestation:status:{payload.get('status')}")
    required_true = (
        ("attestation_current", payload.get("attestation_current")),
        ("credential_permissions_verified", payload.get("credential_permissions_verified")),
        ("credential_separation_verified", payload.get("credential_separation_verified")),
        ("manual_attestation_only", _nested(payload, "gate", "manual_attestation_only")),
    )
    for name, value in required_true:
        if value is not True:
            blockers.append(f"account_attestation:{name}_not_true")
    if _nested(payload, "gate", "paper_order_intake_allowed") is True:
        blockers.append("account_attestation:paper_order_intake_allowed_true")
    if _nested(payload, "gate", "live_unlock_allowed") is True:
        blockers.append("account_attestation:live_unlock_allowed_true")
    return sorted(set(blockers))


def _gate_row(
    *,
    gate_id: str,
    gate_name_cn: str,
    source_ids: Sequence[str],
    checks: Mapping[str, Any],
    blockers: Sequence[str],
    next_action_cn: str,
    responsible_automation: str,
) -> dict[str, Any]:
    unique_blockers = sorted(set(str(item) for item in blockers if str(item)))
    return {
        "gate_id": gate_id,
        "gate_name_cn": gate_name_cn,
        "status": "pass" if not unique_blockers else "blocked",
        "source_ids": list(source_ids),
        "checks": dict(checks),
        "blockers": unique_blockers,
        "next_action_cn": next_action_cn,
        "responsible_automation": responsible_automation,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
    }


def _build_root_cause_dag(matrix: Sequence[Mapping[str, Any]], safety_violations: Sequence[str]) -> dict[str, Any]:
    blockers_by_gate = {
        str(row.get("gate_id")): _list_of_strings(row.get("blockers"))
        for row in matrix
        if str(row.get("gate_id"))
    }
    gate_sources = {
        str(row.get("gate_id")): _list_of_strings(row.get("source_ids"))
        for row in matrix
        if str(row.get("gate_id"))
    }
    if safety_violations:
        blockers_by_gate["safety_fail_closed"] = [f"safety_violation:{item}" for item in safety_violations]
        gate_sources["safety_fail_closed"] = ["source_safety_violations"]
    return build_btc_root_cause_dag(
        blockers_by_gate,
        gate_sources=gate_sources,
        root_node_id="btc_promotion_gate_blocked",
    )


def _current_evidence_blocked(sources: Mapping[str, SourceLoad]) -> bool:
    current_ids = (
        "perpetual_objective",
        "strategy_ledger",
        "strategy_readiness",
        "observe_only_health",
        "paper_runtime_replay",
        "exchange_runtime_gap",
        "perpetual_execution",
        "micro_live_preflight",
        "gate_dashboard",
    )
    for source_id in current_ids:
        source = sources[source_id]
        status = str(source.payload.get("status", "")).lower()
        if not source.exists or source.error:
            return True
        if status.startswith(("blocked", "incomplete", "safety_violation")):
            return True
        if source.payload.get("blockers"):
            return True
    return False


def _legacy_paper_conflict(sources: Mapping[str, SourceLoad], *, current_blocked: bool) -> bool:
    paper = sources["paper_readiness"].payload
    return current_blocked and (
        paper.get("paper_start_allowed") is True
        or paper.get("paper_execution_authorized") is True
        or str(paper.get("paper_queue_status", "")) == "approved"
    )


def _source_safety_violations(sources: Mapping[str, SourceLoad]) -> list[str]:
    violations: list[str] = []
    for source_id, source in sources.items():
        for path in _unsafe_true_paths(source.payload):
            violations.append(f"{source_id}:{path}")
        if source_id == "order_surface_audit":
            for blocker in _list_of_strings(source.payload.get("blockers")):
                violations.append(f"{source_id}:{blocker}")
            for finding in _list_of_mappings(source.payload.get("findings")):
                rule = str(finding.get("rule") or "unknown_rule")
                path = str(finding.get("path") or "unknown_path")
                line = str(finding.get("line") or "0")
                violations.append(f"{source_id}:finding:{path}:{line}:{rule}")
    return sorted(set(violations))


def _key_blockers_cn(sources: Mapping[str, SourceLoad], matrix: Sequence[Mapping[str, Any]]) -> list[str]:
    objective_summary = _mapping(_nested(sources["perpetual_objective"].payload, "summary"))
    replay_summary = _mapping(_nested(sources["paper_runtime_replay"].payload, "summary"))
    observe_summary = _mapping(_nested(sources["observe_only_health"].payload, "summary"))
    items: list[str] = []
    freshness_row = next((row for row in matrix if row.get("gate_id") == "artifact_freshness_gate"), {})
    freshness_checks = _mapping(freshness_row.get("checks"))
    freshness_blocker_count = sum(
        _int(freshness_checks.get(key))
        for key in (
            "stale_source_count",
            "future_source_count",
            "batch_missing_count",
            "batch_mismatch_count",
            "dependency_newer_than_consumer_count",
            "timestamp_missing_count",
        )
    )
    if freshness_blocker_count:
        items.append(
            "artifact freshness / gate 编排不一致："
            f"stale={freshness_checks.get('stale_source_count')}, "
            f"future={freshness_checks.get('future_source_count')}, "
            f"batch_missing={freshness_checks.get('batch_missing_count')}, "
            f"batch_mismatch={freshness_checks.get('batch_mismatch_count')}, "
            f"dependency_newer={freshness_checks.get('dependency_newer_than_consumer_count')}；"
            "先按 freshness_rebuild_plan 重建上游报告。"
        )
    if _float(objective_summary.get("remaining_two_sided_coverage_days")) > 0:
        items.append(
            f"OKX depth 未满 14 天，还差约 {objective_summary.get('remaining_two_sided_coverage_days')} 天。"
        )
    if _int(objective_summary.get("gate_fill_count")) == 0:
        items.append("gate fill 为 0，暂无可映射到盘口的策略成交样本。")
    if objective_summary.get("depth_aware_slippage_history_verified") is not True:
        items.append("depth-aware slippage 还未通过历史验证。")
    if _int(observe_summary.get("minimum_30d_complete_count")) <= 0:
        items.append("observe-only 尚未满 30/60 天，不能作为 paper 证据。")
    if _int(replay_summary.get("simulated_fill_count")) == 0:
        items.append("execution replay 当前没有真实策略模拟成交，只是 flat heartbeat。")
    if any(row["gate_id"] == "manual_review_gate" and row["blockers"] for row in matrix):
        items.append("旧 paper readiness approval 与当前 gate blocked 冲突，必须 fail-closed。")
    return items


def _all_blockers(matrix: Sequence[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for row in matrix:
        gate_id = str(row.get("gate_id"))
        blockers.extend(f"{gate_id}:{item}" for item in _list_of_strings(row.get("blockers")))
    return blockers


def _prefixed_blockers(source_id: str, payload: Mapping[str, Any]) -> list[str]:
    return [f"{source_id}:{item}" for item in _list_of_strings(payload.get("blockers"))]


def _selected_prefixed_blockers(source_id: str, payload: Mapping[str, Any], tokens: Sequence[str]) -> list[str]:
    lower_tokens = tuple(token.lower() for token in tokens)
    return [
        f"{source_id}:{item}"
        for item in _list_of_strings(payload.get("blockers"))
        if any(token in item.lower() for token in lower_tokens)
    ]


def _missing_blockers(sources: Mapping[str, SourceLoad], source_ids: Sequence[str]) -> list[str]:
    blockers = []
    for source_id in source_ids:
        source = sources[source_id]
        if not source.exists:
            blockers.append(f"{source_id}:missing_source_report")
        elif source.error:
            blockers.append(f"{source_id}:invalid_json:{source.error}")
    return blockers


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _guardrails() -> dict[str, Any]:
    return {
        "read_only_artifact_aggregation": True,
        "network_collection_used": False,
        "strategy_rerun_used": False,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_promotion_gate_control_safety_status_v1",
        "status": "research_only",
        "source_report": _nested(report, "outputs", "json"),
        "gate_count": report.get("gate_count"),
        "blocked_gate_count": report.get("blocked_gate_count"),
        "safety_violation_count": report.get("safety_violation_count"),
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
        "strategy_skeleton_generated": False,
    }


def _read_source(root: Path, source_id: str, path: Path) -> SourceLoad:
    resolved = _resolve(root, path)
    if not resolved.exists():
        return SourceLoad(source_id=source_id, path=path, payload={}, exists=False, error=None)
    stat = resolved.stat()
    mtime_utc = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    file_sha256 = _file_sha256(resolved)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return SourceLoad(
            source_id=source_id,
            path=path,
            payload={},
            exists=True,
            error=str(exc),
            file_mtime_utc=mtime_utc,
            file_mtime_ns=stat.st_mtime_ns,
            file_size_bytes=stat.st_size,
            file_sha256=file_sha256,
        )
    if not isinstance(payload, Mapping):
        return SourceLoad(
            source_id=source_id,
            path=path,
            payload={},
            exists=True,
            error="json_root_not_object",
            file_mtime_utc=mtime_utc,
            file_mtime_ns=stat.st_mtime_ns,
            file_size_bytes=stat.st_size,
            file_sha256=file_sha256,
        )
    payload_dict = dict(payload)
    return SourceLoad(
        source_id=source_id,
        path=path,
        payload=payload_dict,
        exists=True,
        error=None,
        file_mtime_utc=mtime_utc,
        file_mtime_ns=stat.st_mtime_ns,
        file_size_bytes=stat.st_size,
        file_sha256=file_sha256,
        stable_hash=stable_payload_hash(payload_dict),
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_matrix_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    columns = [
        "gate_id",
        "gate_name_cn",
        "status",
        "source_ids",
        "root_cause_ids",
        "blockers",
        "next_action_cn",
        "responsible_automation",
        "paper_queue_write_allowed",
        "paper_allowed",
        "live_unlock_allowed",
        "broker_or_order_allowed",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **{key: row.get(key) for key in columns},
                    "source_ids": ";".join(_list_of_strings(row.get("source_ids"))),
                    "root_cause_ids": ";".join(_list_of_strings(row.get("root_cause_ids"))),
                    "blockers": ";".join(_list_of_strings(row.get("blockers"))),
                }
            )


def _write_root_cause_matrix_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    columns = [
        "root_cause_id",
        "category",
        "label_cn",
        "raw_blocker_count",
        "unique_blocker_count",
        "affected_gates",
        "source_ids",
        "blocker_examples",
        "next_action_cn",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **{key: row.get(key) for key in columns},
                    "affected_gates": ";".join(_list_of_strings(row.get("affected_gates"))),
                    "source_ids": ";".join(_list_of_strings(row.get("source_ids"))),
                    "blocker_examples": ";".join(_list_of_strings(row.get("blocker_examples"))),
                }
            )


def _write_freshness_matrix_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    columns = [
        "source_id",
        "path",
        "exists",
        "freshness_policy",
        "source_generated_at_utc",
        "aggregate_generated_at_utc",
        "aggregation_batch_id",
        "source_aggregation_batch_id",
        "same_aggregation_batch",
        "commit_policy",
        "current_code_commit",
        "source_code_commit",
        "source_code_commit_field",
        "source_code_commit_matches_current_head",
        "source_file_mtime_utc",
        "source_file_mtime_ns",
        "source_file_size_bytes",
        "source_file_sha256",
        "source_file_stable_hash",
        "age_hours",
        "freshness_sla_hours",
        "policy_valid_until_utc",
        "declared_valid_until_utc",
        "effective_valid_until_utc",
        "consumption_allowed_reason",
        "dependency_newer_than_consumer_count",
        "status",
        "blockers",
        "required_rebuild_report",
        "rebuild_command",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **{key: row.get(key) for key in columns},
                    "blockers": ";".join(_list_of_strings(row.get("blockers"))),
                }
            )


def _unsafe_true_paths(value: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            if key in DANGEROUS_TRUE_KEYS and child is True:
                paths.append(child_path)
            paths.extend(_unsafe_true_paths(child, child_path))
    elif isinstance(value, list):
        for idx, child in enumerate(value[:300]):
            paths.extend(_unsafe_true_paths(child, f"{prefix}[{idx}]"))
    return paths


def _checks_cell(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "-"
    parts = []
    for key, item in value.items():
        if item is not None:
            parts.append(f"{key}={item}")
    return "; ".join(parts[:8]) if parts else "-"


def _limited_cell(values: Sequence[str], *, limit: int) -> str:
    items = [item for item in values if item]
    if not items:
        return "无"
    shown = items[:limit]
    suffix = f"；另有 {len(items) - limit} 项见 JSON/CSV" if len(items) > limit else ""
    return "；".join(shown) + suffix


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _portable_path(path: Path | str | None) -> str | None:
    if path is None:
        return None
    return str(path).replace("\\", "/")


def _git(args: Sequence[str], *, cwd: Path) -> str:
    try:
        top_level = subprocess.run(
            ["git", "rev-parse", "--show-prefix"],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if top_level.returncode != 0 or top_level.stdout.strip():
            return "unknown"
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True, timeout=5)
    except Exception:
        return "unknown"
    value = result.stdout.strip()
    return value or "unknown"


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float)) and str(item)]


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _md(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ")
