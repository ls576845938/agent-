from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.btc_promotion_gate_control import (
    DEFAULT_SOURCE_PATHS,
    FORBIDDEN_DIRECT_RESEARCH_SOURCE_PATTERNS,
    GATE_IDS,
    PROMOTION_ALLOWED_RESEARCH_BRIDGE_SOURCE_IDS,
    PROMOTION_SOURCE_CONSUMPTION_POLICIES,
    PROMOTION_SOURCE_FRESHNESS_SLA_HOURS,
    build_btc_promotion_gate_control,
)


TS = datetime(2026, 7, 2, tzinfo=timezone.utc)
BATCH_ID = "btc_gate_aggregation_20260702T000000Z"
FIXTURE_CODE_COMMIT = "head123"


def test_btc_promotion_gate_control_has_freshness_sla_for_every_source() -> None:
    assert set(PROMOTION_SOURCE_FRESHNESS_SLA_HOURS) == set(DEFAULT_SOURCE_PATHS)
    assert set(PROMOTION_SOURCE_CONSUMPTION_POLICIES) == set(DEFAULT_SOURCE_PATHS)
    assert all(
        PROMOTION_SOURCE_CONSUMPTION_POLICIES[source_id]["freshness_sla_hours"] > 0
        for source_id in DEFAULT_SOURCE_PATHS
    )
    assert PROMOTION_SOURCE_CONSUMPTION_POLICIES["gate_dashboard"]["batch_policy"] == "same_batch_or_declared_valid_until"
    assert (
        PROMOTION_SOURCE_CONSUMPTION_POLICIES["strategy_ledger"]["batch_policy"]
        == "promotion_sla_or_declared_valid_until"
    )
    assert "strategy_ledger" in PROMOTION_ALLOWED_RESEARCH_BRIDGE_SOURCE_IDS
    assert "leakage_overfit" in PROMOTION_ALLOWED_RESEARCH_BRIDGE_SOURCE_IDS
    assert "btc_high_octane_attack_sleeve_lab" in FORBIDDEN_DIRECT_RESEARCH_SOURCE_PATTERNS
    assert not any(
        pattern in str(path).replace("\\", "/").lower()
        for path in DEFAULT_SOURCE_PATHS.values()
        for pattern in FORBIDDEN_DIRECT_RESEARCH_SOURCE_PATTERNS
    )


