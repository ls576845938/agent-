import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_research_registry import build_btc_research_registry


REGISTRY = Path("artifacts/btc_research_registry/research_registry.json")
SCHEMA = Path("schemas/btc_research_registry.schema.json")


def test_btc_research_registry_schema_valid() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(registry, schema)


def test_btc_research_registry_statuses() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    items = registry["items"]

    assert registry["paper_queue"] == "LOCKED"
    assert registry["live"] == "FROZEN"
    assert items["perp_dual_trend"]["status"] == "archived"
    assert items["liquidation_shock_recovery"]["status"] == "archived"
    assert items["low_vol_uptrend"]["status"] == "hypothesis_rejected"
    assert "compression_expansion_breakout" in items
    assert items["compression_expansion_breakout"]["status"] == "archived"
    assert items["compression_expansion_breakout"]["next_action"] == "do_not_retest_without_new_hypothesis"


def test_btc_research_registry_schema_rejects_non_utc_generated_at() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    registry["generated_at"] = "2026-05-22T08:00:00+08:00"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(registry, schema)


def test_btc_research_registry_exposes_manual_metadata_readiness() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    btc = registry["btc"]
    manual = btc["manual_metadata_capture_status"]
    packet = btc["manual_metadata_capture_operator_packet_status"]
    manual_import = btc["manual_metadata_import_status"]

    assert btc["latest_manual_metadata_capture_readiness"] == (
        "artifacts/btc_data_status/latest/btc_manual_metadata_capture_readiness_report.json"
    )
    assert btc["latest_manual_metadata_capture_operator_packet"] == (
        "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json"
    )
    assert btc["latest_manual_metadata_import_report"] == (
        "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json"
    )
    assert btc["latest_objective_completion_audit"] == (
        "artifacts/btc_data_status/latest/btc_objective_completion_audit_report.json"
    )
    assert btc["latest_candidate_metric_repair_report"] == (
        "artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json"
    )
    assert btc["latest_candidate_bounded_retest_plan"] == (
        "artifacts/btc_candidate_gate/latest/candidate_bounded_retest_plan.json"
    )
    assert btc["latest_candidate_bounded_retest_outcome_report"] == (
        "artifacts/btc_candidate_gate/latest/candidate_bounded_retest_outcome_report.json"
    )
    assert btc["latest_next_hypothesis_decision_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_next_hypothesis_decision_report.json"
    )
    assert btc["latest_strategy_family_roadmap_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_strategy_family_roadmap_report.json"
    )
    assert btc["latest_intraday_short_cycle_alpha_plan_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_alpha_plan_report.json"
    )
    assert btc["latest_intraday_short_cycle_alpha_probe_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_alpha_probe_report.json"
    )
    assert btc["latest_intraday_short_cycle_alpha_refinement_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_alpha_refinement_report.json"
    )
    metric_repair = btc["candidate_metric_repair_status"]
    assert metric_repair["status"] == "needs_metric_repair"
    assert metric_repair["promotion_allowed"] is False
    assert metric_repair["paper_review_pending_allowed"] is False
    assert metric_repair["best_candidate_strategy_id"] == "btc_perp_dual_trend_v4_eventpf_wf"
    assert metric_repair["failed_metrics"] == ["event_profit_factor", "walk_forward_pass_rate"]
    assert metric_repair["event_profit_factor"] == pytest.approx(1.0205)
    assert metric_repair["walk_forward_pass_rate"] == pytest.approx(0.5)
    assert "run_bounded_event_pf_retest" in {
        action["name"] for action in metric_repair["recommended_repair_actions"]
    }
    assert "btc_candidate_metric_repair_event_profit_factor_failed" in metric_repair["blockers"]
    bounded_retest = btc["candidate_bounded_retest_status"]
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
    bounded_retest_outcome = btc["candidate_bounded_retest_outcome_status"]
    assert bounded_retest_outcome["status"] == "completed_candidate_gate_failed"
    assert bounded_retest_outcome["run_id"] == "20260604T132400Z_okx_bounded_retest"
    assert bounded_retest_outcome["candidate_gate_passed"] is False
    assert bounded_retest_outcome["promotion_allowed"] is False
    assert bounded_retest_outcome["paper_review_pending_allowed"] is False
    assert bounded_retest_outcome["same_retest_repeat_allowed"] is False
    assert bounded_retest_outcome["event_profit_factor"] == pytest.approx(1.0205)
    assert bounded_retest_outcome["walk_forward_pass_rate"] == pytest.approx(0.5)
    assert bounded_retest_outcome["failed_metrics"] == ["event_profit_factor", "walk_forward_pass_rate"]
    assert bounded_retest_outcome["paper_queue_status"] == "LOCKED"
    assert bounded_retest_outcome["live_status"] == "FROZEN"
    assert bounded_retest_outcome["real_broker_api_called"] is False
    assert bounded_retest_outcome["real_orders_created"] is False
    assert bounded_retest_outcome["paper_or_live_unlock_allowed"] is False
    assert "btc_candidate_bounded_retest_event_profit_factor_failed" in bounded_retest_outcome["blockers"]
    next_hypothesis = btc["next_hypothesis_decision_status"]
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
    strategy_family = btc["strategy_family_roadmap_status"]
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
    intraday_plan = btc["intraday_short_cycle_alpha_plan_status"]
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
    intraday_probe = btc["intraday_short_cycle_alpha_probe_status"]
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
    intraday_refinement = btc["intraday_short_cycle_alpha_refinement_status"]
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
    objective = btc["objective_completion_status"]
    assert objective["status"] == "complete"
    assert objective["goal_complete"] is True
    assert objective["incomplete_requirements"] == []
    assert "funding_ledger_net_pnl_integration" in objective["complete_requirements"]
    assert "manual_exchange_info_capture" in objective["complete_requirements"]
    assert "funding_info_endpoint_policy_repair" in objective["complete_requirements"]
    assert "archive_compression_expansion_breakout" in objective["complete_requirements"]
    assert "btc_hypothesis_lab_v2_controlled_search" in objective["complete_requirements"]
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
    assert manual["last_public_metadata_next_required_action"] == "manual_capture_from_allowed_network"
    assert manual["exchange_info_manual_capture_required"] is False
    assert manual["funding_info_manual_capture_required"] is False
    assert manual["exchange_info_allowed_endpoint"] == "GET /api/v5/public/instruments"
    assert manual["funding_info_allowed_endpoint"] == "GET /api/v5/public/funding-rate"
    assert manual["api_key_required"] is False
    assert manual["private_endpoints_allowed"] is False
    assert manual["order_endpoints_allowed"] is False
    assert manual["strategy_retest_allowed"] is False
    assert manual["paper_or_live_unlock_allowed"] is False
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
    assert "btc_candidate_metric_repair_event_profit_factor_failed" in btc["blockers"]
    assert "btc_candidate_metric_repair_walk_forward_pass_rate_failed" in btc["blockers"]
    assert "btc_perpetual_exchange_info_not_verified" not in btc["blockers"]
    assert "btc_binance_public_rest_http_451_geoblocked" not in btc["blockers"]


