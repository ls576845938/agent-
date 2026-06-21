from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_global_research_registry import build_global_registry


SCHEMA = Path("schemas/global_research_registry.schema.json")


def test_global_research_registry_schema_has_required_constraints() -> None:
    assert SCHEMA.exists()

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert schema["required"] == [
        "schema_version",
        "generated_at",
        "commit",
        "branch",
        "paper_queue_status",
        "live_status",
        "candidate_passed_internal_gate",
        "assets",
        "failure_explanations",
    ]
    assert schema["properties"]["paper_queue_status"]["enum"] == ["locked", "pending_review"]
    assert schema["properties"]["live_status"]["const"] == "frozen"
    assert schema["properties"]["candidate_passed_internal_gate"]["type"] == "integer"
    assert schema["properties"]["assets"]["required"] == ["us_equity", "btc"]
    us_equity_schema = schema["properties"]["assets"]["properties"]["us_equity"]
    assert us_equity_schema["properties"]["status"]["const"] == "mainline"
    assert "factor_evidence_status" in us_equity_schema["required"]
    assert "factor_count" in us_equity_schema["required"]
    assert "factor_pass_count" in us_equity_schema["required"]
    assert "factor_fail_count" in us_equity_schema["required"]
    assert "current_factor_candidates" in us_equity_schema["required"]
    assert "blocker_reasons" in us_equity_schema["required"]
    assert "data_lineage" in us_equity_schema["required"]
    assert "factor_evidence" in us_equity_schema["required"]
    assert "portfolio_evidence" in us_equity_schema["required"]
    data_lineage_schema = us_equity_schema["properties"]["data_lineage"]
    assert "data_lineage_grade" in data_lineage_schema["required"]
    assert "promotion_clean" in data_lineage_schema["required"]
    assert "universe_snapshot_manifest" in data_lineage_schema["required"]
    assert "corporate_action_status_report" in data_lineage_schema["required"]
    assert "survivorship_audit_report" in data_lineage_schema["required"]
    assert "provider_capability_matrix" in data_lineage_schema["required"]
    assert "provider_verification_report" in data_lineage_schema["required"]
    assert "selected_provider" in data_lineage_schema["required"]
    assert "provider_verified_for_promotion" in data_lineage_schema["required"]
    factor_evidence_schema = us_equity_schema["properties"]["factor_evidence"]
    assert "factor_evidence_status" in factor_evidence_schema["required"]
    assert "latest_factor_evidence" in factor_evidence_schema["required"]
    assert "factor_evidence_pack" in factor_evidence_schema["required"]
    assert "factor_count" in factor_evidence_schema["required"]
    assert "factor_pass_count" in factor_evidence_schema["required"]
    assert "factor_fail_count" in factor_evidence_schema["required"]
    assert "current_factor_candidates" in factor_evidence_schema["required"]
    assert "inherited_data_blockers" in factor_evidence_schema["required"]
    assert "inherited_provider_blockers" in factor_evidence_schema["required"]
    assert "allowed_next_action_summary" in factor_evidence_schema["required"]
    assert "selected_factor_count" in factor_evidence_schema["required"]
    portfolio_evidence_schema = us_equity_schema["properties"]["portfolio_evidence"]
    assert "portfolio_canonical_report" in portfolio_evidence_schema["required"]
    assert "event_ledger_status" in portfolio_evidence_schema["required"]
    assert "promotion_ready" in portfolio_evidence_schema["required"]
    assert "failure_explanations" in schema["properties"]
    assert us_equity_schema["properties"]["current_candidates"]["items"]["properties"]["allowed_next_action"]["const"] == (
        "internal_event_backtest_required"
    )
    btc_schema = schema["properties"]["assets"]["properties"]["btc"]
    assert btc_schema["properties"]["status"]["const"] == "research_sandbox"
    assert "latest_data_status" in btc_schema["required"]
    assert "latest_bundle_preflight" in btc_schema["required"]
    assert "latest_manual_metadata_capture_readiness" in btc_schema["required"]
    assert "latest_manual_metadata_capture_operator_packet" in btc_schema["required"]
    assert "latest_manual_metadata_import_report" in btc_schema["required"]
    assert "latest_objective_completion_audit" in btc_schema["required"]
    assert "latest_cost_model" in btc_schema["required"]
    assert "latest_fold_regime_contract" in btc_schema["required"]
    assert "latest_candidate_gate_audit" in btc_schema["required"]
    assert "latest_candidate_metric_repair_report" in btc_schema["required"]
    assert "latest_candidate_bounded_retest_plan" in btc_schema["required"]
    assert "latest_next_hypothesis_decision_report" in btc_schema["required"]
    assert "latest_strategy_family_roadmap_report" in btc_schema["required"]
    assert "latest_intraday_short_cycle_alpha_plan_report" in btc_schema["required"]
    assert "latest_intraday_short_cycle_alpha_probe_report" in btc_schema["required"]
    assert "latest_intraday_short_cycle_alpha_refinement_report" in btc_schema["required"]
    assert "latest_intraday_short_cycle_event_ledger_report" in btc_schema["required"]
    assert "latest_intraday_short_cycle_event_definition_repair_report" in btc_schema["required"]
    assert "latest_intraday_short_cycle_repaired_event_ledger_report" in btc_schema["required"]
    assert "latest_intraday_short_cycle_drift_guarded_event_ledger_report" in btc_schema["required"]
    assert "latest_intraday_short_cycle_promotion_gate_report" in btc_schema["required"]
    assert "latest_intraday_short_cycle_manual_review_packet" in btc_schema["required"]
    assert "latest_intraday_short_cycle_research_candidate_definition_preflight" in btc_schema["required"]
    assert "latest_intraday_short_cycle_research_candidate_definition_manifest" in btc_schema["required"]
    assert "latest_intraday_short_cycle_remaining_external_evidence_status" in btc_schema["required"]
    assert "latest_compression_attribution" in btc_schema["required"]
    assert "data_status" in btc_schema["required"]
    assert "bundle_preflight_status" in btc_schema["required"]
    assert "manual_metadata_capture_status" in btc_schema["required"]
    assert "manual_metadata_capture_operator_packet_status" in btc_schema["required"]
    assert "manual_metadata_import_status" in btc_schema["required"]
    assert "objective_completion_status" in btc_schema["required"]
    manual_schema = btc_schema["properties"]["manual_metadata_capture_status"]
    assert "latest_public_metadata_capture_attempt" in manual_schema["required"]
    assert "last_public_metadata_capture_status" in manual_schema["required"]
    assert "last_exchange_info_http_status" in manual_schema["required"]
    assert "last_funding_info_http_status" in manual_schema["required"]
    packet_schema = btc_schema["properties"]["manual_metadata_capture_operator_packet_status"]
    assert "operator_action" in packet_schema["required"]
    assert "manual_inputs_status" in packet_schema["required"]
    assert "paper_gate_manual_inputs_complete" in packet_schema["required"]
    assert "required_manual_inputs" in packet_schema["required"]
    assert "capture_request_count" in packet_schema["required"]
    assert "dry_run_import_available" in packet_schema["required"]
    assert "fee_tier_status" in packet_schema["required"]
    import_schema = btc_schema["properties"]["manual_metadata_import_status"]
    assert "captured_at" in import_schema["required"]
    assert "writes_performed" in import_schema["required"]
    assert "exchange_info_verified" in import_schema["required"]
    assert "funding_info_verified" in import_schema["required"]
    assert "valid_for_completion" in import_schema["required"]
    assert "raw_input_files" in import_schema["required"]
    objective_schema = btc_schema["properties"]["objective_completion_status"]
    assert "goal_complete" in objective_schema["required"]
    assert "incomplete_requirements" in objective_schema["required"]
    assert "cost_model_status" in btc_schema["required"]
    assert "fold_regime_status" in btc_schema["required"]
    assert "candidate_gate_audit" in btc_schema["required"]
    assert "candidate_metric_repair_status" in btc_schema["required"]
    assert "candidate_bounded_retest_status" in btc_schema["required"]
    assert "next_hypothesis_decision_status" in btc_schema["required"]
    assert "strategy_family_roadmap_status" in btc_schema["required"]
    assert "intraday_short_cycle_alpha_plan_status" in btc_schema["required"]
    assert "intraday_short_cycle_alpha_probe_status" in btc_schema["required"]
    assert "intraday_short_cycle_alpha_refinement_status" in btc_schema["required"]
    assert "intraday_short_cycle_event_ledger_status" in btc_schema["required"]
    assert "intraday_short_cycle_event_definition_repair_status" in btc_schema["required"]
    assert "intraday_short_cycle_repaired_event_ledger_status" in btc_schema["required"]
    assert "intraday_short_cycle_drift_guarded_event_ledger_status" in btc_schema["required"]
    assert "intraday_short_cycle_promotion_gate_status" in btc_schema["required"]
    assert "intraday_short_cycle_manual_review_packet_status" in btc_schema["required"]
    assert "intraday_short_cycle_research_candidate_definition_preflight_status" in btc_schema["required"]
    assert "intraday_short_cycle_research_candidate_definition_manifest_status" in btc_schema["required"]
    assert "intraday_short_cycle_remaining_external_evidence_status" in btc_schema["required"]
    repair_schema = btc_schema["properties"]["intraday_short_cycle_event_definition_repair_status"]
    assert repair_schema["properties"]["repair_screen_is_promotion_evidence"]["const"] is False
    assert repair_schema["properties"]["full_event_ledger_retest_required"]["const"] is True
    assert repair_schema["properties"]["candidate_generation_allowed"]["const"] is False
    assert repair_schema["properties"]["paper_or_live_unlock_allowed"]["const"] is False
    assert repair_schema["properties"]["true_scalping_allowed"]["const"] is False
    repaired_schema = btc_schema["properties"]["intraday_short_cycle_repaired_event_ledger_status"]
    assert repaired_schema["properties"]["candidate_generation_allowed"]["const"] is False
    assert repaired_schema["properties"]["paper_or_live_unlock_allowed"]["const"] is False
    assert repaired_schema["properties"]["true_scalping_allowed"]["const"] is False
    drift_guarded_schema = btc_schema["properties"]["intraday_short_cycle_drift_guarded_event_ledger_status"]
    assert drift_guarded_schema["properties"]["candidate_generation_allowed"]["const"] is False
    assert drift_guarded_schema["properties"]["paper_or_live_unlock_allowed"]["const"] is False
    assert drift_guarded_schema["properties"]["true_scalping_allowed"]["const"] is False
    promotion_gate_schema = btc_schema["properties"]["intraday_short_cycle_promotion_gate_status"]
    assert promotion_gate_schema["properties"]["candidate_generation_allowed"]["const"] is False
    assert promotion_gate_schema["properties"]["paper_review_pending_allowed"]["const"] is False
    assert promotion_gate_schema["properties"]["paper_or_live_unlock_allowed"]["const"] is False
    assert promotion_gate_schema["properties"]["true_scalping_allowed"]["const"] is False
    manual_review_schema = btc_schema["properties"]["intraday_short_cycle_manual_review_packet_status"]
    assert manual_review_schema["properties"]["candidate_generation_allowed"]["const"] is False
    assert manual_review_schema["properties"]["strategy_skeleton_generation_allowed"]["const"] is False
    assert manual_review_schema["properties"]["paper_or_live_unlock_allowed"]["const"] is False
    assert manual_review_schema["properties"]["true_scalping_allowed"]["const"] is False
    candidate_definition_manifest_schema = btc_schema["properties"][
        "intraday_short_cycle_research_candidate_definition_manifest_status"
    ]
    assert candidate_definition_manifest_schema["properties"]["candidate_generation_allowed"]["const"] is False
    assert candidate_definition_manifest_schema["properties"]["strategy_skeleton_generation_allowed"]["const"] is False
    assert candidate_definition_manifest_schema["properties"]["paper_or_live_unlock_allowed"]["const"] is False
    assert candidate_definition_manifest_schema["properties"]["true_scalping_allowed"]["const"] is False
    external_evidence_schema = btc_schema["properties"]["intraday_short_cycle_remaining_external_evidence_status"]
    assert external_evidence_schema["properties"]["candidate_generation_allowed"]["const"] is False
    assert external_evidence_schema["properties"]["strategy_skeleton_generation_allowed"]["const"] is False
    assert external_evidence_schema["properties"]["paper_or_live_unlock_allowed"]["const"] is False
    assert external_evidence_schema["properties"]["true_scalping_allowed"]["const"] is False
    assert "attribution_only" in btc_schema["required"]


