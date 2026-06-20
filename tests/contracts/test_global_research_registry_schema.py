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