def test_btc_research_registry_exposes_manual_import_raw_file_hashes(tmp_path: Path) -> None:
    _write_selected_bundle(tmp_path)
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json",
        {
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
            "exchange_info_output_sha256": _sha256(
                tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/fixture/exchange_info.json"
            ),
            "funding_info_output_path": "data/external/btc_perpetual/binance_usdm/bundles/fixture/funding_info.json",
            "funding_info_output_sha256": _sha256(
                tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/fixture/funding_info.json"
            ),
            "post_import_validation_command": "make validate-btc-public-data-bundle",
            "blockers": [],
        },
    )

    registry = build_btc_research_registry(repo_root=tmp_path, generated_at="2026-05-22T00:00:00Z")
    manual_import = registry["btc"]["manual_metadata_import_status"]

    assert registry["btc"]["latest_manual_metadata_import_report"] == (
        "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json"
    )
    assert manual_import["status"] == "verified"
    assert manual_import["captured_at"] == "2026-05-22T00:00:00Z"
    assert manual_import["bundle_dir"] == "data/external/btc_perpetual/binance_usdm/bundles/fixture"
    assert manual_import["bundle_dir_exists"] is True
    assert manual_import["bundle_dir_matches_selected"] is True
    assert manual_import["bundle_exchange_info_exists"] is True
    assert manual_import["bundle_funding_info_exists"] is True
    assert manual_import["bundle_exchange_info_output_hash_verified"] is True
    assert manual_import["bundle_funding_info_output_hash_verified"] is True
    assert manual_import["valid_for_completion"] is True
    assert manual_import["blockers"] == []
    assert manual_import["raw_input_files"]["exchange_info_raw"]["sha256"] == "a" * 64
    assert manual_import["raw_input_files"]["funding_info_raw"]["size_bytes"] == 2