def test_global_research_registry_schema_rejects_non_utc_generated_at() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    registry = build_global_registry(generated_at="2026-05-18T00:00:00Z")
    registry["generated_at"] = "2026-05-18T08:00:00+08:00"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(registry, schema)


def test_build_global_registry_minimum_structure_matches_policy() -> None:
    registry = build_global_registry(generated_at="2026-05-18T00:00:00Z")

    assert registry["schema_version"] == "global_research_registry_v1"
    assert registry["generated_at"] == "2026-05-18T00:00:00Z"
    assert registry["paper_queue_status"] == "locked"
    assert registry["live_status"] == "frozen"
    assert registry["candidate_passed_internal_gate"] == 0
    assert registry["assets"]["us_equity"]["status"] == "mainline"
    assert registry["assets"]["us_equity"]["data_lineage"]["status"] in {"missing", "partial", "complete"}
    assert "data_status_report" in registry["assets"]["us_equity"]["data_lineage"]
    assert registry["assets"]["us_equity"]["factor_evidence"]["status"] in {"missing", "partial", "complete"}
    assert registry["assets"]["us_equity"]["portfolio_evidence"]["status"] in {"missing", "research_only", "partial", "complete"}
    assert "internal_event_backtest_required" in registry["assets"]["us_equity"]["allowed_next_actions"]
    assert all(
        not data_version.startswith("qs-sqlite-BTC")
        for data_version in registry["assets"]["us_equity"]["data_lineage"]["data_versions"]
    )
    assert registry["assets"]["btc"]["status"] == "research_sandbox"
    assert "data_status" in registry["assets"]["btc"]
    assert "bundle_preflight_status" in registry["assets"]["btc"]
    assert "failure_explanations" in registry
    assert registry["assets"]["btc"]["data_status"]["status"] == "pass"
    assert registry["assets"]["btc"]["data_status"]["fold_contract_status"] == "pass"
    assert registry["assets"]["btc"]["data_status"]["regime_contract_status"] == "pass"
    assert registry["assets"]["btc"]["data_status"]["blockers"] == []
    assert registry["assets"]["btc"]["fold_regime_status"]["status"] == "pass"
    assert registry["assets"]["btc"]["fold_regime_status"]["blockers"] == []

    assert registry["assets"]["btc"]["current_candidates"] == []
    assert registry["assets"]["btc"]["attribution_only"] == []
    assert "compression_expansion_breakout" in registry["assets"]["btc"]["archived_or_rejected"]
    assert registry["assets"]["btc"]["candidate_passed_internal_gate"] == 0
    manual = registry["assets"]["btc"]["manual_metadata_capture_status"]
    packet = registry["assets"]["btc"]["manual_metadata_capture_operator_packet_status"]
    manual_import = registry["assets"]["btc"]["manual_metadata_import_status"]
    objective = registry["assets"]["btc"]["objective_completion_status"]
    assert registry["assets"]["btc"]["latest_manual_metadata_capture_operator_packet"] == (
        "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json"
    )
    assert registry["assets"]["btc"]["latest_manual_metadata_import_report"] == (
        "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json"
    )
    assert registry["assets"]["btc"]["latest_objective_completion_audit"] == (
        "artifacts/btc_data_status/latest/btc_objective_completion_audit_report.json"
    )
    assert registry["assets"]["btc"]["latest_candidate_metric_repair_report"] == (
        "artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json"
    )
    assert registry["assets"]["btc"]["latest_candidate_bounded_retest_plan"] == (
        "artifacts/btc_candidate_gate/latest/candidate_bounded_retest_plan.json"
    )
    assert registry["assets"]["btc"]["latest_next_hypothesis_decision_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_next_hypothesis_decision_report.json"
    )
    assert registry["assets"]["btc"]["latest_strategy_family_roadmap_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_strategy_family_roadmap_report.json"
    )
    assert registry["assets"]["btc"]["latest_intraday_short_cycle_alpha_plan_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_alpha_plan_report.json"
    )
    assert registry["assets"]["btc"]["latest_intraday_short_cycle_alpha_probe_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_alpha_probe_report.json"
    )
    assert registry["assets"]["btc"]["latest_intraday_short_cycle_alpha_refinement_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_alpha_refinement_report.json"
    )
    assert registry["assets"]["btc"]["latest_intraday_short_cycle_event_ledger_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_event_ledger_report.json"
    )
    assert registry["assets"]["btc"]["latest_intraday_short_cycle_event_definition_repair_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_event_definition_repair_report.json"
    )
    assert registry["assets"]["btc"]["latest_intraday_short_cycle_repaired_event_ledger_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_repaired_event_ledger_report.json"
    )
    assert registry["assets"]["btc"]["latest_intraday_short_cycle_drift_guarded_event_ledger_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_drift_guarded_event_ledger_report.json"
    )
    assert registry["assets"]["btc"]["latest_intraday_short_cycle_promotion_gate_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_promotion_gate_report.json"
    )
    assert registry["assets"]["btc"]["latest_intraday_short_cycle_manual_review_packet"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_manual_review_packet.json"
    )
    assert registry["assets"]["btc"]["latest_intraday_short_cycle_research_candidate_definition_preflight"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_research_candidate_definition_preflight.json"
    )
    assert registry["assets"]["btc"]["latest_intraday_short_cycle_research_candidate_definition_manifest"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_research_candidate_definition_manifest.json"
    )
    assert registry["assets"]["btc"]["latest_intraday_short_cycle_remaining_external_evidence_status"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_remaining_external_evidence_status_report.json"
    )
    metric_repair = registry["assets"]["btc"]["candidate_metric_repair_status"]
    assert metric_repair["status"] == "needs_metric_repair"
    assert metric_repair["promotion_allowed"] is False
    assert metric_repair["paper_review_pending_allowed"] is False
    assert metric_repair["best_candidate_strategy_id"] == "btc_perp_dual_trend_v4_eventpf_wf"
    assert metric_repair["failed_metrics"] == ["event_profit_factor", "walk_forward_pass_rate"]
    assert "repair_late_walk_forward_folds" in {
        action["name"] for action in metric_repair["recommended_repair_actions"]
    }
    assert "btc_candidate_metric_repair_event_profit_factor_failed" in metric_repair["blockers"]
    bounded_retest = registry["assets"]["btc"]["candidate_bounded_retest_status"]
    assert bounded_retest["status"] == "ready_for_bounded_retest"
    assert bounded_retest["retest_allowed"] is True
    assert bounded_retest["bounded_parameter_search_allowed"] is True
    assert bounded_retest["promotion_allowed"] is False
    assert bounded_retest["paper_review_pending_allowed"] is False
    assert bounded_retest["candidate_strategy_id"] == "btc_perp_dual_trend_v4_eventpf_wf"
    assert bounded_retest["failed_metrics"] == ["event_profit_factor", "walk_forward_pass_rate"]
    assert bounded_retest["focus_failed_folds"] == [3, 4]
    assert bounded_retest["ordinary_profit_factor_diagnostic_only"] is True
    assert bounded_retest["paper_or_live_unlock_allowed"] is False
    assert bounded_retest["broker_calls_allowed"] is False
    assert bounded_retest["blockers"] == []
    next_hypothesis = registry["assets"]["btc"]["next_hypothesis_decision_status"]
    assert next_hypothesis["status"] == "dual_trend_micro_surgery_rejected"
    assert next_hypothesis["decision"] == "reject_same_family_micro_surgery"
    assert next_hypothesis["next_required_action"] == "design_new_strategy_family_with_lifecycle_edge"
    assert next_hypothesis["promotion_allowed"] is False
    assert next_hypothesis["paper_review_pending_allowed"] is False
    assert next_hypothesis["same_family_micro_search_allowed"] is False
    assert next_hypothesis["mode_count"] == 10
    assert next_hypothesis["event_profit_factor_pass_count"] == 0
    assert next_hypothesis["best_event_mode"] == "lifecycle_stop6_trail10_max240"
    assert next_hypothesis["best_event_profit_factor"] == pytest.approx(1.036973)
    assert next_hypothesis["best_wf_mode"] == "accel1p2_lifecycle"
    assert next_hypothesis["best_wf_pass_rate"] == pytest.approx(1.0)
    assert "btc_next_hypothesis_all_probe_event_profit_factor_failed" in next_hypothesis["blockers"]
    strategy_family = registry["assets"]["btc"]["strategy_family_roadmap_status"]
    assert strategy_family["status"] == "family_design_data_blocked"
    assert strategy_family["decision"] == "select_funding_carry_reversion_hypothesis"
    assert strategy_family["next_required_action"] == (
        "extend_okx_public_history_before_hypothesis_or_candidate_generation"
    )
    assert strategy_family["selected_family_id"] == "funding_carry_reversion_v0"
    assert strategy_family["selected_family"] == "funding_carry_reversion"
    assert strategy_family["selected_provider"] == "okx_swap"
    assert strategy_family["selected_bundle_id"] == "btc_okx_swap_btcusdt_history_365d_v1"
    assert strategy_family["selected_bundle_duration_days"] == pytest.approx(94.333333)
    assert strategy_family["selected_bundle_duration_days"] < 365.0
    assert strategy_family["funding_rate_record_count"] == 284
    assert strategy_family["hypothesis_distribution_allowed"] is False
    assert strategy_family["candidate_generation_allowed"] is False
    assert strategy_family["strategy_skeleton_generation_allowed"] is False
    assert strategy_family["promotion_allowed"] is False
    assert strategy_family["paper_review_pending_allowed"] is False
    assert strategy_family["paper_or_live_unlock_allowed"] is False
    assert "btc_strategy_family_selected_okx_bundle_history_too_short" in strategy_family["blockers"]
    intraday_plan = registry["assets"]["btc"]["intraday_short_cycle_alpha_plan_status"]
    assert intraday_plan["status"] == "research_distribution_ready_candidate_blocked"
    assert intraday_plan["decision"] == "start_intraday_short_cycle_alpha_distribution"
    assert intraday_plan["next_required_action"] == "run_research_only_intraday_short_cycle_distribution_probe"
    assert intraday_plan["selected_style_id"] == "intraday_short_cycle_alpha_v0"
    assert intraday_plan["primary_timeframes"] == ["5m", "15m"]
    assert intraday_plan["intraday_research_distribution_allowed"] is True
    assert intraday_plan["short_cycle_probe_allowed"] is True
    assert intraday_plan["true_scalping_allowed"] is False
    assert intraday_plan["candidate_generation_allowed"] is False
    assert intraday_plan["strategy_skeleton_generation_allowed"] is False
    assert intraday_plan["promotion_allowed"] is False
    assert intraday_plan["paper_review_pending_allowed"] is False
    assert intraday_plan["paper_or_live_unlock_allowed"] is False
    assert intraday_plan["sample_days"] == pytest.approx(862.0)
    assert intraday_plan["interval_bar_counts"] == {"5m": 248257, "15m": 82753}
    assert intraday_plan["candidate_family_count"] == 4
    assert "btc_intraday_candidate_generation_blocked_until_distribution_probe_passes" in intraday_plan["blockers"]
    assert "btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model" in intraday_plan["blockers"]
    intraday_probe = registry["assets"]["btc"]["intraday_short_cycle_alpha_probe_status"]
    assert intraday_probe["status"] == "probe_completed_no_distribution_edge"
    assert intraday_probe["decision"] == "continue_intraday_alpha_research"
    assert intraday_probe["next_required_action"] == "refine_short_cycle_event_definitions_before_candidate"
    assert intraday_probe["distribution_probe_completed"] is True
    assert intraday_probe["alpha_distribution_observed"] is False
    assert intraday_probe["candidate_generation_allowed"] is False
    assert intraday_probe["strategy_skeleton_generation_allowed"] is False
    assert intraday_probe["promotion_allowed"] is False
    assert intraday_probe["paper_review_pending_allowed"] is False
    assert intraday_probe["paper_or_live_unlock_allowed"] is False
    assert intraday_probe["true_scalping_allowed"] is False
    assert intraday_probe["best_family_id"] == "orderflow_confirmed_momentum_intraday_v0"
    assert intraday_probe["best_family_event_count"] == 5659
    assert intraday_probe["best_horizon"] == "60m"
    assert intraday_probe["best_net_mean_bps"] == pytest.approx(-8.103324)
    assert intraday_probe["family_count"] == 4
    assert intraday_probe["round_trip_taker_cost_bps"] == pytest.approx(10.0)
    assert intraday_probe["interval_row_counts"] == {"5m": 248270, "15m": 82756}
    assert "btc_intraday_probe_no_net_positive_distribution_edge" in intraday_probe["blockers"]
    intraday_refinement = registry["assets"]["btc"]["intraday_short_cycle_alpha_refinement_status"]
    assert intraday_refinement["status"] == "refinement_completed_event_ledger_backtest_ready_candidate_blocked"
    assert intraday_refinement["decision"] == "design_research_only_event_ledger_backtest_for_refined_alpha"
    assert intraday_refinement["next_required_action"] == "build_event_ledger_backtest_for_best_refined_variant"
    assert intraday_refinement["refinement_completed"] is True
    assert intraday_refinement["robust_alpha_distribution_observed"] is True
    assert intraday_refinement["candidate_generation_allowed"] is False
    assert intraday_refinement["strategy_skeleton_generation_allowed"] is False
    assert intraday_refinement["promotion_allowed"] is False
    assert intraday_refinement["paper_review_pending_allowed"] is False
    assert intraday_refinement["paper_or_live_unlock_allowed"] is False
    assert intraday_refinement["true_scalping_allowed"] is False
    assert intraday_refinement["best_variant_id"] == "pullback_reclaim_24_dd100_4htrend100_v1"
    assert intraday_refinement["best_family_id"] == "pullback_reclaim_intraday_v0"
    assert intraday_refinement["best_variant_event_count"] == 558
    assert intraday_refinement["best_horizon"] == "60m"
    assert intraday_refinement["best_net_mean_bps"] == pytest.approx(5.754492)
    assert intraday_refinement["positive_net_fold_count"] == 4
    assert intraday_refinement["variant_count"] == 8
    assert intraday_refinement["round_trip_taker_cost_bps"] == pytest.approx(10.0)
    assert "btc_intraday_refinement_candidate_generation_blocked_until_event_ledger_backtest" in (
        intraday_refinement["blockers"]
    )
    intraday_event_ledger = registry["assets"]["btc"]["intraday_short_cycle_event_ledger_status"]
    assert intraday_event_ledger["status"] == "event_ledger_completed_research_only"
    assert intraday_event_ledger["decision"] == "return_to_event_definition"
    assert intraday_event_ledger["next_required_action"] == "repair_intraday_event_definition_before_candidate"
    assert intraday_event_ledger["event_ledger_completed"] is True
    assert intraday_event_ledger["candidate_generation_allowed"] is False
    assert intraday_event_ledger["strategy_skeleton_generation_allowed"] is False
    assert intraday_event_ledger["promotion_allowed"] is False
    assert intraday_event_ledger["paper_review_pending_allowed"] is False
    assert intraday_event_ledger["paper_or_live_unlock_allowed"] is False
    assert intraday_event_ledger["true_scalping_allowed"] is False
    assert intraday_event_ledger["variant_id"] == "pullback_reclaim_24_dd100_4htrend100_v1"
    assert intraday_event_ledger["family_id"] == "pullback_reclaim_intraday_v0"
    assert intraday_event_ledger["event_count"] == 315
    assert intraday_event_ledger["trade_count"] == 166
    assert intraday_event_ledger["fill_count"] == 331
    assert intraday_event_ledger["profit_factor"] == pytest.approx(1.214213)
    assert intraday_event_ledger["event_profit_factor"] == pytest.approx(1.15)
    assert intraday_event_ledger["walk_forward_pass_rate"] == pytest.approx(1.0)
    assert intraday_event_ledger["regime_pass_rate"] == pytest.approx(0.333333)
    assert intraday_event_ledger["gate_passed"] is False
    assert intraday_event_ledger["gate_status"] == "candidate_gate_failed"
    assert intraday_event_ledger["failed_metrics"] == ["regime_pass_rate"]
    assert intraday_event_ledger["stress_scenario_count"] == 5
    assert intraday_event_ledger["required_scenarios_present"] is True
    assert "btc_intraday_event_ledger_gate_failed_regime_pass_rate" in intraday_event_ledger["blockers"]
    intraday_repair = registry["assets"]["btc"]["intraday_short_cycle_event_definition_repair_status"]
    assert intraday_repair["status"] == "repair_candidate_identified_retest_required"
    assert intraday_repair["decision"] == "run_full_event_ledger_retest_for_repaired_definition"
    assert intraday_repair["next_required_action"] == (
        "run_research_only_event_ledger_retest_for_high_vol_non_expansion_repair_v1"
    )
    assert intraday_repair["repair_scan_completed"] is True
    assert intraday_repair["repair_screen_is_promotion_evidence"] is False
    assert intraday_repair["full_event_ledger_retest_required"] is True
    assert intraday_repair["candidate_generation_allowed"] is False
    assert intraday_repair["strategy_skeleton_generation_allowed"] is False
    assert intraday_repair["promotion_allowed"] is False
    assert intraday_repair["paper_review_pending_allowed"] is False
    assert intraday_repair["paper_or_live_unlock_allowed"] is False
    assert intraday_repair["true_scalping_allowed"] is False
    assert intraday_repair["best_variant_id"] == "high_vol_non_expansion_repair_v1"
    assert intraday_repair["best_trade_count"] == 103
    assert intraday_repair["best_profit_factor"] == pytest.approx(1.859701)
    assert intraday_repair["best_median_net_pnl"] == pytest.approx(2.371603)
    assert intraday_repair["best_regime_pass_rate"] == pytest.approx(1.0)
    assert intraday_repair["best_tail_dependency_pass"] is True
    assert intraday_repair["best_repair_screen_pass"] is True
    assert intraday_repair["variant_count"] == 5
    assert intraday_repair["min_trade_count"] == 50
    assert "btc_intraday_repair_full_event_ledger_retest_required" in intraday_repair["blockers"]
    repaired_event_ledger = registry["assets"]["btc"]["intraday_short_cycle_repaired_event_ledger_status"]
    assert repaired_event_ledger["status"] == "event_ledger_completed_research_only"
    assert repaired_event_ledger["decision"] == "return_to_event_definition"
    assert repaired_event_ledger["next_required_action"] == "repair_intraday_event_definition_before_candidate"
    assert repaired_event_ledger["event_ledger_completed"] is True
    assert repaired_event_ledger["source_event_definition_repair_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_event_definition_repair_report.json"
    )
    assert repaired_event_ledger["candidate_generation_allowed"] is False
    assert repaired_event_ledger["strategy_skeleton_generation_allowed"] is False
    assert repaired_event_ledger["promotion_allowed"] is False
    assert repaired_event_ledger["paper_review_pending_allowed"] is False
    assert repaired_event_ledger["paper_or_live_unlock_allowed"] is False
    assert repaired_event_ledger["true_scalping_allowed"] is False
    assert repaired_event_ledger["variant_id"] == "high_vol_non_expansion_repair_v1"
    assert repaired_event_ledger["allowed_regimes"] == ["high_vol_trend", "mean_reverting_chop", "trending_up"]
    assert repaired_event_ledger["volatility_states"] == ["high_vol"]
    assert repaired_event_ledger["event_count"] == 217
    assert repaired_event_ledger["trade_count"] == 110
    assert repaired_event_ledger["fill_count"] == 219
    assert repaired_event_ledger["profit_factor"] == pytest.approx(1.637559)
    assert repaired_event_ledger["event_profit_factor"] == pytest.approx(1.3697)
    assert repaired_event_ledger["walk_forward_pass_rate"] == pytest.approx(0.833333)
    assert repaired_event_ledger["regime_pass_rate"] == pytest.approx(0.5)
    assert repaired_event_ledger["tail_dependency_status"] == "pass"
    assert repaired_event_ledger["gate_passed"] is False
    assert repaired_event_ledger["gate_status"] == "candidate_gate_failed"
    assert repaired_event_ledger["failed_metrics"] == ["regime_pass_rate"]
    assert repaired_event_ledger["stress_scenario_count"] == 5
    assert repaired_event_ledger["required_scenarios_present"] is True
    assert "btc_intraday_event_ledger_gate_failed_regime_pass_rate" in repaired_event_ledger["blockers"]
    drift_guarded = registry["assets"]["btc"]["intraday_short_cycle_drift_guarded_event_ledger_status"]
    assert drift_guarded["status"] == "event_ledger_passed_internal_research_gate_candidate_still_locked"
    assert drift_guarded["decision"] == "continue_research"
    assert drift_guarded["next_required_action"] == "manual_review_before_any_candidate_generation"
    assert drift_guarded["event_ledger_completed"] is True
    assert drift_guarded["candidate_generation_allowed"] is False
    assert drift_guarded["strategy_skeleton_generation_allowed"] is False
    assert drift_guarded["promotion_allowed"] is False
    assert drift_guarded["paper_review_pending_allowed"] is False
    assert drift_guarded["paper_or_live_unlock_allowed"] is False
    assert drift_guarded["true_scalping_allowed"] is False
    assert drift_guarded["variant_id"] == "high_vol_non_expansion_trend_guard_repair_v1"
    assert drift_guarded["allowed_regimes"] == ["high_vol_trend", "mean_reverting_chop", "trending_up"]
    assert drift_guarded["volatility_states"] == ["high_vol"]
    assert drift_guarded["min_trend_by_regime"] == {"high_vol_trend": 0.017}
    assert drift_guarded["event_count"] == 161
    assert drift_guarded["trade_count"] == 78
    assert drift_guarded["fill_count"] == 156
    assert drift_guarded["profit_factor"] == pytest.approx(2.647434)
    assert drift_guarded["event_profit_factor"] == pytest.approx(1.4397)
    assert drift_guarded["walk_forward_pass_rate"] == pytest.approx(0.833333)
    assert drift_guarded["regime_pass_rate"] == pytest.approx(0.8)
    assert drift_guarded["tail_dependency_status"] == "pass"
    assert drift_guarded["gate_passed"] is True
    assert drift_guarded["gate_status"] == "candidate_passed_internal_gate"
    assert drift_guarded["failed_metrics"] == []
    assert drift_guarded["stress_scenario_count"] == 5
    assert drift_guarded["required_scenarios_present"] is True
    assert "btc_regime_contract_not_pass" not in drift_guarded["blockers"]
    assert "btc_intraday_event_ledger_candidate_generation_locked_pending_review" in drift_guarded["blockers"]
    promotion_gate = registry["assets"]["btc"]["intraday_short_cycle_promotion_gate_status"]
    assert promotion_gate["status"] == "ready_for_manual_candidate_review"
    assert promotion_gate["decision"] == "continue_research_manual_review_only"
    assert promotion_gate["next_required_action"] == "manual_review_before_any_candidate_generation"
    assert promotion_gate["manual_candidate_review_allowed"] is True
    assert promotion_gate["candidate_generation_allowed"] is False
    assert promotion_gate["strategy_skeleton_generation_allowed"] is False
    assert promotion_gate["promotion_allowed"] is False
    assert promotion_gate["paper_review_pending_allowed"] is False
    assert promotion_gate["paper_or_live_unlock_allowed"] is False
    assert promotion_gate["true_scalping_allowed"] is False
    assert promotion_gate["strategy_id"] == "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1"
    assert promotion_gate["variant_id"] == "high_vol_non_expansion_trend_guard_repair_v1"
    assert promotion_gate["trade_count"] == 78
    assert promotion_gate["fill_count"] == 156
    assert promotion_gate["profit_factor"] == pytest.approx(2.647434)
    assert promotion_gate["event_profit_factor"] == pytest.approx(1.4397)
    assert promotion_gate["walk_forward_pass_rate"] == pytest.approx(0.833333)
    assert promotion_gate["regime_pass_rate"] == pytest.approx(0.8)
    assert promotion_gate["gate_passed"] is True
    assert promotion_gate["gate_status"] == "candidate_passed_internal_gate"
    assert promotion_gate["manifest_params_present"] is True
    assert promotion_gate["private_order_broker_paths_locked"] is True
    assert promotion_gate["paper_live_still_locked"] is True
    assert promotion_gate["true_scalping_still_locked"] is True
    assert promotion_gate["blockers"] == []
    manual_review = registry["assets"]["btc"]["intraday_short_cycle_manual_review_packet_status"]
    assert manual_review["status"] == "approved_for_research_candidate_definition"
    assert manual_review["decision"] == "allow_research_candidate_definition_only"
    assert manual_review["next_required_action"] == "build_research_candidate_definition_manifest"
    assert manual_review["manual_review_packet_ready"] is True
    assert manual_review["recorded_manual_review_approved"] is True
    assert manual_review["research_candidate_definition_allowed"] is True
    assert manual_review["candidate_generation_allowed"] is False
    assert manual_review["strategy_skeleton_generation_allowed"] is False
    assert manual_review["promotion_allowed"] is False
    assert manual_review["paper_review_pending_allowed"] is False
    assert manual_review["paper_or_live_unlock_allowed"] is False
    assert manual_review["true_scalping_allowed"] is False
    assert manual_review["strategy_id"] == "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1"
    assert manual_review["variant_id"] == "high_vol_non_expansion_trend_guard_repair_v1"
    assert manual_review["approval_exists"] is True
    assert manual_review["approval_valid"] is True
    assert manual_review["approval_path"] == (
        "data/research/btc_intraday_candidate_reviews/btc_intraday_short_cycle_manual_review_v1/review.json"
    )
    assert manual_review["blockers"] == []
    candidate_definition_preflight = registry["assets"]["btc"][
        "intraday_short_cycle_research_candidate_definition_preflight_status"
    ]
    assert registry["assets"]["btc"]["latest_intraday_short_cycle_research_candidate_definition_preflight"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_research_candidate_definition_preflight.json"
    )
    assert candidate_definition_preflight["status"] == "ready_for_research_candidate_definition_manifest"
    assert candidate_definition_preflight["decision"] == "allow_research_candidate_definition_manifest_only"
    assert candidate_definition_preflight["next_required_action"] == (
        "create_research_candidate_definition_manifest_no_strategy_skeleton"
    )
    assert candidate_definition_preflight["research_candidate_definition_manifest_allowed"] is True
    assert candidate_definition_preflight["candidate_generation_allowed"] is False
    assert candidate_definition_preflight["strategy_skeleton_generation_allowed"] is False
    assert candidate_definition_preflight["promotion_allowed"] is False
    assert candidate_definition_preflight["paper_or_live_unlock_allowed"] is False
    assert candidate_definition_preflight["true_scalping_allowed"] is False
    assert candidate_definition_preflight["manual_review_packet_approved"] is True
    assert candidate_definition_preflight["recorded_manual_review_approved"] is True
    candidate_definition_manifest = registry["assets"]["btc"][
        "intraday_short_cycle_research_candidate_definition_manifest_status"
    ]
    assert candidate_definition_manifest["status"] == "ready_research_candidate_definition_manifest_only"
    assert candidate_definition_manifest["decision"] == "publish_research_candidate_definition_manifest_only"
    assert candidate_definition_manifest["next_required_action"] == (
        "review_research_candidate_definition_manifest_no_strategy_skeleton"
    )
    assert candidate_definition_manifest["research_candidate_definition_manifest_ready"] is True
    assert candidate_definition_manifest["candidate_generation_allowed"] is False
    assert candidate_definition_manifest["strategy_skeleton_generation_allowed"] is False
    assert candidate_definition_manifest["promotion_allowed"] is False
    assert candidate_definition_manifest["paper_or_live_unlock_allowed"] is False
    assert candidate_definition_manifest["true_scalping_allowed"] is False
    assert candidate_definition_manifest["preflight_ready_for_definition_manifest"] is True
    assert candidate_definition_manifest["manual_review_packet_approved"] is True
    assert candidate_definition_manifest["recorded_manual_review_approved"] is True
    assert candidate_definition_manifest["only_manual_or_external_blockers_remain"] is True
    assert candidate_definition_manifest["automated_engineering_blockers"] == []
    assert set(candidate_definition_manifest["remaining_manual_or_external_categories"]) == {
        "real_long_horizon_market_data",
        "execution_evidence",
        "queue_evidence",
        "paper_gate",
    }
    external_evidence = registry["assets"]["btc"]["intraday_short_cycle_remaining_external_evidence_status"]
    assert external_evidence["status"] == "candidate_definition_ready_external_evidence_pending"
    assert external_evidence["decision"] == "continue_external_evidence_collection_no_candidate_no_paper_no_live"
    assert external_evidence["manual_approval_satisfied"] is True
    assert external_evidence["research_candidate_definition_manifest_ready"] is True
    assert external_evidence["only_external_evidence_blockers_remain"] is True
    assert external_evidence["automated_engineering_blockers"] == []
    assert set(external_evidence["remaining_external_evidence_categories"]) == {
        "real_long_horizon_market_data",
        "execution_evidence",
        "queue_evidence",
        "paper_gate",
    }
    assert external_evidence["ws_l2_coverage_contract_satisfied"] is False
    assert external_evidence["ws_proxy_diagnostics_ready"] is True
    assert external_evidence["execution_queue_external_evidence_contract_satisfied"] is False
    assert external_evidence["execution_latency_evidence_contract_satisfied"] is False
    assert external_evidence["queue_position_evidence_contract_satisfied"] is False
    assert external_evidence["private_order_execution_latency_model_ready"] is False
    assert external_evidence["exchange_queue_position_model_ready"] is False
    assert external_evidence["paper_gate_ready"] is False
    assert external_evidence["candidate_generation_allowed"] is False
    assert external_evidence["strategy_skeleton_generation_allowed"] is False
    assert external_evidence["paper_or_live_unlock_allowed"] is False
    assert external_evidence["true_scalping_allowed"] is False
    assert registry["paper_queue_status"] == "locked"
    assert registry["candidate_passed_internal_gate"] == 0
    assert registry["assets"]["btc"]["paper_queue_status"] == "locked"
    assert registry["assets"]["btc"]["current_candidates"] == []
    assert objective["status"] == "complete"
    assert objective["goal_complete"] is True
    assert objective["incomplete_requirements"] == []
    assert "funding_ledger_net_pnl_integration" in objective["complete_requirements"]
    assert "manual_exchange_info_capture" in objective["complete_requirements"]
    assert "funding_info_endpoint_policy_repair" in objective["complete_requirements"]
    assert objective["next_required_action"] == "none"
    assert manual["status"] == "metadata_verified"
    assert manual["latest_public_metadata_capture_attempt"] == (
        "artifacts/btc_data_status/latest/btc_public_metadata_capture_attempt_report.json"
    )
    assert manual["last_public_metadata_capture_status"] == "capture_incomplete"
    assert manual["last_public_metadata_capture_network_called"] is False
    assert manual["last_exchange_info_capture_status"] == "not_executed"
    assert manual["last_exchange_info_http_status"] is None
    assert manual["last_funding_info_capture_status"] == "not_executed"
    assert manual["last_funding_info_http_status"] is None
    assert manual["exchange_info_manual_capture_required"] is False
    assert manual["funding_info_manual_capture_required"] is False
    assert manual["exchange_info_allowed_endpoint"] == "GET /api/v5/public/instruments"
    assert manual["funding_info_allowed_endpoint"] == "GET /api/v5/public/funding-rate"
    assert manual["api_key_required"] is False
    assert packet["status"] == "metadata_verified"
    assert packet["operator_action"] == "no_manual_capture_required"
    assert packet["manual_inputs_status"] == "manual_inputs_verified"
    assert packet["paper_gate_manual_inputs_complete"] is True
    assert packet["required_manual_input_count"] == 3
    inputs = {item["name"]: item for item in packet["required_manual_inputs"]}
    assert inputs["exchange_info"]["status"] == "verified"
    assert inputs["funding_info"]["status"] == "verified"
    assert inputs["fee_tier_overlay"]["status"] == "verified"
    assert inputs["fee_tier_overlay"]["action"] == "none"
    assert packet["capture_request_count"] == 2
    assert packet["dry_run_import_available"] is True
    assert packet["last_exchange_info_http_status"] is None
    assert packet["last_funding_info_http_status"] is None
    assert packet["fee_tier_status"]["fee_tier_verified"] is True
    assert packet["fee_tier_status"]["manual_capture_required"] is False
    assert packet["fee_tier_status"]["cost_model_status"] == "pass"
    assert packet["fee_tier_status"]["fee_blockers"] == []
    assert manual_import["status"] == "verified"
    assert manual_import["report_path"] == "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json"
    assert manual_import["writes_performed"] is True
    assert manual_import["exchange_info_verified"] is True
    assert manual_import["funding_info_verified"] is True
    assert manual_import["valid_for_completion"] is True
    assert manual_import["bundle_dir"] == (
        "data/external/btc_perpetual/okx_swap/bundles/btc_okx_swap_btcusdt_history_365d_v1"
    )
    assert manual_import["raw_input_files"]["exchange_info_raw"]["exists"] is True
    assert manual_import["raw_input_files"]["exchange_info_raw"]["http_status"] == 200
    assert manual_import["raw_input_files"]["funding_info_raw"]["exists"] is True
    assert manual_import["raw_input_files"]["funding_info_raw"]["http_status"] == 200
    assert manual_import["blockers"] == []
    assert manual["strategy_retest_allowed"] is False
    assert "btc_candidate_metric_repair_event_profit_factor_failed" in registry["assets"]["btc"]["blockers"]
    assert "btc_binance_public_rest_http_451_geoblocked" not in registry["assets"]["btc"]["blockers"]


