from __future__ import annotations

from quant_crypto.monitoring.btc_root_cause_dag import build_btc_root_cause_dag, root_cause_ids_for_blockers


def test_flat_heartbeat_and_data_insufficient_blockers_do_not_become_runtime_not_connected() -> None:
    blockers = [
        "btc_runtime_ready_waiting_non_flat_sample",
        "paper_runtime_replay:waiting_for_current_gate_eligible_non_flat_fill",
        "exchange_runtime_gap:btc_execution_latency_model:data_insufficient",
        "exchange_runtime_gap:btc_queue_model:data_insufficient",
        "btc_public_ws_l2_event_history_days_insufficient",
        "strategy_readiness:exchange_runtime_gap:btc_execution_latency_model_missing_public_ws_coverage_is_not_order_latency",
        "strategy_readiness:exchange_runtime_gap:btc_queue_model_missing_public_l2_coverage_is_not_exchange_queue_position",
        "perpetual_execution:btc_perp_exec_depth_aware_slippage_history_verified",
        "perpetual_execution:btc_perp_exec_current_mark_price_available",
        "perpetual_execution:btc_perp_exec_mark_used_for_liquidation_risk",
        "gate_dashboard:btc_gate_dashboard_artifact_blocker:perpetual_execution_evidence:btc_perp_exec_current_mark_price_available",
        "strategy_readiness:gate_dashboard:btc_gate_dashboard_artifact_blocker:perpetual_execution_evidence:btc_perp_exec_mark_used_for_liquidation_risk",
        "perpetual_objective:btc_perpetual_gate_objective:fill_mapping_not_older_than_runtime_replay",
        "perpetual_execution:btc_perp_exec_exchange_runtime_real_or_paper_replay_ready",
        "gate_dashboard:btc_gate_dashboard_micro_live_preflight_blocked",
        "kill_switch:status:incomplete_research_only",
    ]

    root_ids = set(root_cause_ids_for_blockers(blockers))

    assert "runtime_ready_waiting_non_flat_sample" in root_ids
    assert "data_wait" in root_ids
    assert "runtime_not_connected" not in root_ids

    dag = build_btc_root_cause_dag({"execution_gate": blockers})
    assert "runtime_not_connected" not in {row["root_cause_id"] for row in dag["root_cause_matrix"]}


def test_true_local_fixture_only_runtime_blocker_still_maps_to_runtime_not_connected() -> None:
    root_ids = set(
        root_cause_ids_for_blockers(
            ["exchange_runtime_gap:btc_runtime_contract_local_fixture_only_public_or_paper_runtime_layer_required"]
        )
    )

    assert "runtime_not_connected" in root_ids


def test_operator_paper_intake_envelope_fields_are_not_uncategorized() -> None:
    blockers = [
        "micro_live_preflight:operator_paper_intake_envelope_initial_principal_missing",
        "micro_live_preflight:operator_paper_intake_envelope_daily_order_limit_missing",
        "micro_live_preflight:operator_paper_intake_envelope_leverage_missing",
        "micro_live_preflight:operator_paper_intake_envelope_order_notional_missing",
    ]

    root_ids = set(root_cause_ids_for_blockers(blockers))

    assert root_ids == {"operator_paper_intake_envelope_missing"}


def test_missing_cost_model_inputs_are_data_wait_not_uncategorized() -> None:
    blockers = [
        "cost_model:btc_maker_taker_fee_tier_missing",
        "cost_model:btc_slippage_bps_missing",
    ]

    root_ids = set(root_cause_ids_for_blockers(blockers))

    assert root_ids == {"data_wait"}


def test_missing_api_key_classes_are_manual_security_inputs_not_uncategorized() -> None:
    blockers = [
        "api_key_audit:btc_api_key_class_missing:paper_trade",
        "api_key_audit:btc_api_key_class_missing:live_trade",
    ]

    assert set(root_cause_ids_for_blockers(blockers)) == {"manual_review_approval_missing"}


def test_paper_readiness_upstream_data_gaps_are_data_wait_not_uncategorized() -> None:
    blockers = [
        "paper_readiness:btc_paper_readiness_bundle_preflight_not_pass",
        "paper_readiness:btc_paper_readiness_cost_model_not_pass",
        "paper_readiness:btc_paper_readiness_fee_tier_cost_model_not_verified",
        "paper_readiness:btc_paper_readiness_objective_audit_incomplete",
        "paper_readiness:btc_paper_readiness_tail_dependency_not_pass",
    ]

    assert set(root_cause_ids_for_blockers(blockers)) == {"data_wait"}


def test_legacy_paper_gate_blockers_have_stable_root_causes() -> None:
    blockers = [
        "micro_live_preflight:paper_risk_circuit_breaker_drill:missing_input:paper_risk_circuit_breaker_drill",
        "paper_readiness:btc_compression_expansion_archived",
        "paper_readiness:btc_compression_expansion_failed_folds_require_repair_decision",
        "paper_readiness:btc_compression_expansion_full_ledger_event_pf_failed",
        "paper_readiness:btc_compression_expansion_regime_drag_unresolved",
        "paper_readiness:btc_event_ledger_manifest_missing",
        "paper_readiness:btc_external_evidence_paper_gate_not_ready",
        "paper_readiness:btc_external_evidence_private_execution_latency_model_missing",
    ]

    assert set(root_cause_ids_for_blockers(blockers)) == {
        "runtime_not_connected",
        "source_artifact_missing",
        "strategy_overfit_or_forward_gap",
    }

def test_intraday_research_blockers_are_strategy_or_derived_locks() -> None:
    blockers = [
        "paper_readiness:btc_intraday_event_ledger_gate_failed_regime_pass_rate",
        "paper_readiness:btc_intraday_event_ledger_paper_live_locked",
        "paper_readiness:btc_intraday_probe_no_net_positive_distribution_edge",
        "paper_readiness:btc_intraday_probe_requires_walk_forward_regime_cost_stress",
        "paper_readiness:btc_intraday_repair_full_event_ledger_retest_required",
        "paper_readiness:btc_intraday_tail_dependency_right_tail_concentrated",
    ]

    assert root_cause_ids_for_blockers(blockers) == ["strategy_overfit_or_forward_gap"]

def test_remaining_paper_readiness_blockers_have_stable_root_causes() -> None:
    blockers = [
        "paper_readiness:btc_next_hypothesis_all_probe_event_profit_factor_failed",
        "paper_readiness:btc_next_hypothesis_dual_trend_micro_surgery_rejected",
        "paper_readiness:btc_paper_readiness_paper_review_pending_not_allowed",
        "paper_readiness:btc_perpetual_cost_contract_not_complete",
        "paper_readiness:btc_strategy_family_selected_okx_bundle_history_too_short",
        "paper_readiness:btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model",
    ]

    assert set(root_cause_ids_for_blockers(blockers)) == {
        "data_wait",
        "manual_review_approval_missing",
        "strategy_overfit_or_forward_gap",
    }