def test_btc_research_registry_rejects_weak_manual_import_for_completion(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json",
        {
            "schema_version": "btc_manual_metadata_import_report_v1",
            "status": "verified",
            "generated_at": "2026-05-22T00:00:00Z",
            "dry_run": False,
            "captured_at": "2026-05-22T08:00:00+08:00",
            "writes_performed": True,
            "exchange_info_verified": False,
            "funding_info_verified": True,
            "bundle_dir": "data/external/btc_perpetual/binance_usdm/bundles/fixture",
            "raw_input_files": {
                "exchange_info_raw": {
                    "path": "exchange_info_raw.json",
                    "exists": True,
                    "size_bytes": 0,
                    "sha256": "a" * 64,
                    "http_status_file": "exchange_info_http_status.txt",
                    "http_status": 200,
                    "http_status_verified": True,
                },
                "funding_info_raw": {
                    "path": "funding_info_raw.json",
                    "exists": True,
                    "size_bytes": 2,
                    "sha256": "z" * 64,
                },
            },
            "post_import_validation_command": "make validate-btc-public-data-bundle",
            "blockers": [],
        },
    )

    registry = build_btc_research_registry(repo_root=tmp_path, generated_at="2026-05-22T00:00:00Z")
    manual_import = registry["btc"]["manual_metadata_import_status"]

    assert manual_import["status"] == "verified"
    assert manual_import["valid_for_completion"] is False
    assert "btc_manual_metadata_import_exchange_info_not_verified" in manual_import["blockers"]
    assert "btc_manual_metadata_import_captured_at_missing" in manual_import["blockers"]
    assert "btc_exchange_info_raw_import_provenance_missing" in manual_import["blockers"]
    assert "btc_funding_info_raw_import_provenance_missing" in manual_import["blockers"]


def test_btc_research_registry_rejects_blank_manual_import_raw_path(tmp_path: Path) -> None:
    report = _verified_import_report()
    report["raw_input_files"]["exchange_info_raw"]["path"] = "   "
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)

    registry = build_btc_research_registry(repo_root=tmp_path, generated_at="2026-05-22T00:00:00Z")
    manual_import = registry["btc"]["manual_metadata_import_status"]

    assert manual_import["status"] == "verified"
    assert manual_import["valid_for_completion"] is False
    assert "btc_exchange_info_raw_import_provenance_missing" in manual_import["blockers"]


def test_btc_research_registry_rejects_missing_manual_import_bundle_dir(tmp_path: Path) -> None:
    report = _verified_import_report()
    report.pop("bundle_dir")
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)

    registry = build_btc_research_registry(repo_root=tmp_path, generated_at="2026-05-22T00:00:00Z")
    manual_import = registry["btc"]["manual_metadata_import_status"]

    assert manual_import["status"] == "verified"
    assert manual_import["valid_for_completion"] is False
    assert "btc_manual_metadata_import_bundle_dir_missing" in manual_import["blockers"]