def test_global_registry_rejects_schema_versionless_manual_import_for_completion(tmp_path: Path) -> None:
    report = _verified_manual_import_report()
    report.pop("schema_version")
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)

    registry = build_global_registry(repo_root=tmp_path, generated_at="2026-05-18T00:00:00Z")
    manual_import = registry["assets"]["btc"]["manual_metadata_import_status"]

    assert manual_import["status"] == "verified"
    assert manual_import["valid_for_completion"] is False
    assert "btc_manual_metadata_import_schema_version_missing_or_invalid" in manual_import["blockers"]


def test_global_registry_rejects_blank_manual_import_raw_path(tmp_path: Path) -> None:
    report = _verified_manual_import_report()
    report["raw_input_files"]["funding_info_raw"]["path"] = "   "
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)

    registry = build_global_registry(repo_root=tmp_path, generated_at="2026-05-18T00:00:00Z")
    manual_import = registry["assets"]["btc"]["manual_metadata_import_status"]

    assert manual_import["status"] == "verified"
    assert manual_import["valid_for_completion"] is False
    assert "btc_funding_info_raw_import_provenance_missing" in manual_import["blockers"]


def test_global_registry_rejects_missing_manual_import_validation_command(tmp_path: Path) -> None:
    report = _verified_manual_import_report()
    report.pop("post_import_validation_command")
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)

    registry = build_global_registry(repo_root=tmp_path, generated_at="2026-05-18T00:00:00Z")
    manual_import = registry["assets"]["btc"]["manual_metadata_import_status"]

    assert manual_import["status"] == "verified"
    assert manual_import["valid_for_completion"] is False
    assert "btc_manual_metadata_import_validation_command_missing" in manual_import["blockers"]