def test_btc_promotion_gate_control_generates_gate_matrix_and_blocks_current_depth_fill_gap(tmp_path: Path) -> None:
    paths = _write_current_like_sources(tmp_path)
    report = build_btc_promotion_gate_control(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        source_paths=paths,
        generated_at_utc=TS,
        aggregation_batch_id=BATCH_ID,
    )

    assert report["schema_version"] == "btc_promotion_gate_control_v1"
    assert "code_commit" in report
    assert report["dirty_state_summary"]["is_dirty"] is False
    assert report["status"] == "safety_violation_fail_closed"
    assert report["decision"] == "btc_promotion_gate_control_safety_violation_fail_closed_no_paper_no_live"
    assert report["gate_count"] == 10
    assert {row["gate_id"] for row in report["gate_matrix"]} == set(GATE_IDS)
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["gate"]["broker_or_order_allowed"] is False
    assert report["root_cause_dag"]["schema_version"] == "btc_root_cause_dag_v1"
    assert report["root_cause_summary"]["raw_blocker_count"] > report["root_cause_summary"]["root_cause_count"]
    assert report["root_cause_task_queue"]["schema_version"] == "btc_root_cause_task_queue_v1"
    assert report["root_cause_task_queue"]["dashboard_should_show_root_causes_only"] is True
    assert report["root_cause_task_queue"]["data_wait_items"]
    assert report["root_cause_task_queue"]["immediate_development_items"]
    isolation = report["research_promotion_isolation"]
    assert isolation["schema_version"] == "btc_research_promotion_isolation_v1"
    assert isolation["status"] == "pass"
    assert isolation["direct_research_sources"] == []
    assert {row["source_id"] for row in isolation["bridge_sources"]} == PROMOTION_ALLOWED_RESEARCH_BRIDGE_SOURCE_IDS
    for row in report["root_cause_matrix"]:
        assert row["owner"]
        assert row["source_reports"]
        assert row["next_command"]
        assert row["acceptance_criteria"]
    root_ids = {row["root_cause_id"] for row in report["root_cause_matrix"]}
    assert {
        "data_wait",
        "runtime_not_connected",
        "strategy_overfit_or_forward_gap",
        "manual_review_approval_missing",
        "safety_fail_closed",
    } <= root_ids

    data_gate = _gate(report, "data_gate")
    assert data_gate["status"] == "blocked"
    assert "data_wait" in data_gate["root_cause_ids"]
    assert "runtime_ready_waiting_non_flat_sample" in data_gate["root_cause_ids"]
    assert any("depth_history_coverage_window_satisfied" in item for item in data_gate["blockers"])
    assert data_gate["checks"]["gate_fill_count"] == 0
    assert data_gate["checks"]["depth_aware_slippage_history_verified"] is False
    freshness_gate = _gate(report, "artifact_freshness_gate")
    assert freshness_gate["status"] == "pass"
    assert freshness_gate["checks"]["source_count"] == 26
    assert freshness_gate["checks"]["stale_source_count"] == 0
    assert freshness_gate["checks"]["future_source_count"] == 0
    assert freshness_gate["checks"]["batch_missing_count"] == 0
    assert freshness_gate["checks"]["dependency_newer_than_consumer_count"] == 0
    assert freshness_gate["checks"]["source_code_commit_missing_count"] == 0
    assert freshness_gate["checks"]["source_code_commit_mismatch_count"] == 0
    assert freshness_gate["checks"]["source_timeline_consistent"] is True
    assert report["artifact_freshness"]["required_rebuild_reports"] == []

    manual_gate = _gate(report, "manual_review_gate")
    assert "manual_review:legacy_paper_readiness_approved_but_current_gate_blocked" in manual_gate["blockers"]
    assert "manual_review:manual_approval_missing" in manual_gate["blockers"]
    assert "manual_review:manual_paper_review_approval_record_missing" in manual_gate["blockers"]
    assert manual_gate["checks"]["api_key_audit_status"] == "complete"
    assert manual_gate["checks"]["account_attestation_status"] == "verified_research_only"
    assert manual_gate["checks"]["account_attestation_current"] is True
    assert manual_gate["checks"]["account_attestation_manual_only"] is True
    assert not any("api_key_audit:" in item for item in manual_gate["blockers"])
    assert not any("account_attestation:" in item for item in manual_gate["blockers"])
    assert any("OKX depth 未满" in item for item in report["key_blockers_cn"])
    assert any("gate fill 为 0" in item for item in report["key_blockers_cn"])
    assert any("execution replay 当前没有真实策略模拟成交" in item for item in report["key_blockers_cn"])

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert (tmp_path / "out" / "btc_promotion_gate_control_root_cause_dag.json").exists()
    assert (tmp_path / "out" / "btc_promotion_gate_control_root_cause_matrix.csv").exists()
    assert (tmp_path / "out" / "btc_promotion_gate_control_artifact_freshness_matrix.csv").exists()
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["paper_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_or_order_allowed"] is False

    summary = (tmp_path / "out" / "btc_promotion_gate_control_summary_cn.md").read_text(encoding="utf-8")
    for text in ("数据 gate", "策略 gate", "风控 gate", "执行 gate", "Kill switch gate", "回撤/压力 gate", "未来函数/过拟合 gate", "人工复核 gate"):
        assert text in summary
    assert "不写 paper 队列，不解锁 live" in summary
    assert "工作区边界" in summary
    assert "never-commit" in summary