def test_btc_research_registry_rejects_manual_import_bundle_dir_not_selected(tmp_path: Path) -> None:
    _write_selected_bundle(tmp_path)
    report = _verified_import_report()
    report["bundle_dir"] = "data/external/btc_perpetual/binance_usdm/bundles/not_selected"
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)

    registry = build_btc_research_registry(repo_root=tmp_path, generated_at="2026-05-22T00:00:00Z")
    manual_import = registry["btc"]["manual_metadata_import_status"]

    assert manual_import["status"] == "verified"
    assert manual_import["bundle_dir_exists"] is False
    assert manual_import["bundle_dir_matches_selected"] is False
    assert manual_import["valid_for_completion"] is False
    assert "btc_manual_metadata_import_bundle_dir_missing_on_disk" in manual_import["blockers"]
    assert "btc_manual_metadata_import_bundle_dir_not_selected_bundle" in manual_import["blockers"]


def test_btc_research_registry_rejects_missing_manual_import_validation_command(tmp_path: Path) -> None:
    report = _verified_import_report()
    report.pop("post_import_validation_command")
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)

    registry = build_btc_research_registry(repo_root=tmp_path, generated_at="2026-05-22T00:00:00Z")
    manual_import = registry["btc"]["manual_metadata_import_status"]

    assert manual_import["status"] == "verified"
    assert manual_import["valid_for_completion"] is False
    assert "btc_manual_metadata_import_validation_command_missing" in manual_import["blockers"]


def test_btc_research_registry_rejects_schema_versionless_manual_import_for_completion(tmp_path: Path) -> None:
    report = _verified_import_report()
    report.pop("schema_version")
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)

    registry = build_btc_research_registry(repo_root=tmp_path, generated_at="2026-05-22T00:00:00Z")
    manual_import = registry["btc"]["manual_metadata_import_status"]

    assert manual_import["status"] == "verified"
    assert manual_import["valid_for_completion"] is False
    assert "btc_manual_metadata_import_schema_version_missing_or_invalid" in manual_import["blockers"]


def test_btc_research_registry_can_surface_future_gate_pass_as_current_candidate(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json",
        {
            "schema_version": "btc_candidate_gate_audit_report_v1",
            "status": "pass",
            "strategy_id": "btc_future_candidate_v1",
            "candidate_passed_internal_gate": 1,
            "paper_review_pending_allowed": True,
            "paper_queue_status": "pending_review",
            "blockers": [],
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

    registry = build_btc_research_registry(repo_root=tmp_path, generated_at="2026-05-22T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(registry, schema)
    assert registry["paper_queue"] == "PENDING_REVIEW"
    assert registry["live"] == "FROZEN"
    assert registry["btc"]["paper_queue_status"] == "pending_review"
    assert registry["btc"]["candidate_passed_internal_gate"] == 1
    assert registry["btc"]["current_candidates"] == ["btc_future_candidate_v1"]


def test_btc_research_registry_schema_rejects_pending_review_without_current_candidate() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    registry["paper_queue"] = "PENDING_REVIEW"
    registry["btc"]["paper_queue_status"] = "pending_review"
    registry["btc"]["candidate_passed_internal_gate"] = 1
    registry["btc"]["current_candidates"] = []

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(registry, schema)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_selected_bundle(tmp_path: Path) -> None:
    config = tmp_path / "configs/data/btc_perpetual_sources.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "\n".join(
            [
                "providers:",
                "  binance_usdm:",
                "    root: data/external/btc_perpetual/binance_usdm/",
                "    selected_bundle_id: fixture",
            ]
        ),
        encoding="utf-8",
    )
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/fixture"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "exchange_info.json").write_text("{}", encoding="utf-8")
    (bundle / "funding_info.json").write_text("{}", encoding="utf-8")


def _verified_import_report() -> dict[str, object]:
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
        "exchange_info_output_sha256": hashlib.sha256(b"{}").hexdigest(),
        "funding_info_output_path": "data/external/btc_perpetual/binance_usdm/bundles/fixture/funding_info.json",
        "funding_info_output_sha256": hashlib.sha256(b"{}").hexdigest(),
        "post_import_validation_command": "make validate-btc-public-data-bundle",
        "blockers": [],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