def test_global_registry_can_surface_btc_pending_review_from_btc_registry(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_research_registry/research_registry.json",
        {
            "items": {},
            "btc": {
                "candidate_passed_internal_gate": 1,
                "current_candidates": ["btc_future_candidate_v1"],
            },
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json",
        {
            "status": "metadata_verified",
            "operator_action": "no_manual_capture_required",
            "capture_requests": [{"name": "exchange_info"}, {"name": "funding_info"}],
            "post_capture_dry_run_import_command": "",
            "last_public_metadata_capture_status": {},
            "blockers": [],
        },
    )

    registry = build_global_registry(repo_root=tmp_path, generated_at="2026-05-18T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(registry, schema)
    assert registry["paper_queue_status"] == "pending_review"
    assert registry["live_status"] == "frozen"
    assert registry["candidate_passed_internal_gate"] == 1
    assert registry["assets"]["btc"]["paper_queue_status"] == "pending_review"
    assert registry["assets"]["btc"]["current_candidates"] == ["btc_future_candidate_v1"]


def test_global_registry_schema_rejects_pending_review_without_btc_candidate() -> None:
    registry = build_global_registry(generated_at="2026-05-18T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    registry["paper_queue_status"] = "pending_review"
    registry["candidate_passed_internal_gate"] = 1
    registry["assets"]["btc"]["paper_queue_status"] = "pending_review"
    registry["assets"]["btc"]["candidate_passed_internal_gate"] = 1
    registry["assets"]["btc"]["current_candidates"] = []

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(registry, schema)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _verified_manual_import_report() -> dict[str, object]:
    return {
        "schema_version": "btc_manual_metadata_import_report_v1",
        "status": "verified",
        "generated_at": "2026-05-22T00:00:00Z",
        "dry_run": False,
        "captured_at": "2026-05-22T00:00:00Z",
        "writes_performed": True,
        "exchange_info_verified": True,
        "funding_info_verified": True,
        "bundle_dir": "data/external/btc_perpetual/binance_usdm/bundles/fixture",
        "raw_input_files": {
            "exchange_info_raw": {
                "path": "exchange_info_raw.json",
                "exists": True,
                "size_bytes": 123,
                "sha256": "a" * 64,
                    "http_status_file": "exchange_info_http_status.txt",
                    "http_status": 200,
                    "http_status_verified": True,
            },
            "funding_info_raw": {
                "path": "funding_info_raw.json",
                "exists": True,
                "size_bytes": 2,
                "sha256": "b" * 64,
                    "http_status_file": "funding_info_http_status.txt",
                    "http_status": 200,
                    "http_status_verified": True,
            },
        },
        "exchange_info_output_path": "data/external/btc_perpetual/binance_usdm/bundles/fixture/exchange_info.json",
        "exchange_info_output_sha256": "c" * 64,
        "funding_info_output_path": "data/external/btc_perpetual/binance_usdm/bundles/fixture/funding_info.json",
        "funding_info_output_sha256": "d" * 64,
        "post_import_validation_command": "make validate-btc-public-data-bundle",
        "blockers": [],
    }