def test_btc_promotion_gate_control_fails_closed_if_raw_research_lab_is_direct_source(tmp_path: Path) -> None:
    paths = _write_current_like_sources(tmp_path, paper_readiness_approved=False)
    direct_lab_path = tmp_path / "artifacts" / "btc_high_octane_attack_sleeve_lab" / "latest" / "report.json"
    _write_json(direct_lab_path, {"status": "complete_research_only", "blockers": [], "gate": _safe_gate()})
    paths["direct_high_octane_raw_lab"] = direct_lab_path

    report = build_btc_promotion_gate_control(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        source_paths=paths,
        generated_at_utc=TS,
        aggregation_batch_id=BATCH_ID,
    )

    isolation = report["research_promotion_isolation"]
    assert isolation["status"] == "fail"
    assert len(isolation["direct_research_sources"]) == 1
    direct = isolation["direct_research_sources"][0]
    assert direct["source_id"] == "direct_high_octane_raw_lab"
    assert direct["path"].endswith("artifacts/btc_high_octane_attack_sleeve_lab/latest/report.json")
    assert direct["matched_patterns"] == ["btc_high_octane_attack_sleeve_lab"]
    assert "direct_research_artifact_source:direct_high_octane_raw_lab" in isolation["blockers"]
    assert (
        "research_promotion_isolation:direct_research_artifact_source:direct_high_octane_raw_lab"
        in report["safety_violations"]
    )
    assert report["status"] == "safety_violation_fail_closed"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_btc_promotion_gate_control_keeps_missing_source_dimension(tmp_path: Path) -> None:
    paths = _write_current_like_sources(tmp_path)
    paths["leakage_overfit"] = tmp_path / "missing_leakage.json"
    report = build_btc_promotion_gate_control(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        source_paths=paths,
        generated_at_utc=TS,
        aggregation_batch_id=BATCH_ID,
    )

    assert report["missing_source_count"] == 1
    freshness_gate = _gate(report, "artifact_freshness_gate")
    assert "artifact_freshness:missing_source_count=1:see_rebuild_plan" in freshness_gate["blockers"]
    assert "artifact_freshness:leakage_overfit:missing_source_report" in report["artifact_freshness"]["blockers"]
    assert report["artifact_freshness"]["required_rebuild_reports"] == ["leakage_overfit"]
    leakage_gate = _gate(report, "leakage_overfit_gate")
    assert leakage_gate["status"] == "blocked"
    assert "leakage_overfit:missing_source_report" in leakage_gate["blockers"]
    assert "source_artifact_missing" in leakage_gate["root_cause_ids"]
    assert "source_artifact_missing" in {row["root_cause_id"] for row in report["root_cause_matrix"]}
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_btc_promotion_gate_control_fails_closed_on_stale_or_future_source_artifact(tmp_path: Path) -> None:
    paths = _write_current_like_sources(tmp_path, paper_readiness_approved=False)
    stale = TS - timedelta(hours=25)
    future = TS + timedelta(minutes=5)
    _write_json(
        paths["paper_runtime_replay"],
        {
            "status": "incomplete_research_only",
            "blockers": ["btc_perpetual_paper_runtime_replay_no_simulated_fills"],
            "summary": {"simulated_fill_count": 0},
            "gate": _safe_gate(),
        },
        generated_at_utc=stale,
    )
    _write_json(
        paths["cost_model"],
        {"status": "pass", "blockers": [], "gate": _safe_gate()},
        generated_at_utc=future,
    )

    report = build_btc_promotion_gate_control(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        source_paths=paths,
        generated_at_utc=TS,
        aggregation_batch_id=BATCH_ID,
    )

    freshness_gate = _gate(report, "artifact_freshness_gate")
    assert freshness_gate["status"] == "blocked"
    assert freshness_gate["checks"]["stale_source_count"] == 1
    assert freshness_gate["checks"]["future_source_count"] == 1
    assert freshness_gate["checks"]["dependency_newer_than_consumer_count"] == 1
    assert "artifact_freshness:source_artifact_stale_count=1:see_rebuild_plan" in freshness_gate["blockers"]
    assert "artifact_freshness:source_newer_than_aggregate_count=1:rebuild_aggregate_chain" in freshness_gate["blockers"]
    assert (
        "artifact_freshness:dependency_newer_than_consumer_count=1:see_rebuild_plan"
        in freshness_gate["blockers"]
    )
    assert "artifact_freshness:paper_runtime_replay:source_artifact_stale_age_hours_gt_sla" in report["artifact_freshness"]["blockers"]
    assert "artifact_freshness:cost_model:source_newer_than_aggregate_report" in report["artifact_freshness"]["blockers"]
    assert "artifact_freshness:gate_dashboard:dependency_source_newer_than_consumer:cost_model" in report["artifact_freshness"]["blockers"]
    assert set(report["artifact_freshness"]["required_rebuild_reports"]) == {
        "gate_dashboard",
        "paper_runtime_replay",
        "promotion_gate_control",
    }
    plan = {row["source_id"]: row for row in report["freshness_rebuild_plan"]}
    assert plan["paper_runtime_replay"]["required_rebuild_report"] == "paper_runtime_replay"
    assert plan["cost_model"]["required_rebuild_report"] == "promotion_gate_control"
    assert plan["gate_dashboard"]["required_rebuild_report"] == "gate_dashboard"
    assert plan["paper_runtime_replay"]["rebuild_command"] == "py scripts/build_btc_perpetual_paper_runtime_replay_report.py"
    assert plan["cost_model"]["rebuild_command"] == "py scripts/build_btc_gate_aggregation_chain.py"
    assert plan["gate_dashboard"]["rebuild_command"] == "py scripts/build_btc_gate_aggregation_chain.py"
    assert "source_artifact_stale" in freshness_gate["root_cause_ids"]
    assert "source_artifact_stale" in {row["root_cause_id"] for row in report["root_cause_matrix"]}
    assert any("artifact_freshness_gate" in item for item in report["blockers"])
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_btc_promotion_gate_control_allows_explicit_source_valid_until(tmp_path: Path) -> None:
    paths = _write_current_like_sources(tmp_path, paper_readiness_approved=False)
    old = TS - timedelta(hours=96)
    _write_json(
        paths["paper_runtime_replay"],
        {
            "status": "incomplete_research_only",
            "blockers": ["btc_perpetual_paper_runtime_replay_no_simulated_fills"],
            "summary": {"simulated_fill_count": 0},
            "freshness": {"valid_until_utc": (TS + timedelta(hours=1)).isoformat()},
            "gate": _safe_gate(),
        },
        generated_at_utc=old,
    )

    report = build_btc_promotion_gate_control(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        source_paths=paths,
        generated_at_utc=TS,
        aggregation_batch_id=BATCH_ID,
    )

    freshness_gate = _gate(report, "artifact_freshness_gate")
    assert freshness_gate["checks"]["stale_source_count"] == 0
    replay_row = next(row for row in report["artifact_freshness"]["sources"] if row["source_id"] == "paper_runtime_replay")
    assert replay_row["declared_valid_until_utc"] == (TS + timedelta(hours=1)).isoformat()
    assert replay_row["status"] == "pass"


