from __future__ import annotations

from pathlib import Path


READ_ONLY_BUILDERS = [
    Path("scripts/build_global_research_registry.py"),
    Path("scripts/build_us_equity_data_status_report.py"),
    Path("scripts/build_us_equity_factor_evidence_pack.py"),
    Path("scripts/build_us_equity_portfolio_canonical_report.py"),
    Path("scripts/build_us_equity_portfolio_fixture_event_ledger_report.py"),
    Path("scripts/build_us_equity_production_bundle_preflight_report.py"),
    Path("scripts/build_us_equity_provider_verification_report.py"),
    Path("scripts/build_btc_data_status_report.py"),
    Path("scripts/build_btc_perpetual_provider_verification_report.py"),
    Path("scripts/build_btc_funding_ledger_report.py"),
    Path("scripts/build_btc_cost_model_report.py"),
    Path("scripts/build_btc_fold_regime_contract_report.py"),
    Path("scripts/build_btc_tail_dependency_report.py"),
    Path("scripts/build_btc_candidate_gate_audit.py"),
    Path("scripts/build_btc_paper_readiness_report.py"),
    Path("scripts/build_btc_paper_validation_start_report.py"),
    Path("scripts/check_btc_paper_validation_readiness.py"),
    Path("scripts/build_btc_compression_expansion_attribution_bundle.py"),
    Path("scripts/build_btc_intraday_short_cycle_alpha_plan_report.py"),
    Path("scripts/build_btc_intraday_short_cycle_alpha_probe_report.py"),
    Path("scripts/build_btc_intraday_short_cycle_alpha_refinement_report.py"),
    Path("scripts/build_btc_intraday_short_cycle_event_ledger_report.py"),
    Path("scripts/build_btc_intraday_short_cycle_event_definition_repair_report.py"),
    Path("scripts/build_btc_intraday_short_cycle_repaired_event_ledger_report.py"),
    Path("scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py"),
    Path("scripts/build_btc_intraday_short_cycle_promotion_gate_report.py"),
    Path("scripts/build_btc_intraday_short_cycle_manual_review_packet.py"),
    Path("scripts/build_btc_intraday_short_cycle_research_candidate_definition_preflight.py"),
    Path("scripts/build_btc_intraday_short_cycle_research_candidate_definition_manifest.py"),
    Path("scripts/build_btc_intraday_short_cycle_remaining_external_evidence_status.py"),
    Path("scripts/build_btc_intraday_drift_guarded_fold_regime_source_reports.py"),
    Path("scripts/build_btc_true_scalping_microstructure_models.py"),
    Path("scripts/build_btc_true_scalping_microstructure_readiness_report.py"),
    Path("scripts/build_btc_true_scalping_l2_sample_quality_report.py"),
    Path("scripts/build_btc_true_scalping_l2_feature_diagnostics_report.py"),
    Path("scripts/build_btc_true_scalping_timestamp_aligned_l2_data_contract_report.py"),
    Path("scripts/build_btc_true_scalping_l2_aligned_capture_quality_report.py"),
    Path("scripts/build_btc_true_scalping_ws_l2_raw_capture_quality_report.py"),
    Path("scripts/build_btc_true_scalping_ws_order_book_replay_report.py"),
    Path("scripts/build_btc_true_scalping_ws_reconnect_resync_policy_report.py"),
    Path("scripts/build_btc_true_scalping_ws_latency_queue_diagnostics_report.py"),
    Path("scripts/build_btc_true_scalping_ws_l2_capture_coverage_report.py"),
    Path("scripts/build_btc_true_scalping_long_horizon_l2_tick_import_contract_report.py"),
    Path("scripts/build_btc_true_scalping_execution_queue_external_evidence_contract_report.py"),
    Path("scripts/build_btc_true_scalping_1m_proxy_feature_redesign_report.py"),
    Path("scripts/build_btc_true_scalping_research_design_review.py"),
    Path("scripts/build_btc_true_scalping_research_design_report.py"),
    Path("scripts/build_btc_true_scalping_event_ledger_prototype_report.py"),
    Path("scripts/build_btc_true_scalping_event_definition_redesign_report.py"),
    Path("scripts/run_btc_scalping_research_backtest.py"),
    Path("scripts/fetch_btc_okx_microstructure_public_data.py"),
    Path("scripts/fetch_btc_okx_l2_microstructure_public_samples.py"),
    Path("scripts/fetch_btc_okx_timestamp_aligned_l2_public_capture.py"),
    Path("scripts/fetch_btc_okx_public_ws_l2_raw_capture.py"),
    Path("scripts/run_btc_okx_public_ws_l2_segment_capture.py"),
    Path("scripts/build_btc_research_registry.py"),
    Path("scripts/check_artifact_lineage_health.py"),
]


def test_evidence_builders_do_not_import_broker_order_or_live_modules() -> None:
    forbidden_imports = [
        "from quant_us.live",
        "import quant_us.live",
        "from quant_us.execution",
        "import quant_us.execution",
        "from backend.app.services.us_quant",
        "import backend.app.services.us_quant",
    ]
    for path in READ_ONLY_BUILDERS:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        for token in forbidden_imports:
            assert token not in source, f"{path} imports {token}"


def test_evidence_builders_do_not_call_order_submission_surfaces() -> None:
    forbidden_tokens = [
        "AlpacaBroker(",
        "IBKRBroker(",
        "LiveRuntime(",
        "PaperRuntime(",
        "submit_order(",
        "place_order(",
        "create_order(",
    ]
    for path in READ_ONLY_BUILDERS:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in source, f"{path} calls {token}"


def test_paper_queue_locked_in_global_registry_artifact() -> None:
    registry_path = Path("artifacts/global_research_registry/research_registry.json")
    if not registry_path.exists():
        return
    source = registry_path.read_text(encoding="utf-8")

    assert '"paper_queue_status": "locked"' in source
    assert '"live_status": "frozen"' in source