def test_btc_promotion_gate_control_fails_when_dependency_is_newer_than_consumer(tmp_path: Path) -> None:
    paths = _write_current_like_sources(tmp_path, paper_readiness_approved=False)
    _write_json(
        paths["exchange_runtime_gap"],
        {
            "status": "incomplete_research_only",
            "blockers": ["btc_runtime_contract_local_fixture_only_public_or_paper_runtime_layer_required"],
            "gate": _safe_gate(),
        },
        generated_at_utc=TS + timedelta(hours=1),
    )

    report = build_btc_promotion_gate_control(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        source_paths=paths,
        generated_at_utc=TS + timedelta(hours=2),
        aggregation_batch_id=BATCH_ID,
    )

    freshness_gate = _gate(report, "artifact_freshness_gate")
    assert freshness_gate["status"] == "blocked"
    assert freshness_gate["checks"]["dependency_newer_than_consumer_count"] == 2
    assert freshness_gate["checks"]["source_timeline_consistent"] is False
    assert (
        "artifact_freshness:dependency_newer_than_consumer_count=2:see_rebuild_plan"
        in freshness_gate["blockers"]
    )
    assert (
        "artifact_freshness:micro_live_preflight:dependency_source_newer_than_consumer:exchange_runtime_gap"
        in report["artifact_freshness"]["blockers"]
    )
    plan = {row["source_id"]: row for row in report["freshness_rebuild_plan"]}
    assert plan["micro_live_preflight"]["required_rebuild_report"] == "micro_live_preflight"
    assert plan["micro_live_preflight"]["rebuild_command"] == "py scripts/build_btc_gate_aggregation_chain.py"
    assert any("dependency_newer=2" in item for item in report["key_blockers_cn"])


def test_btc_promotion_gate_control_fails_when_gate_critical_source_commit_does_not_match_head(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_git(args, *, cwd):  # type: ignore[no-untyped-def]
        if list(args) == ["rev-parse", "--short", "HEAD"]:
            return FIXTURE_CODE_COMMIT
        if list(args) == ["branch", "--show-current"]:
            return "test"
        return ""

    monkeypatch.setattr("quant_crypto.research.btc_promotion_gate_control._git", fake_git)
    paths = _write_current_like_sources(tmp_path, paper_readiness_approved=False)
    _write_json(
        paths["fill_mapping"],
        {
            "status": "incomplete_research_only",
            "code_commit": "old456",
            "blockers": ["strategy_fill_mapping_verified"],
            "gate": _safe_gate(),
        },
    )

    report = build_btc_promotion_gate_control(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        source_paths=paths,
        generated_at_utc=TS,
        aggregation_batch_id=BATCH_ID,
    )

    freshness_gate = _gate(report, "artifact_freshness_gate")
    assert freshness_gate["status"] == "blocked"
    assert freshness_gate["checks"]["source_code_commit_mismatch_count"] == 1
    assert (
        "artifact_freshness:source_code_commit_mismatch_count=1:rebuild_current_head_chain"
        in freshness_gate["blockers"]
    )
    assert (
        "artifact_freshness:fill_mapping:source_code_commit_mismatch_current_head"
        in report["artifact_freshness"]["blockers"]
    )
    assert "fill_mapping" in report["artifact_freshness"]["required_rebuild_reports"]
    fill_row = next(row for row in report["artifact_freshness"]["sources"] if row["source_id"] == "fill_mapping")
    assert fill_row["commit_policy"] == "source_code_commit_must_match_current_head"
    assert fill_row["current_code_commit"] == FIXTURE_CODE_COMMIT
    assert fill_row["source_code_commit"] == "old456"
    assert fill_row["source_code_commit_matches_current_head"] is False
    assert fill_row["rebuild_command"] == "py scripts/build_btc_gate_aggregation_chain.py"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_btc_promotion_gate_control_fails_closed_on_any_upstream_true_safety_flag(tmp_path: Path) -> None:
    paths = _write_current_like_sources(tmp_path, paper_readiness_approved=False)
    _write_json(
        paths["strategy_ledger"],
        {
            "status": "complete_research_only",
            "line_count": 5,
            "blockers": [],
            "gate": {"paper_queue_write_allowed": True, "live_unlock_allowed": True},
            "guardrails": {"order_endpoint_used": True},
        },
    )
    report = build_btc_promotion_gate_control(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        source_paths=paths,
        generated_at_utc=TS,
        aggregation_batch_id=BATCH_ID,
    )

    assert report["status"] == "safety_violation_fail_closed"
    assert "strategy_ledger:gate.paper_queue_write_allowed" in report["safety_violations"]
    assert "strategy_ledger:gate.live_unlock_allowed" in report["safety_violations"]
    assert "strategy_ledger:guardrails.order_endpoint_used" in report["safety_violations"]
    assert "safety_fail_closed" in {row["root_cause_id"] for row in report["root_cause_matrix"]}
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["gate"]["broker_or_order_allowed"] is False


def test_btc_promotion_gate_control_fails_closed_on_order_surface_audit_findings(tmp_path: Path) -> None:
    paths = _write_current_like_sources(tmp_path, paper_readiness_approved=False)
    _write_json(
        paths["order_surface_audit"],
        {
            "status": "blocked",
            "decision": "freeze_or_wrap_non_oms_order_surface",
            "blockers": [
                "btc_direct_order_surface_violation:quant_crypto/research/btc_strategy.py:4:direct_order_call"
            ],
            "findings": [
                {
                    "path": "quant_crypto/research/btc_strategy.py",
                    "line": 4,
                    "rule": "direct_order_call",
                    "snippet": "exchange.create_order('BTC/USDT', 'market', 'buy', 1)",
                }
            ],
            "gate": _safe_gate(),
        },
    )

    report = build_btc_promotion_gate_control(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        source_paths=paths,
        generated_at_utc=TS,
        aggregation_batch_id=BATCH_ID,
    )

    assert report["status"] == "safety_violation_fail_closed"
    assert any(item.startswith("order_surface_audit:btc_direct_order_surface_violation") for item in report["safety_violations"])
    assert any(item.startswith("order_surface_audit:finding:quant_crypto/research/btc_strategy.py:4") for item in report["safety_violations"])
    assert "safety_fail_closed" in {row["root_cause_id"] for row in report["root_cause_matrix"]}
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def _gate(report: dict, gate_id: str) -> dict:
    return next(row for row in report["gate_matrix"] if row["gate_id"] == gate_id)


def _write_current_like_sources(tmp_path: Path, *, paper_readiness_approved: bool = True) -> dict[str, Path]:
    paths = {
        "strategy_ledger": tmp_path / "strategy_ledger.json",
        "strategy_readiness": tmp_path / "strategy_readiness.json",
        "observe_only_health": tmp_path / "observe_only_health.json",
        "leakage_overfit": tmp_path / "leakage.json",
        "bar_replay": tmp_path / "bar_replay.json",
        "perpetual_objective": tmp_path / "objective.json",
        "gate_dashboard": tmp_path / "dashboard.json",
        "gate_report_consistency": tmp_path / "gate_report_consistency.json",
        "paper_readiness": tmp_path / "paper_readiness.json",
        "micro_live_preflight": tmp_path / "micro_live.json",
        "kill_switch": tmp_path / "kill_switch.json",
        "paper_runtime_replay": tmp_path / "paper_runtime.json",
        "paper_runtime_reconciliation": tmp_path / "reconciliation.json",
        "paper_exchange_rule": tmp_path / "paper_exchange_rule.json",
        "paper_risk_drill": tmp_path / "paper_risk_drill.json",
        "exchange_runtime_gap": tmp_path / "exchange_gap.json",
        "perpetual_execution": tmp_path / "perp_execution.json",
        "depth_slippage": tmp_path / "depth_slippage.json",
        "fill_mapping": tmp_path / "fill_mapping.json",
        "cost_model": tmp_path / "cost_model.json",
        "manual_packet": tmp_path / "manual_packet.json",
        "api_key_audit": tmp_path / "api_key_audit.json",
        "order_surface_audit": tmp_path / "order_surface_audit.json",
        "account_attestation": tmp_path / "account_attestation.json",
        "manual_paper_review_approval": tmp_path / "manual_paper_review_approval.json",
        "dirty_worktree_boundary": tmp_path / "dirty_worktree_boundary.json",
    }
    _write_json(
        paths["perpetual_objective"],
        {
            "status": "incomplete_research_only",
            "blockers": [
                "btc_perpetual_gate_objective:depth_history_coverage_window_satisfied",
                "btc_perpetual_gate_objective:strategy_fill_mapping_verified",
                "btc_perpetual_gate_objective:depth_aware_slippage_history_verified",
            ],
            "summary": {
                "current_mark_price_age_hours": 5.1,
                "two_sided_coverage_days": 1.4,
                "remaining_two_sided_coverage_days": 12.6,
                "gate_fill_count": 0,
                "mapped_gate_fill_count": 0,
                "depth_aware_slippage_history_verified": False,
            },
            "gate": _safe_gate(),
        },
    )
    _write_json(
        paths["strategy_ledger"],
        {"status": "incomplete_research_only", "line_count": 5, "blockers": ["strategy_ledger:global_gate_blocked"], "gate": _safe_gate()},
    )
    _write_json(
        paths["strategy_readiness"],
        {
            "status": "blocked_research_only",
            "blockers": [
                "long_short_donchian_top5:long_short_top5_forward_observation_under_30d",
                "high_octane_attack_sleeve_v2:high_octane_40pct_survival_threshold_boundary_margin_too_small",
                "paper_runtime:btc_perpetual_paper_runtime_replay_no_simulated_fills",
            ],
            "summary": {
                "ready_for_paper_count": 0,
                "paper_runtime_trade_execution_evidence_available": False,
            },
            "gate": _safe_gate(),
        },
    )
    _write_json(
        paths["observe_only_health"],
        {
            "status": "blocked_research_only",
            "blockers": ["long_short_donchian_top5:forward_observation_under_30d"],
            "summary": {
                "minimum_30d_complete_count": 0,
                "target_60d_complete_count": 0,
                "safety_violation_count": 0,
            },
            "gate": _safe_gate(),
        },
    )
    _write_json(
        paths["leakage_overfit"],
        {
            "status": "complete_research_only",
            "decision": "research_only_overfit_risk_high_no_paper_no_live",
            "blockers": [],
            "summary": {
                "check_fail_count": 0,
                "check_warn_count": 5,
                "decision": "research_only_overfit_risk_high_no_paper_no_live",
                "high_octane_best_margin_over_40pct_threshold": 0.011,
                "high_octane_likely_parameter_mined_boundary_candidate": True,
                "data_coverage_liquidation_one_hour_history_complete": False,
                "long_short_overfit_verdict": "requires_forward_confirmation",
                "high_octane_overfit_verdict": "high_overfit",
            },
            "gate": _safe_gate(),
        },
    )
    _write_json(paths["bar_replay"], {"status": "complete_research_only", "summary": {"check_fail_count": 0}, "blockers": [], "gate": _safe_gate()})
    _write_json(paths["gate_dashboard"], {"status": "blocked", "blockers": ["btc_gate_dashboard_micro_live_preflight_blocked"]})
    _write_json(
        paths["gate_report_consistency"],
        {
            "status": "pass",
            "decision": "btc_gate_report_consistency_passed_research_only_no_paper_no_live",
            "summary": {
                "fail_count": 0,
                "dashboard_hash_matches_current_evidence": True,
                "dashboard_perpetual_execution_evidence_hash": "hash-ok",
                "current_evidence_artifact_hash": "hash-ok",
            },
            "blockers": [],
            "gate": _safe_gate(),
        },
    )
    _write_json(
        paths["paper_readiness"],
        {
            "status": "ready_for_paper_start" if paper_readiness_approved else "blocked",
            "paper_queue_status": "approved" if paper_readiness_approved else "locked",
            "paper_start_allowed": paper_readiness_approved,
            "paper_execution_authorized": paper_readiness_approved,
            "live_status": "frozen",
            "blockers": [] if paper_readiness_approved else ["paper_readiness_blocked"],
        },
    )
    _write_json(
        paths["micro_live_preflight"],
        {
            "status": "blocked_fail_closed_research_only",
            "blockers": ["manual_approval_missing", "paper_runtime_replay:current_flat_heartbeat_waiting_for_trade_sample"],
            "summary": {
                "kill_switch_engaged": True,
                "manual_approval_recorded": False,
                "true_safety_flag_count": 0,
                "approved_initial_principal_usdt": 0.0,
            },
            "policy_state": {
                "paper_order_intake_allowed": False,
                "cancel_only_mode": True,
                "reduce_only_mode": True,
            },
            "gate": _safe_gate(),
        },
    )
    _write_json(paths["kill_switch"], {"status": "fail_closed_research_only", "blockers": ["kill_switch_engaged"], "policy_state": {"kill_switch_engaged": True}, "gate": _safe_gate()})
    _write_json(
        paths["paper_runtime_replay"],
        {
            "status": "incomplete_research_only",
            "blockers": ["btc_perpetual_paper_runtime_replay_no_simulated_fills"],
            "summary": {
                "paper_runtime_replay_ready": False,
                "simulated_fill_count": 0,
                "trade_execution_evidence_available": False,
            },
            "gate": _safe_gate(),
        },
    )
    _write_json(paths["paper_runtime_reconciliation"], {"status": "complete_research_only", "summary": {"paper_runtime_reconciliation_passed": True}, "blockers": [], "gate": _safe_gate()})
    _write_json(paths["paper_exchange_rule"], {"status": "incomplete_research_only", "blockers": ["current_flat_waiting_for_order_filter_sample"], "summary": {"current_order_sample_status": "waiting"}, "gate": _safe_gate()})
    _write_json(paths["paper_risk_drill"], {"status": "blocked_research_only", "blockers": ["risk_drill_missing_current_trade_sample"], "gate": _safe_gate()})
    _write_json(
        paths["exchange_runtime_gap"],
        {
            "status": "incomplete_research_only",
            "blockers": ["btc_runtime_contract_local_fixture_only_public_or_paper_runtime_layer_required"],
            "gate": _safe_gate(),
        },
    )
    _write_json(paths["perpetual_execution"], {"status": "incomplete_research_only", "blockers": ["btc_perp_exec_depth_aware_slippage_history_verified"], "gate": _safe_gate()})
    _write_json(paths["depth_slippage"], {"status": "incomplete_research_only", "blockers": ["depth_aware_slippage_history_verified"], "gate": _safe_gate()})
    _write_json(paths["fill_mapping"], {"status": "incomplete_research_only", "blockers": ["strategy_fill_mapping_verified"], "gate": _safe_gate()})
    _write_json(paths["cost_model"], {"status": "pass", "blockers": [], "gate": _safe_gate()})
    _write_json(paths["manual_packet"], {"status": "incomplete", "api_key_permission_reviewed": False, "blockers": ["manual_packet_incomplete"]})
    _write_json(
        paths["api_key_audit"],
        {
            "status": "complete",
            "decision": "api_key_permissions_ready_for_paper_only",
            "blockers": [],
            "gate": _safe_gate(),
        },
    )
    _write_json(
        paths["order_surface_audit"],
        {
            "status": "complete",
            "decision": "non_oms_order_surface_clean",
            "blockers": [],
            "findings": [],
            "non_blocking_match_count": 3,
            "gate": _safe_gate(),
        },
    )
    _write_json(
        paths["account_attestation"],
        {
            "status": "verified_research_only",
            "decision": "btc_paper_account_runtime_attestation_verified_manual_review_only_no_auto_paper_no_live",
            "attestation_current": True,
            "credential_permissions_verified": True,
            "credential_separation_verified": True,
            "manual_approval_recorded": True,
            "blockers": [],
            "gate": {**_safe_gate(), "manual_attestation_only": True, "paper_order_intake_allowed": False},
        },
    )
    _write_json(
        paths["manual_paper_review_approval"],
        {
            "status": "complete_research_only",
            "decision": "btc_manual_paper_review_approval_missing_or_invalid_no_paper_no_live",
            "manual_approval_recorded": False,
            "manual_review_missing_cleared": False,
            "paper_queue_write_allowed": False,
            "paper_order_intake_allowed": False,
            "live_unlock_allowed": False,
            "blockers": [],
            "reviewed_packet": {"sha256": ""},
            "gate": _safe_gate(),
        },
    )
    _write_json(
        paths["dirty_worktree_boundary"],
        {
            "status": "dirty_worktree_present",
            "decision": "btc_dirty_worktree_grouped_for_review_no_file_revert_no_commit",
            "dirty_state_summary": {
                "committable_source_or_test_count": 0,
                "only_generated_or_never_commit_dirty": True,
            },
            "secret_scan": {"unredacted_secret_like_count": 0},
            "blockers": [],
            "gate": _safe_gate(),
        },
    )
    return paths


def _safe_gate() -> dict[str, bool]:
    return {
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _write_json(path: Path, payload: dict, *, generated_at_utc: datetime = TS) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("code_commit", FIXTURE_CODE_COMMIT)
    payload.setdefault("generated_at_utc", generated_at_utc.isoformat())
    payload.setdefault("aggregation_batch_id", BATCH_ID)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
